from dataclasses import dataclass
import ipaddress
from pathlib import Path
import os


COLLECTORS = ("auto", "socai", "xiaohongshu-cli", "opencli")
XIAOHONGSHU_COOKIE_SOURCES = ("auto", "chrome", "edge", "brave", "firefox", "safari")


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path.home() / "Documents" / "Codex" / "xhs-research-data"
    host: str = "127.0.0.1"
    port: int = 4318
    collector: str = "socai"
    socai_bin: str = "socai"
    xiaohongshu_cli_bin: str = "xhs"
    xiaohongshu_cookie_source: str = "auto"
    opencli_bin: str = "opencli"
    codex_bin: str = "codex"
    detail_ttl_days: int = 30
    author_ttl_days: int = 7
    max_author_notes: int = 300
    max_keywords_per_task: int = 5
    max_authors_per_task: int = 5
    research_workers: int = 1
    vision_workers: int = 1
    report_workers: int = 1

    def __post_init__(self):
        # Resolve the storage root once so the database, media, collector runtime,
        # service log and lifecycle lock can never disagree about where data
        # lives (notably for values such as ``~/xhs-research-data``).
        canonical = Path(self.data_dir).expanduser().resolve()
        object.__setattr__(self, "data_dir", canonical)
        collector = str(self.collector or "socai").strip().lower().replace("_", "-")
        aliases = {"xhs": "xiaohongshu-cli", "xiaohongshu": "xiaohongshu-cli"}
        collector = aliases.get(collector, collector)
        if collector not in COLLECTORS:
            raise ValueError(
                f"XHS_RESEARCH_COLLECTOR must be one of {', '.join(COLLECTORS)}"
            )
        object.__setattr__(self, "collector", collector)
        cookie_source = str(self.xiaohongshu_cookie_source or "auto").strip().lower()
        if cookie_source not in XIAOHONGSHU_COOKIE_SOURCES:
            raise ValueError(
                "XHS_RESEARCH_XIAOHONGSHU_COOKIE_SOURCE must be one of "
                f"{', '.join(XIAOHONGSHU_COOKIE_SOURCES)}"
            )
        object.__setattr__(self, "xiaohongshu_cookie_source", cookie_source)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "research.sqlite3"

    @property
    def socai_home(self) -> Path:
        return self.data_dir / ".socai"

    @property
    def collector_bin(self) -> str:
        if self.collector == "xiaohongshu-cli":
            return self.xiaohongshu_cli_bin
        if self.collector == "socai":
            return self.socai_bin
        if self.collector == "opencli":
            return self.opencli_bin
        return "multiple"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"


def is_loopback_host(host: str) -> bool:
    value = str(host or "").strip().lower()
    if value == "localhost":
        return True
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def load_settings() -> Settings:
    def workers(name: str, default: int = 1) -> int:
        return max(1, min(int(os.environ.get(name, default)), 4))

    def source_limit(name: str, default: int = 5) -> int:
        return max(1, min(int(os.environ.get(name, default)), 20))

    return Settings(
        data_dir=Path(os.environ.get("XHS_RESEARCH_DATA_DIR", Settings.data_dir)).expanduser().resolve(),
        host=os.environ.get("XHS_RESEARCH_HOST", "127.0.0.1"),
        port=int(os.environ.get("XHS_RESEARCH_PORT", "4318")),
        collector=os.environ.get("XHS_RESEARCH_COLLECTOR", "socai"),
        socai_bin=os.environ.get("SOCAI_BIN", "socai"),
        xiaohongshu_cli_bin=os.environ.get("XIAOHONGSHU_CLI_BIN", "xhs"),
        xiaohongshu_cookie_source=os.environ.get("XHS_RESEARCH_XIAOHONGSHU_COOKIE_SOURCE", "auto"),
        opencli_bin=os.environ.get("OPENCLI_BIN", "opencli"),
        codex_bin=os.environ.get("CODEX_BIN", "codex"),
        max_keywords_per_task=source_limit("XHS_RESEARCH_MAX_KEYWORDS_PER_TASK"),
        max_authors_per_task=source_limit("XHS_RESEARCH_MAX_AUTHORS_PER_TASK"),
        research_workers=workers("XHS_RESEARCH_RESEARCH_WORKERS"),
        vision_workers=workers("XHS_RESEARCH_VISION_WORKERS"),
        report_workers=workers("XHS_RESEARCH_REPORT_WORKERS"),
    )
