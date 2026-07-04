"""Rule for normalizing Claude Code timezone marker text."""

from __future__ import annotations

import re

from claude_code_local_proxy.sanitizer_rules.base import Mode, SanitizeStats

_XML_TIMEZONE_RE = re.compile(
    r"(?P<open><timezone>)(?P<value>[^<\r\n]+)(?P<close></timezone>)",
    re.IGNORECASE,
)
_LINE_TIMEZONE_RE = re.compile(
    r"(?m)^(?P<prefix>[ \t]*(?:time[ -]?zone|timezone)[ \t]*:[ \t]*)"
    r"(?P<value>[^\r\n]+)$",
    re.IGNORECASE,
)


class TimezoneMarkerRule:
    """Normalize known timezone marker formats to a configured timezone."""

    name = "timezone_marker"

    def __init__(self, target_timezone: str) -> None:
        self.target_timezone = target_timezone

    def apply(self, text: str, mode: Mode) -> tuple[str, SanitizeStats]:
        """Apply the timezone-marker rule to one string.

        Only XML-style ``<timezone>...</timezone>`` markers and whole-line
        ``Timezone: ...`` markers are touched.
        """

        current, xml_stats, xml_changed = self._replace_xml_marker(text, mode)
        sanitized, line_stats, line_changed = self._replace_line_marker(current, mode)
        stats = xml_stats + line_stats
        if not xml_changed and not line_changed:
            return text, stats
        return sanitized, stats

    def _replace_xml_marker(self, text: str, mode: Mode) -> tuple[str, SanitizeStats, bool]:
        stats = SanitizeStats()
        changed = False

        def replace(match: re.Match[str]) -> str:
            nonlocal stats, changed
            value = match.group("value").strip()
            would_change = value != self.target_timezone
            stats += SanitizeStats(
                timezone_markers=1,
                replacements=1 if mode == "normalize" and would_change else 0,
            )
            if mode != "normalize" or not would_change:
                return match.group(0)
            changed = True
            return f"{match.group('open')}{self.target_timezone}{match.group('close')}"

        return _XML_TIMEZONE_RE.sub(replace, text), stats, changed

    def _replace_line_marker(self, text: str, mode: Mode) -> tuple[str, SanitizeStats, bool]:
        stats = SanitizeStats()
        changed = False

        def replace(match: re.Match[str]) -> str:
            nonlocal stats, changed
            value = match.group("value").strip()
            would_change = value != self.target_timezone
            stats += SanitizeStats(
                timezone_markers=1,
                replacements=1 if mode == "normalize" and would_change else 0,
            )
            if mode != "normalize" or not would_change:
                return match.group(0)
            changed = True
            return f"{match.group('prefix')}{self.target_timezone}"

        return _LINE_TIMEZONE_RE.sub(replace, text), stats, changed
