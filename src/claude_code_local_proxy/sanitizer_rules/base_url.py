"""Rule for normalizing local proxy base URLs before forwarding."""

from __future__ import annotations

import re

from claude_code_local_proxy.sanitizer_rules.base import Mode, SanitizeStats


class BaseUrlRule:
    """Replace configured local proxy base URLs with a public upstream base URL."""

    name = "base_url"

    def __init__(self, local_base_urls: tuple[str, ...], public_base_url: str) -> None:
        normalized_public = _normalize_base_url(public_base_url)
        if not normalized_public:
            raise ValueError("public_base_url must not be empty")
        self.public_base_url = normalized_public

        self.local_base_urls = tuple(
            sorted(
                {url for url in (_normalize_base_url(url) for url in local_base_urls) if url},
                key=len,
                reverse=True,
            )
        )
        if not self.local_base_urls:
            raise ValueError("local_base_urls must contain at least one non-empty URL")
        self._patterns = tuple(_base_url_pattern(url) for url in self.local_base_urls)

    def apply(self, text: str, mode: Mode) -> tuple[str, SanitizeStats]:
        """Apply the base-url rule to one string."""

        current = text
        base_urls = 0
        replacements = 0
        changed = False
        for local_base_url, pattern in zip(self.local_base_urls, self._patterns, strict=True):
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
