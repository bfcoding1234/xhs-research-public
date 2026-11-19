#!/usr/bin/env python3
"""校验项目核心文档中的本地 Markdown 链接与根规则预算。"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    PROJECT_ROOT / "AGENTS.md",
    PROJECT_ROOT / "SKILL.md",
    PROJECT_ROOT / "docs" / "README.md",
    PROJECT_ROOT / "docs" / "ARCHITECTURE.md",
    PROJECT_ROOT / "docs" / "CODEMAP.md",
    PROJECT_ROOT / "docs" / "PRODUCT_RULES.md",
    PROJECT_ROOT / "docs" / "ENGINEERING_GUARDRAILS.md",
    PROJECT_ROOT / "docs" / "TESTING.md",
    PROJECT_ROOT / "docs" / "page-specs" / "list-page.md",
    PROJECT_ROOT / "docs" / "details" / "README.md",
    PROJECT_ROOT / "docs" / "details" / "pages.md",
    PROJECT_ROOT / "docs" / "details" / "api.md",
    PROJECT_ROOT / "docs" / "details" / "services.md",
    PROJECT_ROOT / "docs" / "details" / "dependencies.md",
    PROJECT_ROOT / "docs" / "details" / "xiaohongshu-cli-capability-report.md",
    PROJECT_ROOT / "docs" / "details" / "data-model.md",
    PROJECT_ROOT / "docs" / "details" / "configuration.md",
    PROJECT_ROOT / "docs" / "page-specs" / "README.md",
    PROJECT_ROOT / "docs" / "plans" / "README.md",
    PROJECT_ROOT / "docs" / "history" / "README.md",
    PROJECT_ROOT / "docs" / "待删除" / "README.md",
    PROJECT_ROOT / "scripts" / "workbench" / "README.md",
    PROJECT_ROOT / "outputs" / "xhs-architecture-doc" / "README.md",
)
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
ROOT_RULES_MAX_BYTES = 16 * 1024
PENDING_DELETE_DIR = PROJECT_ROOT / "docs" / "待删除"
PENDING_DELETE_INDEX = PENDING_DELETE_DIR / "README.md"
ROOT_RULES_FORBIDDEN_MARKERS = (
    "BEGIN CODEX LEARNED RULES",
    "## 从代码调整中沉淀的规律",
)


def local_targets(document: Path):
    content = document.read_text(encoding="utf-8")
    for raw_target in LINK_PATTERN.findall(content):
        target = unquote(raw_target.strip())
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue
        yield raw_target, (document.parent / path_part).resolve()


def main() -> int:
    missing = []
    retired_dependencies = []
    checked = 0

    for document in DOCUMENTS:
        if not document.is_file():
            missing.append((document, "<document>", document))
            continue
        for raw_target, target in local_targets(document):
            checked += 1
            if not target.exists():
                missing.append((document, raw_target, target))
            elif target.is_relative_to(PENDING_DELETE_DIR) and target != PENDING_DELETE_INDEX:
                retired_dependencies.append((document, raw_target, target))

    if missing:
        print("项目规范文档存在失效的本地链接：", file=sys.stderr)
        for document, raw_target, target in missing:
            print(
                f"- {document.relative_to(PROJECT_ROOT)}: {raw_target} -> "
                f"{target.relative_to(PROJECT_ROOT) if target.is_relative_to(PROJECT_ROOT) else target}",
                file=sys.stderr,
            )
        return 1

    if retired_dependencies:
        print("当前文档不得依赖待删除正文：", file=sys.stderr)
        for document, raw_target, target in retired_dependencies:
            print(
                f"- {document.relative_to(PROJECT_ROOT)}: {raw_target} -> "
                f"{target.relative_to(PROJECT_ROOT)}",
                file=sys.stderr,
            )
        return 1

    root_rules = PROJECT_ROOT / "AGENTS.md"
    root_rules_content = root_rules.read_text(encoding="utf-8")
    root_rules_bytes = len(root_rules_content.encode("utf-8"))
    if root_rules_bytes > ROOT_RULES_MAX_BYTES:
        print(
            "根 AGENTS.md 超过常驻规则预算："
            f"{root_rules_bytes} > {ROOT_RULES_MAX_BYTES} 字节。"
            "请把领域规则迁移到按需读取的规范文档。",
            file=sys.stderr,
        )
        return 1
    for marker in ROOT_RULES_FORBIDDEN_MARKERS:
        if marker in root_rules_content:
            print(
                f"根 AGENTS.md 不得恢复追加式历史规则区块：{marker}",
                file=sys.stderr,
            )
            return 1

    print(
        f"项目规范文档检查通过：{checked} 个本地目标；"
        f"根 AGENTS.md {root_rules_bytes} / {ROOT_RULES_MAX_BYTES} 字节。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
