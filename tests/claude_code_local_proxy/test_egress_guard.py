"""Tests for outbound egress location checks."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

import pytest

from claude_code_local_proxy.egress_guard import (
    EgressGuard,
    EgressGuardBlocked,
    EgressGuardConfig,
    EgressGuardUnavailable,
    parse_country_codes,
)


class FakeResponse:
    def __init__(self, payload: dict[str, Any] | str) -> None:
        if isinstance(payload, str):
            self._body = payload.encode()
        else:
            self._body = json.dumps(payload).encode()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body[:size]


def test_parse_country_codes_accepts_comma_separated_values() -> None:
    assert parse_country_codes("cn, hk,mo,TW") == frozenset({"CN", "HK", "MO", "TW"})


def test_parse_country_codes_rejects_invalid_codes() -> None:
    with pytest.raises(ValueError, match="comma-separated ISO 3166-1"):
        parse_country_codes("CN CHN")


def test_egress_guard_blocks_blocked_country_code() -> None:
    guard = EgressGuard(
        EgressGuardConfig(blocked_country_codes=frozenset({"CN"})),
        urlopen=_urlopen_sequence(
            "203.0.113.10", {"ip": "203.0.113.10", "country_code": "CN", "country": "China"}
        ),
    )

    with pytest.raises(EgressGuardBlocked) as exc_info:
        guard.ensure_allowed()

    assert exc_info.value.location.country_code == "CN"
    assert exc_info.value.location.ip == "203.0.113.10"


def test_egress_guard_allows_non_blocked_country_code() -> None:
    guard = EgressGuard(
        EgressGuardConfig(blocked_country_codes=frozenset({"CN", "HK", "MO", "TW"})),
        urlopen=_urlopen_sequence(
            "198.51.100.10",
            {"ip": "198.51.100.10", "country_code": "US", "country": "United States"},
        ),
    )

    location = guard.ensure_allowed()

    assert location is not None
    assert location.country_code == "US"


def test_egress_guard_tries_next_provider_when_response_is_unusable() -> None:
    guard = EgressGuard(
        EgressGuardConfig(blocked_country_codes=frozenset({"CN"})),
        urlopen=_urlopen_sequence(
            "198.51.100.11",
            {"status": "fail"},
            {"ip": "198.51.100.11", "country_code": "US", "country": "United States"},
        ),
    )

    location = guard.ensure_allowed()

    assert location is not None
    assert location.provider == "ipsb"
    assert location.country_code == "US"


def test_egress_guard_fails_closed_when_all_providers_are_unavailable() -> None:
    guard = EgressGuard(
        EgressGuardConfig(blocked_country_codes=frozenset({"CN"}), fail_closed=True),
        urlopen=_raising_urlopen,
    )

    with pytest.raises(EgressGuardUnavailable):
        guard.ensure_allowed()


def test_egress_guard_can_fail_open_when_configured(caplog: pytest.LogCaptureFixture) -> None:
    guard = EgressGuard(
        EgressGuardConfig(blocked_country_codes=frozenset({"CN"}), fail_closed=False),
        urlopen=_raising_urlopen,
    )

    with caplog.at_level("WARNING", logger="claude_code_local_proxy.egress_guard"):
        assert guard.ensure_allowed() is None

    assert "request allowed by fail-open policy" in caplog.text


def test_egress_guard_caches_ip_region_but_rechecks_current_public_ip() -> None:
    calls = 0

    def urlopen(*args: object, **kwargs: object) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls in {1, 3}:
            return FakeResponse("198.51.100.12\n")
        return FakeResponse({"ip": "198.51.100.12", "country_code": "US"})

    guard = EgressGuard(
        EgressGuardConfig(blocked_country_codes=frozenset({"CN"}), ip_region_cache_seconds=30),
        urlopen=urlopen,
    )

    guard.ensure_allowed()
    guard.ensure_allowed()

    assert calls == 3


def test_egress_guard_looks_up_region_again_when_public_ip_changes() -> None:
    calls = 0

    def urlopen(*args: object, **kwargs: object) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return FakeResponse("198.51.100.12")
        if calls == 2:
            return FakeResponse({"ip": "198.51.100.12", "country_code": "US"})
        if calls == 3:
            return FakeResponse("203.0.113.10")
        return FakeResponse({"ip": "203.0.113.10", "country_code": "JP"})

    guard = EgressGuard(
        EgressGuardConfig(blocked_country_codes=frozenset({"CN"}), ip_region_cache_seconds=30),
        urlopen=urlopen,
    )

    first = guard.ensure_allowed()
    second = guard.ensure_allowed()

    assert first is not None
    assert second is not None
    assert first.ip == "198.51.100.12"
    assert second.ip == "203.0.113.10"
    assert calls == 4


def test_egress_guard_reuses_last_successful_public_ip_provider() -> None:
    urls: list[str] = []

    def urlopen(request: object, **kwargs: object) -> FakeResponse:
        assert isinstance(request, urllib.request.Request)
        url = request.full_url
        urls.append(url)
        if url == "https://api.ipify.org":
            raise OSError("provider unavailable")
        if url == "https://checkip.amazonaws.com":
            return FakeResponse("198.51.100.12")
        return FakeResponse({"ip": "198.51.100.12", "country_code": "US"})

    guard = EgressGuard(
        EgressGuardConfig(blocked_country_codes=frozenset({"CN"}), ip_region_cache_seconds=30),
        urlopen=urlopen,
    )

    guard.ensure_allowed()
    guard.ensure_allowed()

    assert urls[:2] == ["https://api.ipify.org", "https://checkip.amazonaws.com"]
    assert urls[3] == "https://checkip.amazonaws.com"


def test_egress_guard_rejects_geo_response_for_different_ip() -> None:
    guard = EgressGuard(
        EgressGuardConfig(blocked_country_codes=frozenset({"CN"}), fail_closed=True),
        urlopen=_urlopen_sequence(
            "198.51.100.12",
            {"ip": "203.0.113.10", "country_code": "US"},
            {"ip": "203.0.113.10", "country_code": "US"},
        ),
    )

    with pytest.raises(EgressGuardUnavailable):
        guard.ensure_allowed()


def _urlopen_sequence(*payloads: dict[str, Any] | str) -> Any:
    iterator = iter(payloads)

    def urlopen(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse(next(iterator))

    return urlopen


def _raising_urlopen(*args: object, **kwargs: object) -> FakeResponse:
    raise OSError("network unavailable")
