"""Rule for normalizing Claude Code's `Today's date is ...` marker line."""

from __future__ import annotations

import re

from claude_code_local_proxy.sanitizer_rules.base import Mode, SanitizeStats

_MARKER_RE = re.compile(
    r"Today(?P<apostrophe>['\u2019\u02bc\u02b9])s date is "
    r"(?P<year>\d{4})(?P<sep1>[-/])(?P<month>\d{2})(?P<sep2>[-/])(?P<day>\d{2})"
)
_APOSTROPHE_LABELS = {
    "'": "U+0027",
    "\u2019": "U+2019",
    "\u02bc": "U+02BC",
    "\u02b9": "U+02B9",
}


class DateMarkerRule:
    """Normalize known Claude Code date-line marker bits in a string."""

    name = "date_marker"

    def apply(self, text: str, mode: Mode) -> tuple[str, SanitizeStats]:
        """Apply the date-marker rule to one string.

        Only the narrow pattern ``Today['’ʼʹ]s date is YYYY[-/]MM[-/]DD`` is touched.
        The date value is preserved; apostrophe variants become U+0027 and slash
        separators become hyphens when ``mode`` is ``normalize``.
        """

        stats = SanitizeStats()
        changed = False

        def replace(match: re.Match[str]) -> str:
            nonlocal stats, changed
            apostrophe = match.group("apostrophe")
            sep1 = match.group("sep1")
            sep2 = match.group("sep2")
            has_apostrophe_variant = apostrophe != "'"
            has_slash_date = sep1 == "/" or sep2 == "/"
            would_change = has_apostrophe_variant or has_slash_date
            stats += SanitizeStats(
                date_lines=1,
                apostrophe_variants=1 if has_apostrophe_variant else 0,
                slash_dates=1 if has_slash_date else 0,
                replacements=1 if mode == "normalize" and would_change else 0,
            )
            if mode != "normalize" or not would_change:
                return match.group(0)
            changed = True
            return (
                f"Today's date is {match.group('year')}-{match.group('month')}-{match.group('day')}"
            )

        sanitized = _MARKER_RE.sub(replace, text)
        if not changed:
            return text, stats
        return sanitized, stats


def apostrophe_label(char: str) -> str:
    """Return a Unicode label for known apostrophe marker characters."""

    return _APOSTROPHE_LABELS.get(char, f"U+{ord(char):04X}")
