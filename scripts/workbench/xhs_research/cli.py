import argparse
import json
from pathlib import Path
import signal
import shutil
import sys
import threading
import webbrowser

from .config import Settings, load_settings
from .db import Database
from .ai_reporting import CodexReportProvider
from .keyword_generation import CodexKeywordProvider
from .opencli import OpenCliClient
from .ocr import RapidOCRProvider
from .envcheck import check_environment, execute_installation, installation_plan
from .runner import TaskRunner
from .server import ResearchApplication, create_server
from .socai import SocaiClient
from .vision import CodexVisionProvider
from .xiaohongshu_cli import XiaohongshuCliClient


APP_ROOT = Path(__file__).resolve().parent.parent


def _resolve_binary(configured: str, fallback: str = "") -> str:
    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return str(candidate)
    found = shutil.which(configured)
    if found:
        return found
    if fallback and Path(fallback).is_file():
        return fallback
    return configured


def normalized_settings(settings: Settings) -> Settings:
    return Settings(
        data_dir=settings.data_dir,
        host=settings.host,
        port=settings.port,
        collector=settings.collector,
        socai_bin=_resolve_binary(settings.socai_bin, str(Path.home() / ".socai/bin/socai")),
        xiaohongshu_cli_bin=_resolve_binary(settings.xiaohongshu_cli_bin),
        opencli_bin=_resolve_binary(settings.opencli_bin),
        codex_bin=_resolve_binary(settings.codex_bin, "/Applications/ChatGPT.app/Contents/Resources/codex"),
        detail_ttl_days=settings.detail_ttl_days,
        author_ttl_days=settings.author_ttl_days,
        max_author_notes=settings.max_author_notes,
        max_keywords_per_task=settings.max_keywords_per_task,
        max_authors_per_task=settings.max_authors_per_task,
        research_workers=settings.research_workers,
        vision_workers=settings.vision_workers,
        report_workers=settings.report_workers,
    )


def build_application(settings: Settings, enable_vision: bool = True) -> ResearchApplication:
    settings = normalized_settings(settings)
    db = Database(settings.database_path)

    def xiaohongshu_cookie_source():
        stored = db.get_app_settings().get("xiaohongshu_cookie_source")
        return stored if stored is not None else settings.xiaohongshu_cookie_source

    collectors = {
        "socai": SocaiClient(settings.socai_bin, settings.data_dir),
        "xiaohongshu-cli": XiaohongshuCliClient(
            settings.xiaohongshu_cli_bin,
            settings.data_dir,
            cookie_source=xiaohongshu_cookie_source,
        ),
        "opencli": OpenCliClient(settings.opencli_bin, settings.data_dir),
    }
    codex_available = Path(settings.codex_bin).is_file() or shutil.which(settings.codex_bin)
    vision = CodexVisionProvider(settings.codex_bin, work_dir=settings.data_dir / "vision-tmp") if enable_vision and codex_available else None
    reports = CodexReportProvider(settings.codex_bin, work_dir=settings.data_dir / "report-tmp") if enable_vision and codex_available else None
    keyword_provider = CodexKeywordProvider(
        settings.codex_bin,
        work_dir=settings.data_dir / "keyword-tmp",
    ) if enable_vision and codex_available else None
    runner = TaskRunner(db, collectors=collectors, default_collector=settings.collector,
                        vision_provider=vision, ocr_provider=RapidOCRProvider(), report_provider=reports, detail_ttl_days=settings.detail_ttl_days,
                        author_ttl_days=settings.author_ttl_days)
    built_web_root = APP_ROOT / "web" / "dist"
    if not (built_web_root / "index.html").is_file():
        raise FileNotFoundError(
            f"Ant Design Pro 工作台尚未构建：{built_web_root / 'index.html'}。"
            "请先在 scripts/workbench/web 中运行 npm install && npm run build。"
        )
    return ResearchApplication(
        settings,
        db,
        runner,
        built_web_root,
        keyword_provider=keyword_provider,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xhs-research", description="小红书个人工作台")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check-env", help="检查采集 CLI、Chrome、Codex 和本地存储")
    check.add_argument("--json", action="store_true")
    check.add_argument("--install-plan", action="store_true")
    serve = commands.add_parser("serve", help="启动本地服务和 Web 工作台")
    serve.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    serve.add_argument("--ocr-only", action="store_true", help="不启用 Codex 读图")
    install = commands.add_parser("install-deps", help="在用户明确确认后自动安装缺失依赖")
    install.add_argument("--dependency", action="append", required=True, help="要安装的依赖，可重复")
    install.add_argument("--confirm", action="store_true", help="确认执行环境修改")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    settings = normalized_settings(load_settings())
    if args.command == "check-env":
        def resolver(name):
            if name == "socai":
                return settings.socai_bin if Path(settings.socai_bin).is_file() else shutil.which(settings.socai_bin)
            if name == "codex":
                return settings.codex_bin if Path(settings.codex_bin).is_file() else shutil.which(settings.codex_bin)
            if name == "xiaohongshu-cli":
                return settings.xiaohongshu_cli_bin if Path(settings.xiaohongshu_cli_bin).is_file() else shutil.which(settings.xiaohongshu_cli_bin)
            if name == "opencli":
                return settings.opencli_bin if Path(settings.opencli_bin).is_file() else shutil.which(settings.opencli_bin)
            from .envcheck import _default_resolver
            return _default_resolver(name)
        result = check_environment(settings, resolver=resolver)
        if args.install_plan:
            missing = [
                name for name, value in result["dependencies"].items()
                if value["status"] != "ok" and value.get("required")
            ]
            if not result.get("ready_collectors"):
                missing.extend(
                    name for name in ("socai", "xiaohongshu-cli")
                    if result["dependencies"][name]["status"] != "ok"
                )
            result["installation_plan"] = installation_plan(missing=missing)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("环境可用" if result["ready_for_collection"] else "环境尚未就绪")
            for name, value in result["dependencies"].items():
                print(f"- {name}: {value['status']}")
        return 0 if result["ready_for_collection"] else 2
    if args.command == "serve":
        app = build_application(settings, enable_vision=not args.ocr_only)
        server = create_server(settings.host, settings.port, app, claim_runtime=True)
        actual_port = server.server_address[1]
        url = f"http://{settings.host}:{actual_port}/#/overview"
        print(f"小红书个人工作台已启动：{url}", flush=True)
        if not args.no_open:
            webbrowser.open(url)
        stopping = threading.Event()
        previous_handlers = {}

        def request_stop(_signum, _frame):
            if stopping.is_set():
                return
            stopping.set()
            app.signal_shutdown()
            # HTTPServer.shutdown() waits for serve_forever(), so it must not run
            # in the signal handler's main thread.
            threading.Thread(target=server.shutdown, name="xhs-research-shutdown", daemon=True).start()

        for signum in (signal.SIGTERM, signal.SIGHUP):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, request_stop)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            request_stop(signal.SIGINT, None)
        finally:
            app.signal_shutdown()
            server.server_close()
            app.shutdown()
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)
        return 0
    if args.command == "install-deps":
        if not args.confirm:
            print(json.dumps({"status": "confirmation_required", "dependencies": args.dependency}, ensure_ascii=False))
            return 3
        result = execute_installation(args.dependency, confirmed=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if all(value["status"] == "installed" for value in result.values()) else 4
    return 1


if __name__ == "__main__":
    sys.exit(main())
