"""Rule for normalizing local proxy base URLs before forwarding."""

from __future__ import annotations

import re

from claude_code_local_proxy.sanitizer_rules.base import Mode, SanitizeStats


class BaseUrlRule:
    """Replace configured local proxy base URLs with a public upstream base URL."""

    name = "base_url"

    def __init__(self, local_base_urls: tuple[str, ...], public_base_url: str) -> None:
        self.local_base_urls = tuple(
            sorted({_normalize_base_url(url) for url in local_base_urls}, key=len, reverse=True)
        )
        self.public_base_url = _normalize_base_url(public_base_url)

    def apply(self, text: str, mode: Mode) -> tuple[str, SanitizeStats]:
        """Apply the base-url rule to one string."""

        current = text
        base_urls = 0
        replacements = 0
        changed = False
        for local_base_url in self.local_base_urls:
            pattern = _base_url_pattern(local_base_url)
            matches = tuple(pattern.finditer(current))
            count = len(matches)
            if count == 0:
                continue
            base_urls += count
            if mode != "normalize" or local_base_url == self.public_base_url:
                continue
            current = pattern.sub(self.public_base_url, current)
            replacements += count
            changed = True
        stats = SanitizeStats(base_urls=base_urls, replacements=replacements)
        if not changed:
            return text, stats
        return current, stats


def _normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def _base_url_pattern(local_base_url: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(local_base_url)}(?=$|[/#?\s<>'\")\]}}.,;:!])")
