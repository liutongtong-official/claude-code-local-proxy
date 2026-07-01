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

## Features

### Sanitizer rules

Sanitizer rules inspect JSON string values in request bodies. Unrelated headers, response bodies, invalid JSON, and non-JSON requests are forwarded unchanged.

Sanitizer mode applies to every enabled rule:

| Mode | Behavior |
|---|---|
| `off` | Do not scan or modify JSON bodies. |
| `observe` | Detect rule statistics and log counts, but forward the original body. |
| `normalize` | Detect and normalize known rule matches before forwarding. |

`normalize` is the default.

#### Date marker rule

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

### Egress guard

By default, the egress guard checks the proxy process's current public IP before each upstream request. It then looks up that public IP's country code and returns `451` without forwarding the Claude Code request upstream if the country code is blocked. By default, blocked country codes are `CN,HK,MO,TW`.

The guard uses public IP and geolocation providers without sending prompts, request bodies, response bodies, or credentials to those providers. When the current public IP needs to be refreshed, it sends one request to identify it, then uses a local `public_ip -> country_code` cache to avoid repeated GeoIP lookups for the same IP.

For safety, the default is fail-closed: if all location providers are unreachable, the proxy returns `503` instead of forwarding the request. Set `EGRESS_GUARD_FAIL_CLOSED=false` only if availability is more important than leak prevention.

By default `EGRESS_GUARD_IP_REGION_CACHE_SECONDS=86400`, so the country code for a previously seen public IP is reused for one day. `EGRESS_GUARD_PUBLIC_IP_CACHE_SECONDS=0` keeps the current public IP cache disabled by default, so a VPN route change is detected before the next Claude Code request is forwarded. Set it to a short value such as `5` or `30` only when you want to reduce public IP provider calls during request bursts and accept that route changes may be detected after that TTL expires.

## Install

```bash
make install
cp .env.example .env
```

Runtime defaults live in `src/claude_code_local_proxy/config.py`. `.env.example` lists optional overrides only; copy it to `.env` and uncomment entries there when you want to change a default.

## Run

Start the proxy in the foreground:

```bash
uv run claude-code-local-proxy
```

To keep logs in a file as well as the console, pass `--log-file` or set `LOG_FILE`:

```bash
uv run claude-code-local-proxy --log-file logs/claude-code-local-proxy.log
```

Start the proxy in the background:

```bash
make run-bg
```

The background target writes the process ID to `logs/claude-code-local-proxy.pid` and application logs to `logs/claude-code-local-proxy.log`. Stop that background process with:

```bash
make stop-bg
```

Point Claude Code at the local proxy:

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
claude
```

## Development

```bash
make fmt      # format and apply safe lint fixes
make check    # ruff + mypy + pytest coverage
```

The proxy is intentionally implemented with Python's standard-library HTTP server/client plus `python-dotenv`; avoid adding framework dependencies unless the proxy needs capabilities the standard library cannot provide.
