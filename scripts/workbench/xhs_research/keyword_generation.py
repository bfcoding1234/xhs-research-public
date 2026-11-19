from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Dict, Iterable, List, Optional
import uuid

from .codex_process import run_codex_process


KEYWORD_PROMPT_VERSION = "keyword-v2"
KEYWORD_GENERATION_TIMEOUT = 120
KEYWORD_REASONING_EFFORT = "medium"
KEYWORD_SUGGESTION_LIMIT = 12


class KeywordGenerationError(RuntimeError):
    """Raised when Codex cannot return usable keyword suggestions."""


def _clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _keyword_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _keyword_values(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        keyword = re.sub(r"\s+", " ", str(value or "").strip())
        key = keyword.casefold()
        if not keyword or key in seen:
            continue
        seen.add(key)
        result.append(keyword)
    return result


def _error_summary(stderr: Any, fallback: str) -> str:
    text = str(stderr or "").strip()
    if not text:
        return fallback
    line = next((item.strip() for item in reversed(text.splitlines()) if item.strip()), "")
    return _clip(line, 300) or fallback


class CodexKeywordProvider:
    def __init__(
        self,
        binary: str = "codex",
        model: Optional[str] = None,
        prompt_version: str = KEYWORD_PROMPT_VERSION,
        work_dir: Optional[Path] = None,
        timeout: float = KEYWORD_GENERATION_TIMEOUT,
        reasoning_effort: str = KEYWORD_REASONING_EFFORT,
    ):
        self.binary = binary
        self.model = model
        self.prompt_version = prompt_version
        self.work_dir = Path(work_dir) if work_dir else None
        self.timeout = max(1.0, float(timeout))
        self.reasoning_effort = (
            reasoning_effort
            if reasoning_effort in ("low", "medium", "high")
            else KEYWORD_REASONING_EFFORT
        )
        self.schema_path = Path(__file__).with_name("keyword-generation-schema.json")

    def _args(self, output_root: Path, output: Path) -> List[str]:
        args = [
            self.binary,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--disable", "plugins",
            "--disable", "remote_plugin",
            "--disable", "apps",
            "--disable", "hooks",
            "--disable", "browser_use",
            "--disable", "computer_use",
            "--disable", "multi_agent",
            "--disable", "skill_search",
            "--skip-git-repo-check",
            "-C", str(output_root),
            "--sandbox", "read-only",
            "--color", "never",
            "-c", f'model_reasoning_effort="{self.reasoning_effort}"',
            "--output-schema", str(self.schema_path),
            "-o", str(output),
        ]
        if self.model:
            args.extend(["--model", self.model])
        return args

    def generate(
        self,
        project: Dict[str, Any],
        reference_keywords: Iterable[Any],
        existing_keywords: Iterable[Any],
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        name = _clip(project.get("name"), 200)
        if not name:
            raise ValueError("项目名称不能为空")
        description = _clip(project.get("description"), 2000)
        references = _keyword_values(reference_keywords)
        existing = _keyword_values(existing_keywords)
        prompt = (
            "你是小红书个人工作台的关键词助手。请根据项目名称、项目说明和用户明确选择的参考关键词，"
            f"生成最多 {KEYWORD_SUGGESTION_LIMIT} 个适合在小红书搜索的中文候选关键词。"
            "只提供候选词，不执行搜索，不读取或推断项目帖子、作者、报告等其他信息。"
            "关键词应覆盖核心主题、目标人群、使用场景、痛点需求和产品方案，避免空泛词、完整句子、"
            "同义重复以及已有关键词。每个候选都要给出简短分类和推荐理由。只输出符合 schema 的 JSON。\n"
            f"项目名称：{name}\n"
            f"项目说明：{description or '（未填写）'}\n"
            f"用户选择的参考关键词：{json.dumps(references, ensure_ascii=False)}\n"
            f"项目全部已有关键词（仅用于排除重复）：{json.dumps(existing, ensure_ascii=False)}"
        )
        output_root = self.work_dir or Path.cwd()
        output_root.mkdir(parents=True, exist_ok=True)
        output = output_root / (
            f"keywords-{datetime.now().strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex}.json"
        )
        try:
            result = run_codex_process(
                self._args(output_root, output),
                prompt,
                self.timeout,
                should_cancel=should_cancel,
            )
            if result.returncode:
                raise KeywordGenerationError(
                    _error_summary(result.stderr, "Codex 关键词生成失败")
                )
            try:
                value = json.loads(output.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise KeywordGenerationError("Codex 未返回有效的关键词 JSON") from exc
            if not isinstance(value, dict) or not isinstance(value.get("keywords"), list):
                raise KeywordGenerationError("Codex 关键词结果格式无效")

            seen = {_keyword_key(item) for item in existing if _keyword_key(item)}
            suggestions = []
            for item in value["keywords"]:
                if not isinstance(item, dict):
                    continue
                keyword = re.sub(r"\s+", " ", str(item.get("keyword") or "").strip())
                key = keyword.casefold()
                if not keyword or len(keyword) > 120 or key in seen:
                    continue
                category = _clip(item.get("category"), 50)
                reason = _clip(item.get("reason"), 200)
                if not category or not reason:
                    continue
                seen.add(key)
                suggestions.append({
                    "keyword": keyword,
                    "category": category,
                    "reason": reason,
                })
                if len(suggestions) >= KEYWORD_SUGGESTION_LIMIT:
                    break
            return {
                "keywords": suggestions,
                "model": self.model or "default",
                "prompt_version": self.prompt_version,
            }
        except subprocess.TimeoutExpired as exc:
            raise KeywordGenerationError(
                f"Codex 关键词生成超时（{int(self.timeout)} 秒）"
            ) from exc
        except OSError as exc:
            raise KeywordGenerationError("Codex 关键词生成进程无法启动") from exc
        finally:
            output.unlink(missing_ok=True)
