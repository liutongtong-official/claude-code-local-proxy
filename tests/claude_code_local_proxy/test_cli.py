"""Tests for CLI argument handling."""

import logging
import shutil
import subprocess
from collections.abc import Iterator
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_local_proxy import cli
from claude_code_local_proxy.cli import main
from claude_code_local_proxy.config import DEFAULT_UPSTREAM_BASE_URL
from claude_code_local_proxy.egress_guard import EgressGuard
from claude_code_local_proxy.proxy import ProxyConfig

_CLI_ENV_KEYS = (
    "PROXY_LISTEN_HOST",
    "PROXY_LISTEN_PORT",
    "UPSTREAM_BASE_URL",
    "UPSTREAM_TIMEOUT_SECONDS",
    "SANITIZER_MODE",
    "SANITIZER_PUBLIC_BASE_URL",
    "SANITIZER_RULES",
    "SANITIZER_TIMEZONE",
    "EGRESS_GUARD_ENABLED",
    "EGRESS_GUARD_MODE",
    "EGRESS_GUARD_FIXED_IP",
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


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level

    try:
        yield
    finally:
        for handler in list(root.handlers):
            if handler not in old_handlers:
                root.removeHandler(handler)
                handler.close()
        for handler in old_handlers:
            if handler not in root.handlers:
                root.addHandler(handler)
        root.setLevel(old_level)


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
    assert config.sanitizer_rules == ()
    assert config.egress_guard is None
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 0


def test_cli_rejects_invalid_sanitizer_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)
    monkeypatch.setenv("SANITIZER_MODE", "normlize")

    with pytest.raises(SystemExit, match="SANITIZER_MODE must be one of"):
        main(["--listen-port", "0"])


def test_cli_accepts_sanitizer_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_server(host: str, port: int, config: object) -> None:
        captured["config"] = config

    _clear_cli_env(monkeypatch)
    monkeypatch.setattr("claude_code_local_proxy.cli.run_server", fake_run_server)

    main(["--listen-port", "0", "--sanitizer-timezone", "America/Los_Angeles"])

    config = captured["config"]
    assert isinstance(config, ProxyConfig)
    assert config.sanitizer_timezone == "America/Los_Angeles"


def test_cli_accepts_sanitizer_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_server(host: str, port: int, config: object) -> None:
        captured["config"] = config

    _clear_cli_env(monkeypatch)
    monkeypatch.setattr("claude_code_local_proxy.cli.run_server", fake_run_server)

    main(
        [
            "--listen-port",
            "0",
            "--sanitizer-rules",
            "date-marker,timezone-marker",
            "--sanitizer-timezone",
            "America/Los_Angeles",
        ]
    )

    config = captured["config"]
    assert isinstance(config, ProxyConfig)
    assert config.sanitizer_rules == ("date-marker", "timezone-marker")


def test_cli_configures_base_url_sanitizer(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_server(host: str, port: int, config: object) -> None:
        captured["config"] = config

    _clear_cli_env(monkeypatch)
    monkeypatch.setattr("claude_code_local_proxy.cli.run_server", fake_run_server)

    main(
        [
            "--listen-port",
            "8787",
            "--sanitizer-rules",
            "base-url",
            "--sanitizer-public-base-url",
            "https://api.anthropic.com/",
        ]
    )

    config = captured["config"]
    assert isinstance(config, ProxyConfig)
    assert config.sanitizer_rules == ("base-url",)
    assert config.sanitizer_public_base_url == "https://api.anthropic.com"
    assert config.sanitizer_local_base_urls == ("http://127.0.0.1:8787", "http://localhost:8787")


def test_cli_rejects_unknown_sanitizer_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)
    monkeypatch.setenv("SANITIZER_RULES", "date-marker,unknown")

    with pytest.raises(SystemExit, match="SANITIZER_RULES is invalid"):
        main(["--listen-port", "0"])


def test_cli_rejects_timezone_rule_without_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)

    with pytest.raises(SystemExit, match="timezone-marker requires"):
        main(["--listen-port", "0", "--sanitizer-rules", "timezone-marker"])


def test_cli_rejects_invalid_sanitizer_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)
    monkeypatch.setenv("SANITIZER_TIMEZONE", "Mars/Olympus")

    with pytest.raises(SystemExit, match="SANITIZER_TIMEZONE is invalid"):
        main(["--listen-port", "0"])


def test_cli_rejects_invalid_sanitizer_timezone_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)

    with pytest.raises(SystemExit):
        main(["--listen-port", "0", "--sanitizer-timezone", "Mars/Olympus"])


def test_cli_can_enable_egress_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_server(host: str, port: int, config: object) -> None:
        captured["config"] = config

    _clear_cli_env(monkeypatch)
    monkeypatch.setattr("claude_code_local_proxy.cli.run_server", fake_run_server)

    main(["--listen-port", "0", "--egress-guard-enabled"])

    config = captured["config"]
    assert isinstance(config, ProxyConfig)
    assert isinstance(config.egress_guard, EgressGuard)


def test_cli_accepts_fixed_ip_egress_guard_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_server(host: str, port: int, config: object) -> None:
        captured["config"] = config

    _clear_cli_env(monkeypatch)
    monkeypatch.setattr("claude_code_local_proxy.cli.run_server", fake_run_server)

    main(
        [
            "--listen-port",
            "0",
            "--egress-guard-enabled",
            "--egress-guard-mode",
            "fixed-ip",
            "--egress-guard-fixed-ip",
            "198.51.100.10",
        ]
    )

    config = captured["config"]
    assert isinstance(config, ProxyConfig)
    assert isinstance(config.egress_guard, EgressGuard)
    assert config.egress_guard._config.mode == "fixed-ip"
    assert config.egress_guard._config.fixed_ip == "198.51.100.10"


def test_cli_rejects_fixed_ip_mode_without_fixed_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)

    with pytest.raises(SystemExit, match="egress guard configuration is invalid"):
        main(["--listen-port", "0", "--egress-guard-enabled", "--egress-guard-mode", "fixed-ip"])


def test_cli_rejects_invalid_egress_guard_fixed_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)
    monkeypatch.setenv("EGRESS_GUARD_FIXED_IP", "not-an-ip")

    with pytest.raises(SystemExit, match="EGRESS_GUARD_FIXED_IP is invalid"):
        main(["--listen-port", "0"])


def test_cli_can_write_logs_to_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log_file = tmp_path / "runtime" / "proxy.log"

    def fake_run_server(host: str, port: int, config: object) -> None:
        logging.getLogger("claude_code_local_proxy.tests").warning("saved log marker")

    _clear_cli_env(monkeypatch)
    monkeypatch.setattr("claude_code_local_proxy.cli.run_server", fake_run_server)

    main(["--listen-port", "0", "--log-file", str(log_file)])
    _flush_root_log_handlers()

    assert "saved log marker" in log_file.read_text()


def test_cli_rotates_file_logs_daily_with_seven_day_retention(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "runtime" / "proxy.log"

    def fake_run_server(host: str, port: int, config: object) -> None:
        pass

    _clear_cli_env(monkeypatch)
    monkeypatch.setattr("claude_code_local_proxy.cli.run_server", fake_run_server)

    main(["--listen-port", "0", "--log-file", str(log_file)])

    file_handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, TimedRotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    handler = file_handlers[0]
    assert handler.baseFilename == str(log_file)
    assert handler.when == "MIDNIGHT"
    assert handler.backupCount == 7


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
    if not shutil.which("make"):
        pytest.skip("make is not installed")

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
        main(
            [
                "--listen-port",
                "0",
                "--egress-guard-enabled",
                "--egress-guard-blocked-country-codes",
                "CHN",
            ]
        )


def test_cli_rejects_invalid_egress_guard_float_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cli_env(monkeypatch)
    monkeypatch.setenv("EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS", "fast")

    with pytest.raises(SystemExit, match="EGRESS_GUARD_PROVIDER_TIMEOUT_SECONDS is invalid"):
        main(["--listen-port", "0"])


def test_load_env_skips_dotenv_under_pytest() -> None:
    # PYTEST_VERSION is set for the whole run, so _load_env must short-circuit
    # before touching any dotenv file — a developer's real .env secrets never
    # leak into test runs and make them hit external services.
    with (
        patch.object(cli, "find_dotenv") as find,
        patch.object(cli, "load_dotenv") as load,
    ):
        cli._load_env()

    find.assert_not_called()
    load.assert_not_called()


def test_load_env_loads_dotenv_outside_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    # Outside pytest, both files are probed in precedence order (most-specific
    # first) and loaded when found (find_dotenv's default mock return is truthy).
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    with (
        patch.object(cli, "find_dotenv") as find,
        patch.object(cli, "load_dotenv") as load,
    ):
        cli._load_env()

    assert [call.args[0] for call in find.call_args_list] == [".env.local", ".env"]
    assert load.call_count == 2
