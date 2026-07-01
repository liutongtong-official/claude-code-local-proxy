# Developer entry points

SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help install fmt lint type test test-coverage check hooks

help:  ## Show available targets
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n\nTargets:\n"} \
	      /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install:  ## Sync dependencies and install pre-commit hooks
	uv sync
	uv run pre-commit install --hook-type pre-commit --hook-type pre-push

fmt:  ## Format code (ruff format + ruff check --fix)
	uv run ruff format
	uv run ruff check --fix

lint:  ## Lint without auto-fix
	uv run ruff check
	uv run ruff format --check

type:  ## Type-check with mypy
	uv run mypy

test:  ## Run pytest
	uv run pytest

test-coverage:  ## Run pytest with coverage (term + build/coverage/coverage.xml)
	uv run pytest --cov --cov-report=term-missing --cov-report=xml

check: lint type test-coverage  ## lint + type + test-coverage (pre-commit hooks run separately: make hooks)

hooks:  ## Run all pre-commit hooks against all files
	uv run pre-commit run --all-files --hook-stage pre-push
