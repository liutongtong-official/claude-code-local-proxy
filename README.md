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

The egress guard checks the proxy process's current public IP before each upstream request. It then looks up that public IP's country code and returns `451` without forwarding the Claude Code request upstream if the country code is blocked. By default, blocked country codes are `CN,HK,MO,TW`.

The guard uses public IP and geolocation providers without sending prompts, request bodies, response bodies, or credentials to those providers. It sends one request to identify the current public IP, then uses a local `public_ip -> country_code` cache to avoid repeated GeoIP lookups for the same IP.

For safety, the default is fail-closed: if all location providers are unreachable, the proxy returns `503` instead of forwarding the request. Set `EGRESS_GUARD_FAIL_CLOSED=false` only if availability is more important than leak prevention.

By default `EGRESS_GUARD_IP_REGION_CACHE_SECONDS=86400`, so the country code for a previously seen public IP is reused for one day. The current public IP itself is still checked on every request, so a VPN route change is detected before the Claude Code request is forwarded.

## Install

```bash
make install
cp .env.example .env
```

Runtime defaults live in `src/claude_code_local_proxy/config.py`. `.env.example` lists optional overrides only; uncomment entries in `.env` when you want to change a default:

```dotenv
# PROXY_LISTEN_HOST=127.0.0.1
# PROXY_LISTEN_PORT=8787

# UPSTREAM_BASE_URL=https://your-channel.example.com

# SANITIZER_MODE=normalize

# EGRESS_GUARD_ENABLED=true
# EGRESS_GUARD_BLOCKED_COUNTRY_CODES="CN,HK,MO,TW"
# EGRESS_GUARD_FAIL_CLOSED=true
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

## Development

```bash
make fmt      # format and apply safe lint fixes
make check    # ruff + mypy + pytest coverage
```

The proxy is intentionally implemented with Python's standard-library HTTP server/client plus `python-dotenv`; avoid adding framework dependencies unless the proxy needs capabilities the standard library cannot provide.
