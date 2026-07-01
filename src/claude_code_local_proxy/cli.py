"""Entry point for the `claude-code-local-proxy` console script."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from claude_code_local_proxy.config import (
    DEFAULT_EGRESS_GUARD_BLOCKED_COUNTRY_CODES,
    DEFAULT_EGRESS_GUARD_ENABLED,
    DEFAULT_EGRESS_GUARD_FAIL_CLOSED,
    DEFAULT_EGRESS_GUARD_IP_REGION_CACHE_SECONDS,
    DEFAULT_EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS,
    DEFAULT_EGRESS_GUARD_PUBLIC_IP_CACHE_SECONDS,
    DEFAULT_LISTEN_HOST,
    DEFAULT_LISTEN_PORT,
    DEFAULT_LOG_FILE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_SANITIZER_MODE,
    DEFAULT_UPSTREAM_BASE_URL,
    DEFAULT_UPSTREAM_TIMEOUT_SECONDS,
)
from claude_code_local_proxy.egress_guard import EgressGuard, EgressGuardConfig, parse_country_codes
from claude_code_local_proxy.proxy import ProxyConfig, run_server
from claude_code_local_proxy.sanitizer import Mode

_MODES: tuple[Mode, ...] = ("off", "observe", "normalize")
_LOG_RETENTION_DAYS = 7


def _get_sanitizer_mode() -> Mode:
    value = os.getenv("SANITIZER_MODE", DEFAULT_SANITIZER_MODE)
    if value not in _MODES:
        raise SystemExit(f"SANITIZER_MODE must be one of {', '.join(_MODES)} (got {value!r})")
    return value


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("expected one of: true, false, yes, no, on, off, 1, 0")


def _env_value[T](name: str, default: T, parser: Callable[[str], T]) -> T:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return parser(value)
    except ValueError as exc:
        raise SystemExit(f"{name} is invalid: {exc}") from exc


def _load_env() -> None:
    # Precedence (highest → lowest): real env > .env.local > .env.
    if "PYTEST_VERSION" not in os.environ:
        load_dotenv(find_dotenv(".env.local", usecwd=True), override=False)
    load_dotenv(find_dotenv(".env", usecwd=True), override=False)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local proxy for processing Claude Code requests before forwarding.",
    )
    parser.add_argument(
        "--listen-host",
        default=os.getenv("PROXY_LISTEN_HOST", DEFAULT_LISTEN_HOST),
        help=f"Host to bind locally. Defaults to PROXY_LISTEN_HOST or {DEFAULT_LISTEN_HOST}.",
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        default=int(os.getenv("PROXY_LISTEN_PORT", str(DEFAULT_LISTEN_PORT))),
        help=f"Port to bind locally. Defaults to PROXY_LISTEN_PORT or {DEFAULT_LISTEN_PORT}.",
    )
    parser.add_argument(
        "--upstream-base-url",
        default=os.getenv("UPSTREAM_BASE_URL", DEFAULT_UPSTREAM_BASE_URL),
        help=f"Real upstream Anthropic-compatible base URL. Defaults to UPSTREAM_BASE_URL or {DEFAULT_UPSTREAM_BASE_URL}.",
    )
    parser.add_argument(
        "--sanitizer-mode",
        choices=_MODES,
        default=_get_sanitizer_mode(),
        help="Sanitizer mode: off = forward unchanged, observe = log only, normalize = clean markers.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", str(DEFAULT_UPSTREAM_TIMEOUT_SECONDS))),
        help=f"Upstream request timeout. Defaults to UPSTREAM_TIMEOUT_SECONDS or {DEFAULT_UPSTREAM_TIMEOUT_SECONDS:g}.",
    )
    parser.add_argument(
        "--egress-guard-enabled",
        action=argparse.BooleanOptionalAction,
        default=_env_value(
            "EGRESS_GUARD_ENABLED",
            DEFAULT_EGRESS_GUARD_ENABLED,
            _parse_bool,
        ),
        help="Check egress IP location before forwarding. Defaults to EGRESS_GUARD_ENABLED or enabled.",
    )
    parser.add_argument(
        "--egress-guard-blocked-country-codes",
        default=os.getenv(
            "EGRESS_GUARD_BLOCKED_COUNTRY_CODES",
            DEFAULT_EGRESS_GUARD_BLOCKED_COUNTRY_CODES,
        ),
        help="Comma-separated ISO country codes to block. Defaults to EGRESS_GUARD_BLOCKED_COUNTRY_CODES or CN,HK,MO,TW.",
    )
    parser.add_argument(
        "--egress-guard-fail-closed",
        action=argparse.BooleanOptionalAction,
        default=_env_value(
            "EGRESS_GUARD_FAIL_CLOSED",
            DEFAULT_EGRESS_GUARD_FAIL_CLOSED,
            _parse_bool,
        ),
        help="Block requests when egress location cannot be checked. Defaults to EGRESS_GUARD_FAIL_CLOSED or enabled.",
    )
    parser.add_argument(
        "--egress-guard-provider-timeout-seconds",
        type=float,
        default=_env_value(
            "EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS",
            DEFAULT_EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS,
            float,
        ),
        help=f"Per-provider egress location timeout. Defaults to EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS or {DEFAULT_EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS:g}.",
    )
    parser.add_argument(
        "--egress-guard-public-ip-cache-seconds",
        type=float,
        default=_env_value(
            "EGRESS_GUARD_PUBLIC_IP_CACHE_SECONDS",
            DEFAULT_EGRESS_GUARD_PUBLIC_IP_CACHE_SECONDS,
            float,
        ),
        help=f"Seconds to cache the current public IP check. Defaults to EGRESS_GUARD_PUBLIC_IP_CACHE_SECONDS or {DEFAULT_EGRESS_GUARD_PUBLIC_IP_CACHE_SECONDS:g}.",
    )
    parser.add_argument(
        "--egress-guard-ip-region-cache-seconds",
        type=float,
        default=_env_value(
            "EGRESS_GUARD_IP_REGION_CACHE_SECONDS",
            DEFAULT_EGRESS_GUARD_IP_REGION_CACHE_SECONDS,
            float,
        ),
        help=f"Seconds to cache public-IP-to-region lookups. Defaults to EGRESS_GUARD_IP_REGION_CACHE_SECONDS or {DEFAULT_EGRESS_GUARD_IP_REGION_CACHE_SECONDS:g}.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL),
        help=f"Python logging level. Defaults to LOG_LEVEL or {DEFAULT_LOG_LEVEL}.",
    )
    parser.add_argument(
        "--log-file",
        default=os.getenv("LOG_FILE", DEFAULT_LOG_FILE),
        help="Optional path to also write logs to. Defaults to LOG_FILE or console-only logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    _load_env()
    args = _build_parser().parse_args(argv)
    _configure_logging(args.log_level, args.log_file)

    config = ProxyConfig(
        upstream_base_url=args.upstream_base_url,
        mode=args.sanitizer_mode,
        timeout_seconds=args.timeout_seconds,
        egress_guard=_build_egress_guard(args),
    )
    run_server(args.listen_host, args.listen_port, config)


def _configure_logging(level_name: str, log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(
                TimedRotatingFileHandler(
                    log_path,
                    when="midnight",
                    backupCount=_LOG_RETENTION_DAYS,
                    encoding="utf-8",
                )
            )
        except OSError as exc:
            raise SystemExit(f"LOG_FILE is invalid: {exc}") from exc

    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


def _build_egress_guard(args: argparse.Namespace) -> EgressGuard | None:
    if not args.egress_guard_enabled:
        return None
    try:
        config = EgressGuardConfig(
            blocked_country_codes=parse_country_codes(args.egress_guard_blocked_country_codes),
            provider_timeout_seconds=args.egress_guard_provider_timeout_seconds,
            public_ip_cache_seconds=args.egress_guard_public_ip_cache_seconds,
            ip_region_cache_seconds=args.egress_guard_ip_region_cache_seconds,
            fail_closed=args.egress_guard_fail_closed,
        )
    except ValueError as exc:
        raise SystemExit(f"egress guard configuration is invalid: {exc}") from exc
    return EgressGuard(config)


if __name__ == "__main__":
    main()
