#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_DATA_DIR = Path.home() / "Documents/Codex/xhs-research-data"
DEVELOPMENT_DATA_DIR = Path.home() / "Documents/Codex/xhs-research-data-develop"


def _is_linked_worktree(root: Path) -> bool:
    """Return whether this checkout is a linked Git worktree."""
    return (root / ".git").is_file()


def configure_development_defaults():
    """Keep the linked development worktree isolated from the primary checkout."""
    root = Path(__file__).resolve().parent.parent
    if _is_linked_worktree(root):
        os.environ.setdefault("XHS_RESEARCH_PORT", "4319")
        os.environ.setdefault("XHS_RESEARCH_DATA_DIR", str(DEVELOPMENT_DATA_DIR))


def app_root() -> Path:
    configured = os.environ.get("XHS_RESEARCH_APP_DIR", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if (path / "xhs_research/cli.py").is_file():
            return path
        raise SystemExit(
            f"XHS_RESEARCH_APP_DIR 指向的工作台无效：{path}。"
            "请确认该目录中存在 xhs_research/cli.py。"
        )

    bundled = Path(__file__).resolve().parent / "workbench"
    if (bundled / "xhs_research/cli.py").is_file():
        return bundled
    raise SystemExit(
        f"小红书个人工作台 Skill 安装不完整：未找到 {bundled / 'xhs_research/cli.py'}。"
        "请重新安装完整的 xhs-research Skill 文件夹。"
    )


def base_url():
    configure_development_defaults()
    return f"http://{os.environ.get('XHS_RESEARCH_HOST','127.0.0.1')}:{os.environ.get('XHS_RESEARCH_PORT','4318')}"


def api(path, method="GET", payload=None, timeout=15):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(base_url() + path, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        message = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"本地服务请求失败（{exc.code}）：{message}")
    except URLError as exc:
        raise SystemExit(f"本地服务不可用：{exc.reason}。请先运行 start。")


def service_health(port=None):
    configure_development_defaults()
    host = os.environ.get("XHS_RESEARCH_HOST", "127.0.0.1")
    port = int(port if port is not None else os.environ.get("XHS_RESEARCH_PORT", "4318"))
    try:
        with urlopen(f"http://{host}:{port}/api/health", timeout=1) as response:
            value = json.loads(response.read())
            return value if isinstance(value, dict) and value.get("status") == "ok" else None
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def configured_data_dir():
    configure_development_defaults()
    return Path(os.environ.get("XHS_RESEARCH_DATA_DIR", DEFAULT_DATA_DIR)).expanduser().resolve()


def compatible_health(value):
    if not value or int(value.get("api_contract") or 0) < 2 or not value.get("runtime_locking"):
        return False
    try:
        same_data = Path(value.get("data_dir", "")).expanduser().resolve() == configured_data_dir()
        return same_data and value.get("routing_mode") == "capability"
    except (OSError, TypeError, ValueError):
        return False


def is_healthy():
    return compatible_health(service_health())


def start_service():
    configure_development_defaults()
    target_port = int(os.environ.get("XHS_RESEARCH_PORT", "4318"))
    current = service_health(target_port)
    if compatible_health(current):
        return {"status": "already_running", "url": base_url() + "/#/overview"}
    if current:
        raise SystemExit(
            f"端口 {target_port} 上仍运行旧版或其他数据目录的服务；请先正常停止该进程再启动新版。"
        )
    for other_port in (4318, 4319, 4320):
        if other_port == target_port:
            continue
        other = service_health(other_port)
        if not other:
            continue
        try:
            same_data = Path(other.get("data_dir", "")).expanduser().resolve() == configured_data_dir()
        except (OSError, TypeError, ValueError):
            same_data = False
        if same_data:
            raise SystemExit(
                f"检测到端口 {other_port} 的服务正在使用同一数据目录；"
                "请先停止旧服务，或为当前分支设置独立的 XHS_RESEARCH_DATA_DIR。"
            )
    root = app_root()
    data_dir = configured_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    log = open(data_dir / "service.log", "a", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    subprocess.Popen([sys.executable, "-m", "xhs_research", "serve", "--no-open"], cwd=root, env=env,
                     stdout=log, stderr=log, start_new_session=True)
    for _ in range(30):
        time.sleep(0.2)
        if is_healthy():
            return {"status": "started", "url": base_url() + "/#/overview"}
    raise SystemExit(f"服务未能启动，请查看日志：{data_dir / 'service.log'}")


def create_project_and_task(args, mode):
    if not is_healthy():
        start_service()
    project = api("/api/projects", "POST", {"name": args.name, "research_type": mode, "config": {}})
    source = ({"profile_urls": args.profile_url or [], "user_keywords": args.user_keyword or []} if mode == "author"
              else {"keywords": args.keyword, "filters": {"sort": args.sort, "publish_time": args.publish_time}})
    if mode == "author" and not source["profile_urls"] and not source["user_keywords"]:
        raise SystemExit("作者调研至少需要一个 --profile-url 或 --user-keyword。")
    task_payload = {
        "mode": mode, "project_id": project["id"], "created_from": "codex", "run_mode": "incremental",
        "source": source, "limits": {"discovery": args.discovery, "deep": args.deep},
        "user_limits": {"discovery": getattr(args, "user_discovery", 5)},
        "image_analysis": {"mode": "ocr-only", "vision_ratio": 0, "vision_count": 0},
    }
    task = create_initial_task_with_cleanup(project, task_payload)
    return {"project_id": project["id"], "task_id": task["id"], "status": task["status"],
            "url": base_url() + f"/#/tasks/{task['id']}"}


def create_mixed_project_and_task(args):
    if not is_healthy():
        start_service()
    keywords = args.keyword or []
    profiles = args.profile_url or []
    user_keywords = args.user_keyword or []
    if not keywords and not profiles and not user_keywords:
        raise SystemExit("综合调研至少需要一个 --keyword、--profile-url 或 --user-keyword。")
    project = api("/api/projects", "POST", {
        "name": args.name, "research_type": "mixed", "config": {}, "description": args.topic,
    })
    task_payload = {
        "mode": "mixed", "project_id": project["id"], "topic": args.topic,
        "created_from": "codex", "run_mode": "incremental",
        "source": {"keywords": keywords, "profile_urls": profiles, "user_keywords": user_keywords,
                   "filters": {"sort": args.sort, "publish_time": args.publish_time}},
        "user_limits": {"discovery": args.user_discovery},
        "keyword_limits": {"discovery": args.keyword_discovery, "deep": args.keyword_deep},
        "author_limits": {"discovery": args.author_discovery, "deep": args.author_deep},
        "image_analysis": {"mode": "ocr-only", "vision_ratio": 0, "vision_count": 0},
    }
    task = create_initial_task_with_cleanup(project, task_payload)
    return {"project_id": project["id"], "task_id": task["id"], "status": task["status"],
            "url": base_url() + f"/#/tasks/{task['id']}"}


def create_initial_task_with_cleanup(project, task_payload):
    """Create an initial task without leaving a confirmed-empty orphan project."""
    try:
        return api("/api/tasks", "POST", task_payload)
    except SystemExit:
        # The request may have reached the server even when the client did not
        # receive its response. Only remove a project after a fresh task query
        # proves it is empty; require_empty closes the final race on the server.
        try:
            tasks = api(f"/api/projects/{project['id']}/tasks")
            if not tasks:
                api(f"/api/projects/{project['id']}?require_empty=true", "DELETE")
        except SystemExit:
            pass
        raise


def configuration_summary(configuration):
    """Return the update-confirmation fields that a person needs to verify."""
    configuration = configuration or {}
    source = configuration.get("source") or {}
    limits = configuration.get("limits") or {}
    mode = configuration.get("mode", "")
    summary = {
        "mode": mode,
        "topic": configuration.get("topic", ""),
        "keywords": source.get("keywords") or [],
        "user_keywords": source.get("user_keywords") or [],
        "user_discovery": (configuration.get("user_limits") or {}).get("discovery", 5),
        "authors": (source.get("author_ids") or source.get("profile_urls") or
                    [value for value in (source.get("author_id"), source.get("profile_url")) if value]),
        "filters": source.get("filters") or {},
        "force_refresh": bool(configuration.get("force_refresh", False)),
    }
    if mode == "mixed":
        keyword_limits = configuration.get("keyword_limits") or limits
        author_limits = configuration.get("author_limits") or limits
        summary["keyword_discovery"] = keyword_limits.get("discovery", 50)
        summary["keyword_deep"] = keyword_limits.get("deep", 0)
        summary["author_discovery"] = author_limits.get("discovery", 50)
        summary["author_deep"] = author_limits.get("deep", 0)
    else:
        summary["discovery"] = limits.get("discovery", 50)
        summary["deep"] = limits.get("deep", 0)
    return summary


def update_project(args):
    if not is_healthy():
        start_service()
    project = api(f"/api/projects/{args.project_id}")
    tasks = [task for task in api(f"/api/projects/{args.project_id}/tasks")
             if task.get("task_type") == "research"]
    if not tasks:
        raise SystemExit("该项目还没有可复用的任务配置，无法更新调研。")
    latest = tasks[0]
    if args.source_task_id:
        latest = next((task for task in tasks if task.get("id") == args.source_task_id), None)
        if not latest:
            raise SystemExit("指定的配置来源任务不属于该项目，无法发起更新调研。")
    configuration = latest.get("input_json") or {}
    if not args.confirm:
        return {
            "confirmation_required": True,
            "project_id": args.project_id,
            "project_name": project.get("name", ""),
            "configuration_source": {
                "task_id": latest.get("id", ""),
                "created_at": latest.get("created_at", ""),
            },
            "configuration": configuration,
            "configuration_summary": configuration_summary(configuration),
            "message": "请向用户展示最近一次任务配置和配置摘要；综合调研必须分别展示关键词发现数量、关键词深度搜索数量、作者发现数量和作者深度搜索数量。只有用户明确确认后，才使用 --confirm 发起更新调研。",
            "confirm_command": (
                f"python3 scripts/xhs_research.py update --project-id {args.project_id} "
                f"--source-task-id {latest.get('id', '')} --confirm"
            ),
        }
    if not args.source_task_id:
        raise SystemExit("确认更新时必须通过 --source-task-id 指定刚刚展示给用户的配置来源任务。")
    rerun_payload = {
        "source_task_id": latest.get("id", ""),
        "created_from": "codex",
    }
    task = api(f"/api/projects/{args.project_id}/run", "POST", rerun_payload)
    return {
        "confirmation_required": False,
        "project_id": args.project_id,
        "task_id": task["id"],
        "status": task["status"],
        "configuration_source_task_id": latest.get("id", ""),
        "url": task.get("url") or base_url() + f"/#/tasks/{task['id']}",
    }


def cancel_task(args):
    if not is_healthy():
        start_service()
    return api(f"/api/tasks/{args.task_id}/cancel", "POST", {})


def enhance_vision(args):
    if not is_healthy():
        start_service()
    project = api(f"/api/projects/{args.project_id}")
    status = api(f"/api/projects/{args.project_id}/vision-status")
    settings = api("/api/settings")
    if not args.confirm:
        return {
            "confirmation_required": True,
            "project_id": args.project_id,
            "project_name": project.get("name", ""),
            "vision_status": status,
            "configuration": {
                "mode": settings.get("vision_analysis_mode"),
                "vision_ratio": settings.get("vision_analysis_ratio"),
                "vision_count": settings.get("vision_analysis_count"),
                "vision_max_count": settings.get("vision_analysis_max_count"),
                "vision_batch_size": settings.get("vision_analysis_batch_size"),
                "only_unanalyzed": True,
            },
            "confirm_command": f"python3 scripts/xhs_research.py enhance-vision --project-id {args.project_id} --confirm",
        }
    configuration = {key: value for key, value in {
        "mode": args.mode,
        "vision_ratio": args.vision_ratio,
        "vision_count": args.min_count,
        "vision_max_count": args.max_count,
        "vision_batch_size": args.batch_size,
    }.items() if value is not None}
    task = api(f"/api/projects/{args.project_id}/vision", "POST", {"created_from": "codex", "configuration": configuration})
    return {"confirmation_required": False, "project_id": args.project_id, "task_id": task["id"],
            "status": task["status"], "url": task.get("url") or base_url() + f"/#/tasks/{task['id']}"}


def common(parser):
    parser.add_argument("--name", required=True)
    parser.add_argument("--discovery", type=int, default=50)
    parser.add_argument("--deep", type=int, default=0)


def parser():
    result = argparse.ArgumentParser(description="小红书个人工作台 Skill 薄入口")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("check-env")
    install = sub.add_parser("install-deps")
    install.add_argument("--dependency", action="append", required=True)
    install.add_argument("--confirm", action="store_true")
    sub.add_parser("start")
    author = sub.add_parser("create-author"); common(author); author.add_argument("--profile-url", action="append")
    author.add_argument("--user-keyword", action="append"); author.add_argument("--user-discovery", type=int, default=5)
    keyword = sub.add_parser("create-keyword"); common(keyword); keyword.add_argument("--keyword", action="append", required=True)
    keyword.add_argument("--sort", default="最多点赞"); keyword.add_argument("--publish-time", default="半年内")
    mixed = sub.add_parser("create-mixed")
    mixed.add_argument("--name", required=True); mixed.add_argument("--topic", required=True)
    mixed.add_argument("--keyword", action="append"); mixed.add_argument("--profile-url", action="append")
    mixed.add_argument("--user-keyword", action="append"); mixed.add_argument("--user-discovery", type=int, default=5)
    mixed.add_argument("--keyword-discovery", type=int, default=50); mixed.add_argument("--keyword-deep", type=int, default=0)
    mixed.add_argument("--author-discovery", type=int, default=50); mixed.add_argument("--author-deep", type=int, default=0)
    mixed.add_argument("--sort", default="最多点赞"); mixed.add_argument("--publish-time", default="半年内")
    status = sub.add_parser("status"); status.add_argument("--task-id", required=True)
    project = sub.add_parser("project"); project.add_argument("--project-id", required=True, type=int)
    update = sub.add_parser("update"); update.add_argument("--project-id", required=True, type=int); update.add_argument("--source-task-id"); update.add_argument("--confirm", action="store_true")
    cancel = sub.add_parser("cancel"); cancel.add_argument("--task-id", required=True)
    vision = sub.add_parser("enhance-vision"); vision.add_argument("--project-id", required=True, type=int); vision.add_argument("--confirm", action="store_true")
    vision.add_argument("--mode", choices=["vision-selective", "vision-all"])
    vision.add_argument("--vision-ratio", type=float)
    vision.add_argument("--min-count", type=int)
    vision.add_argument("--max-count", type=int)
    vision.add_argument("--batch-size", type=int)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "check-env":
        root = app_root(); env = os.environ.copy(); env["PYTHONPATH"] = str(root)
        result = subprocess.run([sys.executable, "-m", "xhs_research", "check-env", "--json", "--install-plan"], cwd=root, env=env)
        return result.returncode
    if args.command == "install-deps":
        root = app_root(); env = os.environ.copy(); env["PYTHONPATH"] = str(root)
        command = [sys.executable, "-m", "xhs_research", "install-deps"]
        for dependency in args.dependency:
            command.extend(["--dependency", dependency])
        if args.confirm:
            command.append("--confirm")
        return subprocess.run(command, cwd=root, env=env).returncode
    if args.command == "start": result = start_service()
    elif args.command == "create-author": result = create_project_and_task(args, "author")
    elif args.command == "create-keyword": result = create_project_and_task(args, "keyword")
    elif args.command == "create-mixed": result = create_mixed_project_and_task(args)
    elif args.command == "status": result = api(f"/api/tasks/{args.task_id}")
    elif args.command == "cancel": result = cancel_task(args)
    elif args.command == "enhance-vision": result = enhance_vision(args)
    elif args.command == "project":
        project = api(f"/api/projects/{args.project_id}")
        result = {"project": project, "posts": api(f"/api/projects/{args.project_id}/posts"),
                  "authors": api(f"/api/projects/{args.project_id}/authors"),
                  "reports": api(f"/api/projects/{args.project_id}/reports")}
    else:
        result = update_project(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
