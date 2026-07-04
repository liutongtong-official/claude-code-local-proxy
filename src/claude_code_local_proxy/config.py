"""Configuration defaults for claude-code-local-proxy."""

from __future__ import annotations

from claude_code_local_proxy.sanitizer import Mode

# Local server defaults.
DEFAULT_LISTEN_HOST = "127.0.0.1"
DEFAULT_LISTEN_PORT = 8787
DEFAULT_LOG_FILE: str | None = None
DEFAULT_LOG_LEVEL = "INFO"

# Request sanitizer defaults.
DEFAULT_SANITIZER_MODE: Mode = "normalize"
DEFAULT_SANITIZER_RULES: tuple[str, ...] = ()
DEFAULT_SANITIZER_TIMEZONE: str | None = None
DEFAULT_SANITIZER_PUBLIC_BASE_URL: str | None = None

# Upstream API defaults.
DEFAULT_UPSTREAM_BASE_URL = "https://api.anthropic.com"
DEFAULT_UPSTREAM_TIMEOUT_SECONDS = 300.0

# Egress guard defaults.
DEFAULT_EGRESS_GUARD_ENABLED = False
DEFAULT_EGRESS_GUARD_MODE = "country-code"
DEFAULT_EGRESS_GUARD_FIXED_IP: str | None = None
DEFAULT_EGRESS_GUARD_BLOCKED_COUNTRY_CODES = "CN,HK,MO,TW"
DEFAULT_EGRESS_GUARD_FAIL_CLOSED = True
DEFAULT_EGRESS_GUARD_PUBLIC_IP_CACHE_SECONDS = 0.0
DEFAULT_EGRESS_GUARD_IP_REGION_CACHE_SECONDS = 86400.0
DEFAULT_EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS = 5.0
