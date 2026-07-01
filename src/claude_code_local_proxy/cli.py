"""Entry point for the `claude-code-local-proxy` console script."""

from __future__ import annotations

import argparse
import logging
import os

from dotenv import find_dotenv, load_dotenv

from claude_code_local_proxy.config import (
    DEFAULT_LISTEN_HOST,
    DEFAULT_LISTEN_PORT,
    DEFAULT_LOG_LEVEL,
    DEFAULT_SANITIZER_MODE,
    DEFAULT_UPSTREAM_BASE_URL,
    DEFAULT_UPSTREAM_TIMEOUT_SECONDS,
)
from claude_code_local_proxy.proxy import ProxyConfig, run_server
from claude_code_local_proxy.sanitizer import Mode

_MODES: tuple[Mode, ...] = ("off", "observe", "normalize")


def _get_sanitizer_mode() -> Mode:
    value = os.getenv("SANITIZER_MODE", DEFAULT_SANITIZER_MODE)
    if value not in _MODES:
        raise SystemExit(f"SANITIZER_MODE must be one of {', '.join(_MODES)} (got {value!r})")
    return value


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
        "--log-level",
        default=os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL),
        help=f"Python logging level. Defaults to LOG_LEVEL or {DEFAULT_LOG_LEVEL}.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    _load_env()
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = ProxyConfig(
        upstream_base_url=args.upstream_base_url,
        mode=args.sanitizer_mode,
        timeout_seconds=args.timeout_seconds,
    )
    run_server(args.listen_host, args.listen_port, config)


if __name__ == "__main__":
    main()
