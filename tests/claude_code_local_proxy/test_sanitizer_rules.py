"""Tests for individual sanitizer rules."""

from claude_code_local_proxy.sanitizer_rules.date_marker import DateMarkerRule, apostrophe_label


def test_date_marker_rule_exposes_name() -> None:
    assert DateMarkerRule().name == "date_marker"


def test_apostrophe_label_returns_unicode_codepoint() -> None:
    assert apostrophe_label("ʹ") == "U+02B9"
    assert apostrophe_label("x") == "U+0078"
