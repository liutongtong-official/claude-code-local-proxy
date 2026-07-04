"""Tests for Claude Code marker sanitizing."""

from claude_code_local_proxy.sanitizer import (
    BASE_URL_RULE,
    DATE_MARKER_RULE,
    TIMEZONE_MARKER_RULE,
    Mode,
    SanitizeStats,
    default_rules,
    sanitize_json_value,
    sanitize_text,
)
from claude_code_local_proxy.sanitizer_rules.timezone_marker import TimezoneMarkerRule


def test_sanitize_text_normalizes_apostrophe_variant_and_slash_date() -> None:
    text = "Todayʹs date is 2026/06/30."

    sanitized, stats = sanitize_text(text, rules=default_rules((DATE_MARKER_RULE,)))

    assert sanitized == "Today's date is 2026-06-30."
    assert stats.date_lines == 1
    assert stats.apostrophe_variants == 1
    assert stats.slash_dates == 1
    assert stats.replacements == 1


def test_sanitize_text_preserves_plain_date_line() -> None:
    text = "Today's date is 2026-06-30."

    sanitized, stats = sanitize_text(text, rules=default_rules((DATE_MARKER_RULE,)))

    assert sanitized == text
    assert stats.date_lines == 1
    assert stats.apostrophe_variants == 0
    assert stats.slash_dates == 0
    assert stats.replacements == 0


def test_observe_mode_reports_without_changing_text() -> None:
    text = "Todayʼs date is 2026/06/30."

    sanitized, stats = sanitize_text(text, mode="observe", rules=default_rules((DATE_MARKER_RULE,)))

    assert sanitized == text
    assert stats.date_lines == 1
    assert stats.apostrophe_variants == 1
    assert stats.slash_dates == 1
    assert stats.replacements == 0


def test_timezone_rule_normalizes_xml_marker() -> None:
    text = "<env><timezone>Asia/Shanghai</timezone></env>"

    sanitized, stats = sanitize_text(text, rules=(TimezoneMarkerRule("America/Los_Angeles"),))

    assert sanitized == "<env><timezone>America/Los_Angeles</timezone></env>"
    assert stats.timezone_markers == 1
    assert stats.replacements == 1


def test_timezone_rule_normalizes_xml_marker_whitespace() -> None:
    text = "<env><timezone> America/Los_Angeles </timezone></env>"

    sanitized, stats = sanitize_text(text, rules=(TimezoneMarkerRule("America/Los_Angeles"),))

    assert sanitized == "<env><timezone>America/Los_Angeles</timezone></env>"
    assert stats.timezone_markers == 1
    assert stats.replacements == 1


def test_timezone_rule_normalizes_whole_line_marker() -> None:
    text = "Current context:\nTimezone: Asia/Shanghai\nOther text."

    sanitized, stats = sanitize_text(text, rules=(TimezoneMarkerRule("America/Los_Angeles"),))

    assert sanitized == "Current context:\nTimezone: America/Los_Angeles\nOther text."
    assert stats.timezone_markers == 1
    assert stats.replacements == 1


def test_timezone_rule_normalizes_whole_line_marker_whitespace() -> None:
    text = "Current context:\nTimezone: America/Los_Angeles \nOther text."

    sanitized, stats = sanitize_text(text, rules=(TimezoneMarkerRule("America/Los_Angeles"),))

    assert sanitized == "Current context:\nTimezone: America/Los_Angeles\nOther text."
    assert stats.timezone_markers == 1
    assert stats.replacements == 1


def test_timezone_rule_does_not_touch_inline_unrelated_text() -> None:
    text = "The timezone: Asia/Shanghai example should stay."

    sanitized, stats = sanitize_text(text, rules=(TimezoneMarkerRule("America/Los_Angeles"),))

    assert sanitized == text
    assert stats.timezone_markers == 0
    assert stats.replacements == 0


def test_base_url_rule_replaces_local_proxy_urls() -> None:
    text = "Base URL: http://127.0.0.1:8787/v1/messages"

    sanitized, stats = sanitize_text(
        text,
        rules=default_rules(
            (BASE_URL_RULE,),
            public_base_url="https://api.anthropic.com",
            local_base_urls=("http://127.0.0.1:8787", "http://localhost:8787"),
        ),
    )

    assert sanitized == "Base URL: https://api.anthropic.com/v1/messages"
    assert stats.base_urls == 1
    assert stats.replacements == 1


def test_base_url_rule_observe_mode_reports_without_changing_text() -> None:
    text = "Base URL: http://localhost:8787/v1/messages"

    sanitized, stats = sanitize_text(
        text,
        mode="observe",
        rules=default_rules(
            (BASE_URL_RULE,),
            public_base_url="https://api.anthropic.com",
            local_base_urls=("http://127.0.0.1:8787", "http://localhost:8787"),
        ),
    )

    assert sanitized == text
    assert stats.base_urls == 1
    assert stats.replacements == 0


def test_base_url_rule_does_not_replace_port_prefix() -> None:
    text = "Other service: http://127.0.0.1:87870/v1/messages"

    sanitized, stats = sanitize_text(
        text,
        rules=default_rules(
            (BASE_URL_RULE,),
            public_base_url="https://api.anthropic.com",
            local_base_urls=("http://127.0.0.1:8787",),
        ),
    )

    assert sanitized == text
    assert stats.base_urls == 0
    assert stats.replacements == 0


def test_base_url_rule_replaces_before_sentence_punctuation() -> None:
    text = "Base URL: http://127.0.0.1:8787."

    sanitized, stats = sanitize_text(
        text,
        rules=default_rules(
            (BASE_URL_RULE,),
            public_base_url="https://api.anthropic.com",
            local_base_urls=("http://127.0.0.1:8787",),
        ),
    )

    assert sanitized == "Base URL: https://api.anthropic.com."
    assert stats.base_urls == 1
    assert stats.replacements == 1


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

    sanitized, stats = sanitize_json_value(payload, rules=default_rules((DATE_MARKER_RULE,)))

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


def test_sanitize_json_value_uses_configured_timezone_rule() -> None:
    payload = {
        "system": [
            {
                "type": "text",
                "text": "Today's date is 2026-06-30.\n<timezone>Asia/Shanghai</timezone>",
            }
        ],
    }

    sanitized, stats = sanitize_json_value(
        payload,
        rules=default_rules((DATE_MARKER_RULE, TIMEZONE_MARKER_RULE), "America/Los_Angeles"),
    )

    assert sanitized == {
        "system": [
            {
                "type": "text",
                "text": "Today's date is 2026-06-30.\n<timezone>America/Los_Angeles</timezone>",
            }
        ],
    }
    assert stats.date_lines == 1
    assert stats.timezone_markers == 1
    assert stats.replacements == 1


def test_sanitize_json_value_uses_configured_base_url_rule() -> None:
    payload = {
        "system": [
            {
                "type": "text",
                "text": "API base: http://127.0.0.1:8787",
            }
        ],
    }

    sanitized, stats = sanitize_json_value(
        payload,
        rules=default_rules(
            (BASE_URL_RULE,),
            public_base_url="https://api.anthropic.com",
            local_base_urls=("http://127.0.0.1:8787", "http://localhost:8787"),
        ),
    )

    assert sanitized == {
        "system": [
            {
                "type": "text",
                "text": "API base: https://api.anthropic.com",
            }
        ],
    }
    assert stats.base_urls == 1
    assert stats.replacements == 1


def test_default_rules_caches_configured_timezone_rules() -> None:
    first_rules = default_rules((TIMEZONE_MARKER_RULE,), "America/Los_Angeles")
    second_rules = default_rules((TIMEZONE_MARKER_RULE,), "America/Los_Angeles")

    assert first_rules is second_rules


def test_default_rules_caches_configured_base_url_rules() -> None:
    first_rules = default_rules(
        (BASE_URL_RULE,),
        public_base_url="https://api.anthropic.com",
        local_base_urls=("http://127.0.0.1:8787",),
    )
    second_rules = default_rules(
        (BASE_URL_RULE,),
        public_base_url="https://api.anthropic.com",
        local_base_urls=("http://127.0.0.1:8787",),
    )

    assert first_rules is second_rules


def test_default_rules_are_empty_without_explicit_rule_names() -> None:
    assert default_rules() == ()


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
