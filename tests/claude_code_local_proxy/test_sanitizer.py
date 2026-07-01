"""Tests for Claude Code marker sanitizing."""

from claude_code_local_proxy.sanitizer import (
    Mode,
    SanitizeStats,
    sanitize_json_value,
    sanitize_text,
)


def test_sanitize_text_normalizes_apostrophe_variant_and_slash_date() -> None:
    text = "Todayʹs date is 2026/06/30."

    sanitized, stats = sanitize_text(text)

    assert sanitized == "Today's date is 2026-06-30."
    assert stats.date_lines == 1
    assert stats.apostrophe_variants == 1
    assert stats.slash_dates == 1
    assert stats.replacements == 1


def test_sanitize_text_preserves_plain_date_line() -> None:
    text = "Today's date is 2026-06-30."

    sanitized, stats = sanitize_text(text)

    assert sanitized == text
    assert stats.date_lines == 1
    assert stats.apostrophe_variants == 0
    assert stats.slash_dates == 0
    assert stats.replacements == 0


def test_observe_mode_reports_without_changing_text() -> None:
    text = "Todayʼs date is 2026/06/30."

    sanitized, stats = sanitize_text(text, mode="observe")

    assert sanitized == text
    assert stats.date_lines == 1
    assert stats.apostrophe_variants == 1
    assert stats.slash_dates == 1
    assert stats.replacements == 0


def test_sanitize_json_value_recurses_over_nested_strings() -> None:
    payload = {
        "system": [
            {
                "type": "text",
                "text": "Today’s date is 2026/06/30.\nOther text remains.",
            }
        ],
        "metadata": {"user_id": "abc"},
    }

    sanitized, stats = sanitize_json_value(payload)

    assert sanitized == {
        "system": [
            {
                "type": "text",
                "text": "Today's date is 2026-06-30.\nOther text remains.",
            }
        ],
        "metadata": {"user_id": "abc"},
    }
    assert stats.date_lines == 1
    assert stats.apostrophe_variants == 1
    assert stats.slash_dates == 1
    assert stats.replacements == 1


def test_sanitize_json_value_does_not_touch_unrelated_dates() -> None:
    payload = {"message": "The date 2026/06/30 should stay as-is."}

    sanitized, stats = sanitize_json_value(payload)

    assert sanitized == payload
    assert stats.date_lines == 0
    assert stats.replacements == 0


def test_sanitize_text_accepts_custom_rules() -> None:
    class ReplaceRule:
        name = "replace_rule"

        def apply(self, text: str, mode: Mode) -> tuple[str, SanitizeStats]:
            if mode != "normalize":
                return text, SanitizeStats()
            return text.replace("alpha", "beta"), SanitizeStats(replacements=1)

    sanitized, stats = sanitize_text("alpha", rules=(ReplaceRule(),))

    assert sanitized == "beta"
    assert stats.replacements == 1
