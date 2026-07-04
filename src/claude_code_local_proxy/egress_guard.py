"""Egress IP location guard for outbound Claude Code requests."""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from claude_code_local_proxy.config import (
    DEFAULT_EGRESS_GUARD_BLOCKED_COUNTRY_CODES,
    DEFAULT_EGRESS_GUARD_FAIL_CLOSED,
    DEFAULT_EGRESS_GUARD_FIXED_IP,
    DEFAULT_EGRESS_GUARD_IP_REGION_CACHE_SECONDS,
    DEFAULT_EGRESS_GUARD_MODE,
    DEFAULT_EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS,
    DEFAULT_EGRESS_GUARD_PUBLIC_IP_CACHE_SECONDS,
)

LOGGER = logging.getLogger(__name__)
EgressGuardMode = Literal["country-code", "fixed-ip"]
_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")
_MAX_GEO_RESPONSE_BYTES = 64 * 1024
_MAX_IP_RESPONSE_BYTES = 1024
_USER_AGENT = "claude-code-local-proxy-egress-guard/0.1"


@dataclass(frozen=True)
class EgressLocation:
    provider: str
    country_code: str
    ip: str
    country: str | None = None
    region: str | None = None
    city: str | None = None


class EgressChecker(Protocol):
    def ensure_allowed(self) -> EgressLocation | None: ...


@dataclass(frozen=True)
class PublicIpProvider:
    name: str
    url: str


@dataclass(frozen=True)
class GeoProvider:
    name: str
    url_template: str
    parser: Callable[[dict[str, Any], str], EgressLocation | None]


@dataclass(frozen=True)
class EgressGuardConfig:
    mode: EgressGuardMode = cast(EgressGuardMode, DEFAULT_EGRESS_GUARD_MODE)
    fixed_ip: str | None = DEFAULT_EGRESS_GUARD_FIXED_IP
    blocked_country_codes: frozenset[str] = field(
        default_factory=lambda: parse_country_codes(DEFAULT_EGRESS_GUARD_BLOCKED_COUNTRY_CODES)
    )
    provider_timeout_seconds: float = DEFAULT_EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS
    public_ip_cache_seconds: float = DEFAULT_EGRESS_GUARD_PUBLIC_IP_CACHE_SECONDS
    ip_region_cache_seconds: float = DEFAULT_EGRESS_GUARD_IP_REGION_CACHE_SECONDS
    fail_closed: bool = DEFAULT_EGRESS_GUARD_FAIL_CLOSED

    def __post_init__(self) -> None:
        if self.mode not in {"country-code", "fixed-ip"}:
            raise ValueError("mode must be one of: country-code, fixed-ip")
        if self.mode == "fixed-ip" and self.fixed_ip is None:
            raise ValueError("fixed_ip is required when mode is fixed-ip")
        if self.fixed_ip is not None:
            normalized_ip = normalize_public_ip(self.fixed_ip)
            object.__setattr__(self, "fixed_ip", normalized_ip)
        if self.provider_timeout_seconds <= 0:
            raise ValueError("provider_timeout_seconds must be positive")
        if self.public_ip_cache_seconds < 0:
            raise ValueError("public_ip_cache_seconds must be non-negative")
        if self.ip_region_cache_seconds < 0:
            raise ValueError("ip_region_cache_seconds must be non-negative")


class EgressGuardBlocked(Exception):
    """Raised when the current egress IP is in a blocked region."""

    def __init__(self, location: EgressLocation) -> None:
        self.location = location
        super().__init__(
            "egress IP is in a blocked region: "
            f"country_code={location.country_code} provider={location.provider} ip={location.ip}"
        )


class EgressGuardIpChanged(Exception):
    """Raised when the current egress IP no longer matches the fixed IP policy."""

    def __init__(self, expected_ip: str, current_ip: str) -> None:
        self.expected_ip = expected_ip
        self.current_ip = current_ip
        super().__init__(
            f"egress IP changed from fixed value: expected_ip={expected_ip} current_ip={current_ip}"
        )


class EgressGuardUnavailable(Exception):
    """Raised when the guard cannot determine egress location and fail-closed is enabled."""

    def __init__(self, provider_errors: tuple[str, ...]) -> None:
        self.provider_errors = provider_errors
        super().__init__("egress location unavailable; request blocked by fail-closed policy")


@dataclass(frozen=True)
class _CachedLocation:
    location: EgressLocation
    cached_at: float


@dataclass(frozen=True)
class _CachedPublicIp:
    ip: str
    cached_at: float


class EgressGuard:
    """Check the current public egress IP before an upstream request is sent."""

    def __init__(
        self,
        config: EgressGuardConfig,
        *,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        monotonic: Callable[[], float] = time.monotonic,
        ip_providers: tuple[PublicIpProvider, ...] = (),
        geo_providers: tuple[GeoProvider, ...] = (),
    ) -> None:
        self._config = config
        self._urlopen = urlopen
        self._monotonic = monotonic
        self._ip_providers = ip_providers or _PUBLIC_IP_PROVIDERS
        self._geo_providers = geo_providers or _GEO_PROVIDERS
        self._lock = threading.Lock()
        self._public_ip_refresh_lock = threading.Lock()
        self._location_by_ip: dict[str, _CachedLocation] = {}
        self._cached_public_ip: _CachedPublicIp | None = None
        self._preferred_ip_provider_name: str | None = None

    def ensure_allowed(self) -> EgressLocation | None:
        ip, ip_errors = self._current_public_ip()
        if ip is None:
            return self._handle_unavailable(tuple(ip_errors))

        if self._config.mode == "fixed-ip":
            return self._ensure_fixed_ip_allowed(ip)

        location = self._cached_location(ip)
        if location is None:
            location, geo_errors = self._lookup_location(ip)
            if location is None:
                return self._handle_unavailable(tuple(ip_errors + geo_errors))
            self._cache_location(location)

        if location.country_code in self._config.blocked_country_codes:
            raise EgressGuardBlocked(location)
        return location

    def _ensure_fixed_ip_allowed(self, ip: str) -> EgressLocation:
        fixed_ip = self._config.fixed_ip
        if fixed_ip is None:  # pragma: no cover - rejected by EgressGuardConfig.
            raise EgressGuardUnavailable(("fixed-ip mode requires fixed_ip",))
        if ip != fixed_ip:
            raise EgressGuardIpChanged(expected_ip=fixed_ip, current_ip=ip)
        return EgressLocation(provider="fixed-ip", country_code="UNKNOWN", ip=ip)

    def _current_public_ip(self) -> tuple[str | None, list[str]]:
        if self._config.public_ip_cache_seconds <= 0:
            return self._lookup_current_public_ip()

        cached = self._cached_current_public_ip()
        if cached is not None:
            return cached, []

        with self._public_ip_refresh_lock:
            cached = self._cached_current_public_ip()
            if cached is not None:
                return cached, []
            return self._lookup_current_public_ip()

    def _lookup_current_public_ip(self) -> tuple[str | None, list[str]]:
        provider_errors: list[str] = []
        for provider in self._ordered_ip_providers():
            try:
                ip = self._fetch_public_ip(provider)
            except Exception as exc:  # pragma: no cover - provider failures vary at runtime
                provider_errors.append(f"{provider.name}: {exc}")
                continue
            self._remember_ip_provider(provider.name)
            self._cache_current_public_ip(ip)
            return ip, provider_errors
        return None, provider_errors

    def _cached_current_public_ip(self) -> str | None:
        if self._config.public_ip_cache_seconds <= 0:
            return None
        with self._lock:
            cached = self._cached_public_ip
            if cached is None:
                return None
            if self._monotonic() - cached.cached_at >= self._config.public_ip_cache_seconds:
                self._cached_public_ip = None
                return None
            return cached.ip

    def _cache_current_public_ip(self, ip: str) -> None:
        if self._config.public_ip_cache_seconds <= 0:
            return
        with self._lock:
            self._cached_public_ip = _CachedPublicIp(ip, self._monotonic())

    def _ordered_ip_providers(self) -> tuple[PublicIpProvider, ...]:
        with self._lock:
            preferred_name = self._preferred_ip_provider_name
        if preferred_name is None:
            return self._ip_providers
        preferred = tuple(
            provider for provider in self._ip_providers if provider.name == preferred_name
        )
        remaining = tuple(
            provider for provider in self._ip_providers if provider.name != preferred_name
        )
        return preferred + remaining

    def _remember_ip_provider(self, provider_name: str) -> None:
        with self._lock:
            self._preferred_ip_provider_name = provider_name

    def _fetch_public_ip(self, provider: PublicIpProvider) -> str:
        body = self._read_provider_body(provider.url, max_bytes=_MAX_IP_RESPONSE_BYTES)
        raw_ip = body.decode("utf-8").strip()
        return str(ipaddress.ip_address(raw_ip))

    def _cached_location(self, ip: str) -> EgressLocation | None:
        if self._config.ip_region_cache_seconds <= 0:
            return None
        with self._lock:
            cached = self._location_by_ip.get(ip)
            if cached is None:
                return None
            if self._monotonic() - cached.cached_at >= self._config.ip_region_cache_seconds:
                del self._location_by_ip[ip]
                return None
            return cached.location

    def _cache_location(self, location: EgressLocation) -> None:
        if self._config.ip_region_cache_seconds <= 0:
            return
        with self._lock:
            self._location_by_ip[location.ip] = _CachedLocation(location, self._monotonic())

    def _lookup_location(self, ip: str) -> tuple[EgressLocation | None, list[str]]:
        provider_errors: list[str] = []
        for provider in self._geo_providers:
            try:
                location = self._fetch_location(provider, ip)
            except Exception as exc:  # pragma: no cover - provider failures vary at runtime
                provider_errors.append(f"{provider.name}: {exc}")
                continue
            if location is None:
                provider_errors.append(f"{provider.name}: no country code in response")
                continue
            return location, provider_errors
        return None, provider_errors

    def _fetch_location(self, provider: GeoProvider, ip: str) -> EgressLocation | None:
        quoted_ip = urllib.parse.quote(ip, safe="")
        body = self._read_provider_body(
            provider.url_template.format(ip=quoted_ip),
            max_bytes=_MAX_GEO_RESPONSE_BYTES,
        )
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("geo provider response is not an object")
        return provider.parser(payload, ip)

    def _read_provider_body(self, url: str, *, max_bytes: int) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with self._urlopen(request, timeout=self._config.provider_timeout_seconds) as response:
            body = response.read(max_bytes + 1)
        if not isinstance(body, bytes):
            raise ValueError("provider response is not bytes")
        if len(body) > max_bytes:
            raise ValueError("provider response too large")
        return body

    def _handle_unavailable(self, provider_errors: tuple[str, ...]) -> EgressLocation | None:
        if self._config.fail_closed:
            raise EgressGuardUnavailable(provider_errors)
        LOGGER.warning(
            "egress location unavailable; request allowed by fail-open policy provider_errors=%s",
            "; ".join(provider_errors) or "none",
        )
        return None


def parse_country_codes(value: str) -> frozenset[str]:
    codes = frozenset(token.strip().upper() for token in value.split(",") if token.strip())
    invalid = sorted(code for code in codes if _COUNTRY_CODE_RE.fullmatch(code) is None)
    if invalid:
        raise ValueError(
            f"country codes must be comma-separated ISO 3166-1 alpha-2 values: {', '.join(invalid)}"
        )
    if not codes:
        raise ValueError("at least one blocked country code is required")
    return codes


def parse_egress_guard_mode(value: str) -> EgressGuardMode:
    normalized = value.strip().lower()
    if normalized not in {"country-code", "fixed-ip"}:
        raise ValueError("expected one of: country-code, fixed-ip")
    return cast(EgressGuardMode, normalized)


def normalize_public_ip(value: str) -> str:
    return str(ipaddress.ip_address(value.strip()))


def _parse_ipwho(payload: dict[str, Any], queried_ip: str) -> EgressLocation | None:
    if payload.get("success") is False:
        return None
    return _location_from_payload(
        "ipwho",
        queried_ip=queried_ip,
        country_code=payload.get("country_code"),
        ip=payload.get("ip"),
        country=payload.get("country"),
        region=payload.get("region"),
        city=payload.get("city"),
    )


def _parse_ipsb(payload: dict[str, Any], queried_ip: str) -> EgressLocation | None:
    return _location_from_payload(
        "ipsb",
        queried_ip=queried_ip,
        country_code=payload.get("country_code"),
        ip=payload.get("ip"),
        country=payload.get("country"),
        region=payload.get("region"),
        city=payload.get("city"),
    )


def _location_from_payload(
    provider: str,
    *,
    queried_ip: str,
    country_code: object,
    ip: object,
    country: object,
    region: object,
    city: object,
) -> EgressLocation | None:
    if not isinstance(country_code, str) or not country_code.strip():
        return None
    return EgressLocation(
        provider=provider,
        country_code=country_code.strip().upper(),
        ip=_normalize_payload_ip(ip, queried_ip),
        country=country if isinstance(country, str) and country else None,
        region=region if isinstance(region, str) and region else None,
        city=city if isinstance(city, str) and city else None,
    )


def _normalize_payload_ip(ip: object, queried_ip: str) -> str:
    if not isinstance(ip, str) or not ip.strip():
        return queried_ip
    normalized = str(ipaddress.ip_address(ip.strip()))
    if normalized != queried_ip:
        raise ValueError("geo provider returned a different IP than requested")
    return normalized


_PUBLIC_IP_PROVIDERS = (
    PublicIpProvider("ipify", "https://api.ipify.org"),
    PublicIpProvider("aws-checkip", "https://checkip.amazonaws.com"),
    PublicIpProvider("icanhazip", "https://icanhazip.com"),
)

_GEO_PROVIDERS = (
    GeoProvider("ipwho", "https://ipwho.is/{ip}", _parse_ipwho),
    GeoProvider("ipsb", "https://api.ip.sb/geoip/{ip}", _parse_ipsb),
)
