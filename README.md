# claude-code-local-proxy

A local Anthropic-compatible proxy for processing Claude Code requests before forwarding them to an upstream API.

Use it when you want Claude Code to talk to a local endpoint first, so request processing can happen before traffic reaches Anthropic or a channel provider:

```text
Claude Code → http://127.0.0.1:8787 → upstream Anthropic-compatible API
```

By default, the upstream is the official Anthropic API:

```text
https://api.anthropic.com
```

Set `UPSTREAM_BASE_URL` only when you want to forward to a different channel or proxy.

## Sanitizer rules

Sanitizer rules inspect JSON string values in request bodies. Unrelated headers, response bodies, invalid JSON, and non-JSON requests are forwarded unchanged.

Sanitizer mode applies to every enabled rule:

| Mode | Behavior |
|---|---|
| `off` | Do not scan or modify JSON bodies. |
| `observe` | Detect rule statistics and log counts, but forward the original body. |
| `normalize` | Detect and normalize known rule matches before forwarding. |

`normalize` is the default.

### Date marker rule

The first built-in rule targets this narrow Claude Code date-line pattern:

```text
Today['’ʼʹ]s date is YYYY[-/]MM[-/]DD
```

In `normalize` mode it becomes:

```text
Today's date is YYYY-MM-DD
```

The date value is preserved. Unrelated dates and unrelated apostrophes are not modified.

When markers are observed, the proxy logs aggregate metadata only:

```text
marker observed path=/v1/messages mode=normalize date_lines=1 apostrophe_variants=1 slash_dates=1 replacements=1
```

It does not log full prompts or request bodies.

## Install

```bash
make install
cp .env.example .env
```

Edit `.env` only for values you want to override:

```dotenv
PROXY_LISTEN_HOST=127.0.0.1
PROXY_LISTEN_PORT=8787

# Defaults to https://api.anthropic.com.
# UPSTREAM_BASE_URL=https://your-channel.example.com

SANITIZER_MODE=normalize
```

## Run

Start the proxy:

```bash
uv run claude-code-local-proxy
```

Point Claude Code at the local proxy:

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
claude
```

## Configuration

Day-to-day usage should prefer `.env`. CLI flags are mainly for temporary overrides, debugging, or running multiple local proxy instances.

Default values are defined in `src/claude_code_local_proxy/config.py`; `.env.example` is only a copyable example.

| CLI flag | Environment variable | Default |
|---|---|---|
| `--listen-host` | `PROXY_LISTEN_HOST` | `127.0.0.1` |
| `--listen-port` | `PROXY_LISTEN_PORT` | `8787` |
| `--upstream-base-url` | `UPSTREAM_BASE_URL` | `https://api.anthropic.com` |
| `--sanitizer-mode` | `SANITIZER_MODE` | `normalize` |

See `.env.example` for less commonly changed settings such as upstream timeout and log level.

## Development

```bash
make fmt      # format and apply safe lint fixes
make check    # ruff + mypy + pytest coverage
```

The proxy is intentionally implemented with Python's standard-library HTTP server/client plus `python-dotenv`; avoid adding framework dependencies unless the proxy needs capabilities the standard library cannot provide.
