"""Sanitizer pipeline for Claude Code request payloads."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from claude_code_local_proxy.sanitizer_rules.base import Mode, SanitizerRule, SanitizeStats
from claude_code_local_proxy.sanitizer_rules.date_marker import DateMarkerRule, apostrophe_label

DEFAULT_RULES: tuple[SanitizerRule, ...] = (DateMarkerRule(),)


def sanitize_text(
    text: str,
    mode: Mode = "normalize",
    rules: Sequence[SanitizerRule] = DEFAULT_RULES,
) -> tuple[str, SanitizeStats]:
    """Apply sanitizer rules to a string in order."""

    current = text
    total = SanitizeStats()
    for rule in rules:
        current, stats = rule.apply(current, mode)
        total += stats
    return current, total


def sanitize_json_value(
    value: Any,
    mode: Mode = "normalize",
    rules: Sequence[SanitizerRule] = DEFAULT_RULES,
) -> tuple[Any, SanitizeStats]:
    """Recursively sanitize all string leaves in a decoded JSON value."""

    if mode == "off":
        return value, SanitizeStats()
    if isinstance(value, str):
        return sanitize_text(value, mode, rules)
    if isinstance(value, list):
        total = SanitizeStats()
        changed = False
        items: list[Any] = []
        for item in value:
            sanitized, stats = sanitize_json_value(item, mode, rules)
            items.append(sanitized)
            total += stats
            changed = changed or sanitized is not item
        return (items if changed else value), total
    if isinstance(value, dict):
        total = SanitizeStats()
        changed = False
        sanitized_dict: dict[Any, Any] = {}
        for key, item in value.items():
            sanitized, stats = sanitize_json_value(item, mode, rules)
            sanitized_dict[key] = sanitized
            total += stats
            changed = changed or sanitized is not item
        return (sanitized_dict if changed else value), total
    return value, SanitizeStats()


__all__ = [
    "DEFAULT_RULES",
    "DateMarkerRule",
    "Mode",
    "SanitizeStats",
    "SanitizerRule",
    "apostrophe_label",
    "sanitize_json_value",
    "sanitize_text",
]
