"""Tests for CLI argument handling."""

import pytest

from claude_code_local_proxy.cli import main
from claude_code_local_proxy.config import DEFAULT_UPSTREAM_BASE_URL
from claude_code_local_proxy.proxy import ProxyConfig


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

    monkeypatch.delenv("UPSTREAM_BASE_URL", raising=False)
    monkeypatch.setattr("claude_code_local_proxy.cli.run_server", fake_run_server)

    main(["--listen-port", "0"])

    config = captured["config"]
    assert isinstance(config, ProxyConfig)
    assert config.upstream_base_url == DEFAULT_UPSTREAM_BASE_URL
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 0


def test_cli_rejects_invalid_sanitizer_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANITIZER_MODE", "normlize")

    with pytest.raises(SystemExit, match="SANITIZER_MODE must be one of"):
        main(["--listen-port", "0"])
