from pathlib import Path
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from typing import Callable, Dict, Iterable, Optional

from .config import Settings


MIN_SOCAI = (0, 4, 9)
MIN_XIAOHONGSHU_CLI = (0, 6, 4)
MIN_OPENCLI = (1, 8, 6)


def _version_tuple(value: str):
    match = re.search(r"(?:socai\s+)?(\d+)\.(\d+)\.(\d+)", value or "")
    return tuple(map(int, match.groups())) if match else (0, 0, 0)


def _default_resolver(name: str) -> Optional[str]:
    if name == "chrome":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return candidate
        return shutil.which("google-chrome") or shutil.which("chromium")
    return shutil.which(name)


def _default_version_reader(path: str) -> str:
    commands = ([path, "--version"], [path, "version", "--no-check"])
    for command in commands:
        try:
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        output = (result.stdout or result.stderr).strip()
        if result.returncode == 0 and output:
            return output
    return ""


def _default_port_probe(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def check_environment(
    settings: Settings,
    resolver: Callable[[str], Optional[str]] = _default_resolver,
    version_reader: Callable[[str], str] = _default_version_reader,
    port_probe: Callable[[str, int], bool] = _default_port_probe,
) -> Dict[str, object]:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    socai = resolver("socai")
    xiaohongshu_cli = resolver("xiaohongshu-cli")
    opencli = resolver("opencli")
    codex = resolver("codex")
    chrome = resolver("chrome")
    socai_version_text = version_reader(socai) if socai else ""
    socai_version = _version_tuple(socai_version_text)
    socai_status = "ok" if socai and socai_version >= MIN_SOCAI else (
        "upgrade_required" if socai else "missing"
    )
    xiaohongshu_cli_version_text = version_reader(xiaohongshu_cli) if xiaohongshu_cli else ""
    xiaohongshu_cli_version = _version_tuple(xiaohongshu_cli_version_text)
    xiaohongshu_cli_status = (
        "ok" if xiaohongshu_cli and xiaohongshu_cli_version >= MIN_XIAOHONGSHU_CLI
        else "upgrade_required" if xiaohongshu_cli else "missing"
    )
    opencli_version_text = version_reader(opencli) if opencli else ""
    opencli_version = _version_tuple(opencli_version_text)
    opencli_status = (
        "ok" if opencli and opencli_version >= MIN_OPENCLI
        else "upgrade_required" if opencli else "missing"
    )
    writable = os.access(settings.data_dir, os.W_OK)
    available = port_probe(settings.host, settings.port)
    dependencies = {
        "python": {
            "status": "ok" if sys.version_info >= (3, 9) else "upgrade_required",
            "version": platform.python_version(),
            "required": True,
        },
        "socai": {
            "status": socai_status,
            "path": socai,
            "version": ".".join(map(str, socai_version)) if socai else "",
            "required": False,
        },
        "xiaohongshu-cli": {
            "status": xiaohongshu_cli_status,
            "path": xiaohongshu_cli,
            "version": ".".join(map(str, xiaohongshu_cli_version)) if xiaohongshu_cli else "",
            "required": False,
        },
        "opencli": {
            "status": opencli_status,
            "path": opencli,
            "version": ".".join(map(str, opencli_version)) if opencli else "",
            "required": False,
            "requires_browser_bridge": True,
        },
        "codex": {
            "status": "ok" if codex else "missing_optional",
            "path": codex,
            "required": False,
        },
        "chrome": {
            "status": "ok" if chrome else "missing",
            "path": chrome,
            "required": True,
        },
    }
    ready_collectors = [
        name for name in ("socai", "xiaohongshu-cli", "opencli")
        if dependencies[name]["status"] == "ok"
    ]
    provider_ready = bool(ready_collectors)
    ready_for_collection = writable and provider_ready and all(
        dependencies[name]["status"] == "ok" for name in ("python", "chrome")
    )
    return {
        "routing_mode": "capability",
        "ready_collectors": ready_collectors,
        "ready_for_collection": ready_for_collection,
        "ready_for_ocr": ready_for_collection,
        "ready_for_vision": ready_for_collection and dependencies["codex"]["status"] == "ok",
        "dependencies": dependencies,
        "data_dir": {"path": str(settings.data_dir), "status": "writable" if writable else "not_writable"},
        "port": {"host": settings.host, "port": settings.port, "status": "available" if available else "in_use"},
    }


def installation_plan(system: Optional[str] = None, missing: Iterable[str] = ()) -> Dict[str, object]:
    system = system or platform.system()
    commands: Dict[str, str] = {}
    notes: Dict[str, str] = {}
    missing = set(missing)
    if "socai" in missing:
        commands["socai"] = (
            "curl -fsSL https://github.com/socai-io/socai/releases/latest/download/install.sh | sh"
            if system == "Darwin"
            else "$installer = Join-Path $env:TEMP 'socai-install.ps1'; "
            "Invoke-WebRequest -UseBasicParsing https://github.com/socai-io/socai/releases/latest/download/install.ps1 -OutFile $installer; "
            "Unblock-File $installer; & $installer"
        )
    if "xiaohongshu-cli" in missing:
        if shutil.which("uv"):
            commands["xiaohongshu-cli"] = "uv tool install xiaohongshu-cli"
        elif shutil.which("pipx"):
            commands["xiaohongshu-cli"] = "pipx install xiaohongshu-cli"
        elif system == "Darwin" and shutil.which("brew"):
            commands["xiaohongshu-cli"] = "brew install uv && uv tool install xiaohongshu-cli"
        else:
            notes["xiaohongshu-cli"] = (
                "请先安装 uv 或 pipx，再按官方说明安装 xiaohongshu-cli。"
            )
    if "opencli" in missing:
        if shutil.which("npm"):
            commands["opencli"] = "npm install -g @jackwener/opencli"
            notes["opencli"] = (
                "安装 CLI 后还需安装 OpenCLI Browser Bridge Chrome 扩展，并运行 opencli doctor。"
            )
        else:
            notes["opencli"] = "请先安装 Node.js 20 或更高版本，再运行 npm install -g @jackwener/opencli。"
    if "codex" in missing:
        notes["codex"] = "安装或打开 Codex，并完成登录；纯 OCR 模式可以暂不安装 Codex CLI。"
    if "chrome" in missing:
        if system == "Darwin" and shutil.which("brew"):
            commands["chrome"] = "brew install --cask google-chrome"
        elif system == "Windows":
            commands["chrome"] = "winget install --id Google.Chrome --exact --accept-package-agreements --accept-source-agreements"
        else:
            notes["chrome"] = "请从 Google Chrome 官方网站安装 Chrome，或安装 Chromium。"
    if "python" in missing:
        if system == "Darwin" and shutil.which("brew"):
            commands["python"] = "brew install python@3.12"
        elif system == "Windows":
            commands["python"] = "winget install --id Python.Python.3.12 --exact --accept-package-agreements --accept-source-agreements"
        else:
            notes["python"] = "请使用系统包管理器安装 Python 3.9 或更高版本。"
    return {"authorized": False, "system": system, "commands": commands, "notes": notes}


def _default_install_executor(command: str, system: str) -> int:
    if system == "Windows":
        result = subprocess.run(["powershell", "-NoProfile", "-Command", command], check=False)
    else:
        result = subprocess.run(["/bin/sh", "-c", command], check=False)
    return int(result.returncode)


def execute_installation(dependencies: Iterable[str], confirmed: bool, system: Optional[str] = None,
                         executor: Callable[[str, str], int] = _default_install_executor) -> Dict[str, object]:
    """执行白名单安装计划。调用方必须传入用户明确确认后的 confirmed=True。"""
    if not confirmed:
        raise PermissionError("dependency installation requires explicit user confirmation")
    dependencies = list(dict.fromkeys(str(value) for value in dependencies))
    plan = installation_plan(system=system, missing=dependencies)
    results: Dict[str, object] = {}
    commands = plan["commands"]
    notes = plan["notes"]
    for dependency in dependencies:
        command = commands.get(dependency)
        if not command:
            results[dependency] = {"status": "unsupported", "message": notes.get(dependency, "没有可用的自动安装方案")}
            continue
        returncode = executor(command, str(plan["system"]))
        results[dependency] = {
            "status": "installed" if returncode == 0 else "failed",
            "returncode": returncode,
            "command": command,
        }
    return results
