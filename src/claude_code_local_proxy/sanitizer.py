"""Sanitizer pipeline for Claude Code request payloads."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from claude_code_local_proxy.sanitizer_rules.base import Mode, SanitizerRule, SanitizeStats
from claude_code_local_proxy.sanitizer_rules.base_url import BaseUrlRule
from claude_code_local_proxy.sanitizer_rules.date_marker import DateMarkerRule, apostrophe_label
from claude_code_local_proxy.sanitizer_rules.timezone_marker import TimezoneMarkerRule

BASE_URL_RULE = "base-url"
DATE_MARKER_RULE = "date-marker"
TIMEZONE_MARKER_RULE = "timezone-marker"
SUPPORTED_RULE_NAMES = (DATE_MARKER_RULE, TIMEZONE_MARKER_RULE, BASE_URL_RULE)
DEFAULT_RULES: tuple[SanitizerRule, ...] = ()


@lru_cache(maxsize=16)
def default_rules(
    enabled_rule_names: tuple[str, ...] = (),
    target_timezone: str | None = None,
    public_base_url: str | None = None,
    local_base_urls: tuple[str, ...] = (),
) -> tuple[SanitizerRule, ...]:
    """Return built-in sanitizer rules for the current runtime configuration."""

    rules: list[SanitizerRule] = []
    for name in enabled_rule_names:
        if name == DATE_MARKER_RULE:
            rules.append(DateMarkerRule())
        elif name == TIMEZONE_MARKER_RULE:
            if target_timezone is None:
                raise ValueError("timezone-marker requires target_timezone")
            rules.append(TimezoneMarkerRule(target_timezone))
        elif name == BASE_URL_RULE:
            if public_base_url is None:
                raise ValueError("base-url requires public_base_url")
            if not local_base_urls:
                raise ValueError("base-url requires local_base_urls")
            rules.append(BaseUrlRule(local_base_urls, public_base_url))
        else:
            raise ValueError(f"unknown sanitizer rule {name!r}")
    return tuple(rules)


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
    "BASE_URL_RULE",
    "BaseUrlRule",
    "DATE_MARKER_RULE",
    "DateMarkerRule",
    "Mode",
    "SanitizeStats",
    "SanitizerRule",
    "SUPPORTED_RULE_NAMES",
    "TIMEZONE_MARKER_RULE",
    "TimezoneMarkerRule",
    "apostrophe_label",
    "default_rules",
    "sanitize_json_value",
    "sanitize_text",
]
