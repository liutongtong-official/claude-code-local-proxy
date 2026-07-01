"""Tests for CLI argument handling."""

import logging
import subprocess
from pathlib import Path

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
    "LOG_FILE",
    "LOG_LEVEL",
)


def _clear_cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _CLI_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _flush_root_log_handlers() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


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


def test_cli_can_write_logs_to_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log_file = tmp_path / "runtime" / "proxy.log"

    def fake_run_server(host: str, port: int, config: object) -> None:
        logging.getLogger("claude_code_local_proxy.tests").warning("saved log marker")

    _clear_cli_env(monkeypatch)
    monkeypatch.setattr("claude_code_local_proxy.cli.run_server", fake_run_server)

    main(["--listen-port", "0", "--log-file", str(log_file)])
    _flush_root_log_handlers()

    assert "saved log marker" in log_file.read_text()


def test_cli_can_write_logs_to_file_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "runtime" / "proxy.log"

    def fake_run_server(host: str, port: int, config: object) -> None:
        logging.getLogger("claude_code_local_proxy.tests").warning("saved log marker")

    _clear_cli_env(monkeypatch)
    monkeypatch.setenv("LOG_FILE", str(log_file))
    monkeypatch.setattr("claude_code_local_proxy.cli.run_server", fake_run_server)

    main(["--listen-port", "0"])
    _flush_root_log_handlers()

    assert "saved log marker" in log_file.read_text()


def test_background_make_targets_dry_run() -> None:
    project_root = Path(__file__).parents[2]
    result = subprocess.run(
        ["make", "-n", "run-bg", "stop-bg"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "nohup uv run claude-code-local-proxy" in result.stdout
    assert "proxy stopped pid=$PID" in result.stdout


def test_cli_rejects_invalid_egress_guard_country_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)

    with pytest.raises(SystemExit, match="egress guard configuration is invalid"):
        main(["--listen-port", "0", "--egress-guard-blocked-country-codes", "CHN"])


def test_cli_rejects_invalid_egress_guard_float_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)
    monkeypatch.setenv("EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS", "fast")

    with pytest.raises(SystemExit, match="EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS is invalid"):
        main(["--listen-port", "0"])
