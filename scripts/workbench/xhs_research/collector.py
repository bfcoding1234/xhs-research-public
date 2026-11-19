from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional


SEARCH_POSTS_BY_KEYWORD = "search_posts_by_keyword"
SEARCH_USERS_BY_KEYWORD = "search_users_by_keyword"
READ_AUTHOR_PROFILE = "read_author_profile"
LIST_AUTHOR_POSTS = "list_author_posts"
READ_KEYWORD_POST_DETAILS = "read_keyword_post_details"
READ_AUTHOR_POST_DETAILS = "read_author_post_details"
READ_POST_DETAIL = "read_post_detail"
READ_POST_COMMENTS = "read_post_comments"
READ_POST_SUB_COMMENTS = "read_post_sub_comments"
OCR_MEDIA = "ocr_media"
DOWNLOAD_MEDIA = "download_media"


@dataclass(frozen=True)
class CapabilityDefinition:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class CollectorCommand:
    """一个采集器具体指令对业务原子能力的适配。"""

    id: str
    capability: str
    provider_id: str
    label: str
    instruction: str
    method: str


CAPABILITY_CATALOG = {
    SEARCH_POSTS_BY_KEYWORD: CapabilityDefinition(
        SEARCH_POSTS_BY_KEYWORD,
        "关键词搜索帖子",
        "根据业务关键词发现帖子卡片。",
    ),
    SEARCH_USERS_BY_KEYWORD: CapabilityDefinition(
        SEARCH_USERS_BY_KEYWORD,
        "关键词搜索用户",
        "根据业务关键词发现小红书用户。",
    ),
    READ_AUTHOR_PROFILE: CapabilityDefinition(
        READ_AUTHOR_PROFILE,
        "读取作者基础信息",
        "根据用户 ID 更新昵称、小红书号、简介、属地、互动统计和头像。",
    ),
    LIST_AUTHOR_POSTS: CapabilityDefinition(
        LIST_AUTHOR_POSTS,
        "读取用户主页帖子",
        "根据用户 ID 读取主页资料与帖子卡片。",
    ),
    READ_KEYWORD_POST_DETAILS: CapabilityDefinition(
        READ_KEYWORD_POST_DETAILS,
        "读取关键词帖子详情",
        "搜索关键词并补充帖子正文、互动和媒体详情。",
    ),
    READ_AUTHOR_POST_DETAILS: CapabilityDefinition(
        READ_AUTHOR_POST_DETAILS,
        "读取用户帖子详情",
        "读取用户主页帖子并补充正文、互动和媒体详情。",
    ),
    READ_POST_DETAIL: CapabilityDefinition(
        READ_POST_DETAIL,
        "读取指定帖子详情",
        "根据已保存的帖子 ID 或原文地址直接补充正文、互动和媒体详情。",
    ),
    READ_POST_COMMENTS: CapabilityDefinition(
        READ_POST_COMMENTS,
        "读取指定帖子评论",
        "按平台默认顺序分页读取指定帖子的一级评论与接口附带的回复预览。",
    ),
    READ_POST_SUB_COMMENTS: CapabilityDefinition(
        READ_POST_SUB_COMMENTS,
        "读取指定评论楼中楼",
        "按平台默认顺序分页读取一条一级评论的完整回复。",
    ),
    OCR_MEDIA: CapabilityDefinition(OCR_MEDIA, "图片 OCR", "识别帖子图片中的文字。"),
    DOWNLOAD_MEDIA: CapabilityDefinition(DOWNLOAD_MEDIA, "媒体下载", "下载帖子图片或视频。"),
}

CAPABILITY_LABELS = {
    capability_id: definition.label
    for capability_id, definition in CAPABILITY_CATALOG.items()
}


def command_id(provider_id: str, capability: str) -> str:
    return f"{provider_id}.{capability}"


DEFAULT_CAPABILITY_ROUTES = {
    SEARCH_USERS_BY_KEYWORD: ["xiaohongshu-cli"],
    READ_AUTHOR_PROFILE: ["xiaohongshu-cli", "socai"],
    SEARCH_POSTS_BY_KEYWORD: ["socai", "xiaohongshu-cli", "opencli"],
    LIST_AUTHOR_POSTS: ["socai", "xiaohongshu-cli", "opencli"],
    READ_KEYWORD_POST_DETAILS: ["socai", "xiaohongshu-cli", "opencli"],
    READ_AUTHOR_POST_DETAILS: ["socai", "xiaohongshu-cli", "opencli"],
    READ_POST_DETAIL: ["xiaohongshu-cli", "opencli"],
    READ_POST_COMMENTS: ["xiaohongshu-cli"],
    READ_POST_SUB_COMMENTS: ["xiaohongshu-cli"],
    DOWNLOAD_MEDIA: ["opencli"],
}

DEFAULT_CAPABILITY_COMMAND_ROUTES = {
    capability: [command_id(provider_id, capability) for provider_id in provider_ids]
    for capability, provider_ids in DEFAULT_CAPABILITY_ROUTES.items()
}


class CollectorError(RuntimeError):
    """统一表示采集 CLI 的可分类运行错误。"""

    def __init__(self, message: str, code: str = "collector_failed"):
        super().__init__(message)
        self.code = code


class CapabilityRegistry:
    """维护业务能力、采集指令与有序路由，不让任务绑定到单一采集器。"""

    LEGACY_METHODS = {
        SEARCH_POSTS_BY_KEYWORD: "keyword_preview",
        LIST_AUTHOR_POSTS: "author_preview",
        READ_KEYWORD_POST_DETAILS: "keyword_deep",
        READ_AUTHOR_POST_DETAILS: "author_deep",
    }

    def __init__(self, providers: Dict[str, object], routes=None):
        self.providers = dict(providers)
        self.commands = self._discover_commands()
        self.default_routes = self._resolve_routes(DEFAULT_CAPABILITY_COMMAND_ROUTES)
        self.routes = self._resolve_routes(routes or self.default_routes)

    @classmethod
    def provider_capabilities(cls, provider: object) -> set:
        declared = set(getattr(provider, "capabilities", ()) or ())
        for spec in getattr(provider, "command_specs", ()) or ():
            if isinstance(spec, Mapping) and spec.get("capability"):
                declared.add(str(spec["capability"]))
        for capability, method_name in cls.LEGACY_METHODS.items():
            if callable(getattr(provider, method_name, None)):
                declared.add(capability)
        return declared

    def _discover_commands(self) -> Dict[str, CollectorCommand]:
        values: Dict[str, CollectorCommand] = {}
        for configured_id, provider in self.providers.items():
            provider_id = str(getattr(provider, "provider_id", configured_id) or configured_id)
            described_capabilities = set()
            for raw in getattr(provider, "command_specs", ()) or ():
                if not isinstance(raw, Mapping):
                    continue
                capability = str(raw.get("capability") or "").strip()
                method = str(raw.get("method") or capability).strip()
                if not capability or not callable(getattr(provider, method, None)):
                    continue
                item = CollectorCommand(
                    id=str(raw.get("id") or command_id(provider_id, capability)),
                    capability=capability,
                    provider_id=provider_id,
                    label=str(raw.get("label") or CAPABILITY_LABELS.get(capability, capability)),
                    instruction=str(raw.get("instruction") or method),
                    method=method,
                )
                values[item.id] = item
                described_capabilities.add(capability)
            for capability in self.provider_capabilities(provider) - described_capabilities:
                method = capability
                if not callable(getattr(provider, method, None)):
                    method = self.LEGACY_METHODS.get(capability, capability)
                if not callable(getattr(provider, method, None)):
                    continue
                item = CollectorCommand(
                    id=command_id(provider_id, capability),
                    capability=capability,
                    provider_id=provider_id,
                    label=f"{getattr(provider, 'display_name', provider_id)} · {CAPABILITY_LABELS.get(capability, capability)}",
                    instruction=method,
                    method=method,
                )
                values[item.id] = item
        return values

    def _resolve_token(self, capability: str, token: str) -> Optional[str]:
        token = str(token or "").strip()
        command = self.commands.get(token)
        if command and command.capability == capability:
            return token
        provider_matches = [
            value.id for value in self.commands.values()
            if value.capability == capability and value.provider_id == token
        ]
        return provider_matches[0] if provider_matches else None

    def _resolve_routes(self, routes) -> Dict[str, List[str]]:
        routes = routes if isinstance(routes, Mapping) else {}
        values: Dict[str, List[str]] = {}
        for capability in CAPABILITY_CATALOG:
            raw_tokens = routes.get(capability, self.default_routes.get(capability, []) if hasattr(self, "default_routes") else [])
            if not isinstance(raw_tokens, list):
                raw_tokens = []
            resolved = []
            for token in raw_tokens:
                command = self._resolve_token(capability, token)
                if command and command not in resolved:
                    resolved.append(command)
            if resolved:
                values[capability] = resolved
        return values

    def validate_routes(self, routes) -> Dict[str, List[str]]:
        if not isinstance(routes, Mapping):
            raise ValueError("capability_routes must be an object")
        unknown = set(routes) - set(CAPABILITY_CATALOG)
        if unknown:
            raise ValueError(f"unknown capability: {sorted(unknown)[0]}")
        values = dict(self.default_routes)
        for capability, raw_commands in routes.items():
            if not isinstance(raw_commands, list) or not raw_commands:
                raise ValueError(f"{capability} must contain at least one command")
            resolved = []
            for raw_command in raw_commands:
                command = str(raw_command or "").strip()
                item = self.commands.get(command)
                if item is None:
                    raise ValueError(f"unknown collector command: {command}")
                if item.capability != capability:
                    raise ValueError(f"collector command {command} does not support {capability}")
                if command in resolved:
                    raise ValueError(f"duplicate collector command: {command}")
                resolved.append(command)
            values[capability] = resolved
        return values

    def command_candidates(self, capability: str):
        values = []
        for command_id_value in self.routes.get(capability, []):
            command = self.commands.get(command_id_value)
            provider = self.providers.get(command.provider_id) if command else None
            method = getattr(provider, command.method, None) if provider and command else None
            if command and provider is not None and callable(method):
                values.append((command, provider, method))
        return values

    def candidates(self, capability: str):
        """兼容旧调用方：返回按指令路由去重后的提供方。"""
        values = []
        seen = set()
        for command, provider, _method in self.command_candidates(capability):
            if command.provider_id not in seen:
                values.append((command.provider_id, provider))
                seen.add(command.provider_id)
        return values

    def describe_commands(self) -> List[dict]:
        return [
            {
                "id": item.id,
                "capability": item.capability,
                "provider_id": item.provider_id,
                "label": item.label,
                "instruction": item.instruction,
            }
            for item in self.commands.values()
        ]

    def describe_routes(self) -> List[dict]:
        values = []
        for capability, definition in CAPABILITY_CATALOG.items():
            commands = list(self.routes.get(capability, []))
            defaults = list(self.default_routes.get(capability, []))
            values.append({
                "capability": capability,
                "label": definition.label,
                "description": definition.description,
                "commands": commands,
                "default_commands": defaults,
                # 兼容旧前端和外部读取方。
                "providers": [self.commands[value].provider_id for value in commands if value in self.commands],
            })
        return values
