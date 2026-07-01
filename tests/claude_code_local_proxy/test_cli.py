"""Tests for CLI argument handling."""

import pytest

from claude_code_local_proxy.cli import main
from claude_code_local_proxy.config import DEFAULT_UPSTREAM_BASE_URL
from claude_code_local_proxy.proxy import ProxyConfig

_CLI_ENV_KEYS = (
    "PROXY_LISTEN_HOST",
    "PROXY_LISTEN_PORT",
    "UPSTREAM_BASE_URL",
    "UPSTREAM_TIMEOUT_SECONDS",
    "SANITIZER_MODE",
    "EGRESS_GUARD_ENABLED",
    "EGRESS_GUARD_BLOCKED_COUNTRY_CODES",
    "EGRESS_GUARD_FAIL_CLOSED",
    "EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS",
    "EGRESS_GUARD_PUBLIC_IP_CACHE_SECONDS",
    "EGRESS_GUARD_IP_REGION_CACHE_SECONDS",
    "LOG_LEVEL",
)


def _clear_cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _CLI_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_cli_help_runs(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    assert "processing Claude Code requests" in capsys.readouterr().out


def test_cli_uses_official_anthropic_upstream_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_server(host: str, port: int, config: object) -> None:
        captured["host"] = host
        captured["port"] = port
        captured["config"] = config

    _clear_cli_env(monkeypatch)
    monkeypatch.setattr("claude_code_local_proxy.cli.run_server", fake_run_server)

    main(["--listen-port", "0"])

    config = captured["config"]
    assert isinstance(config, ProxyConfig)
    assert config.upstream_base_url == DEFAULT_UPSTREAM_BASE_URL
    assert config.egress_guard is not None
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 0


def test_cli_rejects_invalid_sanitizer_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)
    monkeypatch.setenv("SANITIZER_MODE", "normlize")

    with pytest.raises(SystemExit, match="SANITIZER_MODE must be one of"):
        main(["--listen-port", "0"])


def test_cli_can_disable_egress_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_server(host: str, port: int, config: object) -> None:
        captured["config"] = config

    _clear_cli_env(monkeypatch)
    monkeypatch.setattr("claude_code_local_proxy.cli.run_server", fake_run_server)

    main(["--listen-port", "0", "--no-egress-guard-enabled"])

    config = captured["config"]
    assert isinstance(config, ProxyConfig)
    assert config.egress_guard is None


def test_cli_rejects_invalid_egress_guard_country_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)

    with pytest.raises(SystemExit, match="egress guard configuration is invalid"):
        main(["--listen-port", "0", "--egress-guard-blocked-country-codes", "CHN"])


def test_cli_rejects_invalid_egress_guard_float_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)
    monkeypatch.setenv("EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS", "fast")

    with pytest.raises(SystemExit, match="EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS is invalid"):
        main(["--listen-port", "0"])
