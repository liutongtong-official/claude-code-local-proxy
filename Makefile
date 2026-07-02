# Developer entry points

SHELL := /bin/bash
.DEFAULT_GOAL := help

LOG_DIR ?= logs
PROXY_LOG_FILE ?= $(LOG_DIR)/claude-code-local-proxy.log
PROXY_PID_FILE ?= $(LOG_DIR)/claude-code-local-proxy.pid
AUTOSTART_LABEL ?= local.claude-code-local-proxy
LAUNCH_AGENT_TEMPLATE ?= scripts/launchd/local.claude-code-local-proxy.plist.in
LAUNCH_AGENT_DIR ?= $(HOME)/Library/LaunchAgents
LAUNCH_AGENT_PLIST ?= $(LAUNCH_AGENT_DIR)/$(AUTOSTART_LABEL).plist
UV_BIN ?= $(shell command -v uv 2>/dev/null)
LAUNCHD_PATH ?= /usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin

.PHONY: help install run-bg stop-bg install-autostart uninstall-autostart status-autostart fmt lint type test test-coverage check hooks

help:  ## Show available targets
	@awk 'BEGIN {FS = ":.*##"} \
	      /^[a-zA-Z_-]+:.*##/ { names[++n] = $$1; descs[n] = $$2; if (length($$1) > w) w = length($$1) } \
	      END { printf "Usage: make <target>\n\nTargets:\n"; \
	            for (i = 1; i <= n; i++) printf "  \033[36m%-*s\033[0m %s\n", w, names[i], descs[i] }' $(MAKEFILE_LIST)

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

install-autostart:  ## Install a macOS LaunchAgent that starts the proxy at login
	@if [[ "$$(uname -s)" != "Darwin" ]]; then \
		echo "install-autostart is supported on macOS only"; \
		exit 1; \
	fi
	@if [[ -z "$(UV_BIN)" ]]; then \
		echo "uv was not found in PATH"; \
		exit 1; \
	fi
	@mkdir -p "$(LAUNCH_AGENT_DIR)" "$(LOG_DIR)"
	@$(MAKE) --no-print-directory stop-bg
	@AUTOSTART_LABEL="$(AUTOSTART_LABEL)" \
		UV_BIN="$(UV_BIN)" \
		PROXY_LOG_FILE="$(abspath $(PROXY_LOG_FILE))" \
		WORKING_DIRECTORY="$(CURDIR)" \
		LAUNCHD_PATH="$(LAUNCHD_PATH)" \
		STDOUT_LOG_FILE="$(abspath $(LOG_DIR))/claude-code-local-proxy.launchd.out.log" \
		STDERR_LOG_FILE="$(abspath $(LOG_DIR))/claude-code-local-proxy.launchd.err.log" \
		"$(UV_BIN)" run python -c 'import os; from pathlib import Path; from string import Template; from xml.sax.saxutils import escape; names = ("AUTOSTART_LABEL", "UV_BIN", "PROXY_LOG_FILE", "WORKING_DIRECTORY", "LAUNCHD_PATH", "STDOUT_LOG_FILE", "STDERR_LOG_FILE"); values = {name: escape(os.environ[name]) for name in names}; rendered = Template(Path("$(LAUNCH_AGENT_TEMPLATE)").read_text(encoding="utf-8")).substitute(values); Path("$(LAUNCH_AGENT_PLIST)").write_text(rendered, encoding="utf-8")'
	@plutil -lint "$(LAUNCH_AGENT_PLIST)" >/dev/null
	@launchctl bootout "gui/$$(id -u)/$(AUTOSTART_LABEL)" >/dev/null 2>&1 || true
	@launchctl bootstrap "gui/$$(id -u)" "$(LAUNCH_AGENT_PLIST)"
	@launchctl enable "gui/$$(id -u)/$(AUTOSTART_LABEL)"
	@launchctl kickstart -k "gui/$$(id -u)/$(AUTOSTART_LABEL)"
	@echo "autostart installed label=$(AUTOSTART_LABEL) plist=$(LAUNCH_AGENT_PLIST)"

uninstall-autostart:  ## Uninstall the macOS LaunchAgent used for login autostart
	@if [[ "$$(uname -s)" != "Darwin" ]]; then \
		echo "uninstall-autostart is supported on macOS only"; \
		exit 1; \
	fi
	@launchctl bootout "gui/$$(id -u)/$(AUTOSTART_LABEL)" >/dev/null 2>&1 || true
	@rm -f "$(LAUNCH_AGENT_PLIST)"
	@echo "autostart uninstalled label=$(AUTOSTART_LABEL)"

status-autostart:  ## Show the macOS LaunchAgent status
	@if [[ "$$(uname -s)" != "Darwin" ]]; then \
		echo "status-autostart is supported on macOS only"; \
		exit 1; \
	fi
	@echo "plist=$(LAUNCH_AGENT_PLIST)"
	@launchctl print "gui/$$(id -u)/$(AUTOSTART_LABEL)" || true

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
