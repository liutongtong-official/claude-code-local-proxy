"""Configuration defaults for claude-code-local-proxy."""

from __future__ import annotations

from claude_code_local_proxy.sanitizer import Mode

DEFAULT_LISTEN_HOST = "127.0.0.1"
DEFAULT_LISTEN_PORT = 8787
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_SANITIZER_MODE: Mode = "normalize"
DEFAULT_UPSTREAM_BASE_URL = "https://api.anthropic.com"
DEFAULT_UPSTREAM_TIMEOUT_SECONDS = 300.0
