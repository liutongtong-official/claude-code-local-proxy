# Developer entry points

SHELL := /bin/bash
.DEFAULT_GOAL := help

LOG_DIR ?= logs
PROXY_LOG_FILE ?= $(LOG_DIR)/claude-code-local-proxy.log
PROXY_PID_FILE ?= $(LOG_DIR)/claude-code-local-proxy.pid

.PHONY: help install run-bg stop-bg fmt lint type test test-coverage check hooks

help:  ## Show available targets
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n\nTargets:\n"} \
	      /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install:  ## Sync dependencies and install pre-commit hooks
	uv sync
	uv run pre-commit install --hook-type pre-commit --hook-type pre-push

run-bg:  ## Start the proxy in the background and write logs to PROXY_LOG_FILE
	@mkdir -p "$(LOG_DIR)" "$$(dirname "$(PROXY_PID_FILE)")"
	@if test -f "$(PROXY_PID_FILE)"; then \
		PID="$$(cat "$(PROXY_PID_FILE)")"; \
		COMMAND="$$(ps -p "$$PID" -o command= 2>/dev/null || true)"; \
		if [[ -n "$$COMMAND" && "$$COMMAND" == *claude-code-local-proxy* ]]; then \
			echo "proxy already running pid=$$PID"; \
			exit 1; \
		fi; \
	fi
	@rm -f "$(PROXY_PID_FILE)"
	@nohup uv run claude-code-local-proxy --log-file "$(PROXY_LOG_FILE)" >/dev/null 2>&1 & \
		PID=$$!; \
		echo "$$PID" > "$(PROXY_PID_FILE)"; \
		sleep 1; \
		if ! kill -0 "$$PID" 2>/dev/null; then \
			rm -f "$(PROXY_PID_FILE)"; \
			echo "proxy failed to start; see $(PROXY_LOG_FILE)"; \
			exit 1; \
		fi; \
		echo "proxy started pid=$$PID log=$(PROXY_LOG_FILE)"

stop-bg:  ## Stop the background proxy started by run-bg
	@if test ! -f "$(PROXY_PID_FILE)"; then \
		echo "proxy is not running"; \
		exit 0; \
	fi; \
	PID="$$(cat "$(PROXY_PID_FILE)")"; \
	if [[ ! "$$PID" =~ ^[0-9]+$$ ]]; then \
		echo "removed invalid pid file pid=$$PID"; \
		rm -f "$(PROXY_PID_FILE)"; \
		exit 0; \
	fi; \
	if kill -0 "$$PID" 2>/dev/null; then \
		COMMAND="$$(ps -p "$$PID" -o command= 2>/dev/null || true)"; \
		if [[ -n "$$COMMAND" && "$$COMMAND" != *claude-code-local-proxy* ]]; then \
			echo "pid $$PID does not look like claude-code-local-proxy; keeping $(PROXY_PID_FILE)"; \
			exit 1; \
		fi; \
		kill "$$PID"; \
		for _ in {1..10}; do \
			if ! kill -0 "$$PID" 2>/dev/null; then \
				rm -f "$(PROXY_PID_FILE)"; \
				echo "proxy stopped pid=$$PID"; \
				exit 0; \
			fi; \
			sleep 0.2; \
		done; \
		echo "proxy did not stop after SIGTERM pid=$$PID"; \
		exit 1; \
	else \
		echo "removed stale pid file pid=$$PID"; \
		rm -f "$(PROXY_PID_FILE)"; \
	fi

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
