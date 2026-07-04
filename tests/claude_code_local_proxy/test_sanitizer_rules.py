"""Tests for individual sanitizer rules."""

from claude_code_local_proxy.sanitizer_rules.date_marker import DateMarkerRule, apostrophe_label
from claude_code_local_proxy.sanitizer_rules.timezone_marker import TimezoneMarkerRule


def test_date_marker_rule_exposes_name() -> None:
    assert DateMarkerRule().name == "date_marker"


def test_timezone_marker_rule_exposes_name() -> None:
    assert TimezoneMarkerRule("America/Los_Angeles").name == "timezone_marker"


def test_apostrophe_label_returns_unicode_codepoint() -> None:
    assert apostrophe_label("ʹ") == "U+02B9"
    assert apostrophe_label("x") == "U+0078"
