"""Smoke tests — verify the package imports and basic wiring works."""

import claude_code_local_proxy


def test_package_has_version() -> None:
    assert claude_code_local_proxy.__version__
