from __future__ import annotations

from .external_content import ExternalContentSource, wrap_external_content


def fence_project_context(content: str) -> str:
    return wrap_external_content(content, ExternalContentSource.FILE)


def fence_skill_context(content: str) -> str:
    return wrap_external_content(content, ExternalContentSource.FILE)


def fence_chat_history(content: str) -> str:
    return wrap_external_content(content, ExternalContentSource.CHANNEL_METADATA)


def fence_tool_observations(content: str) -> str:
    return wrap_external_content(content, ExternalContentSource.API)


__all__ = [
    "fence_chat_history",
    "fence_project_context",
    "fence_skill_context",
    "fence_tool_observations",
]
