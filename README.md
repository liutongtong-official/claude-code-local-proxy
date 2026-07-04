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

No sanitizer rules are enabled by default. Set `SANITIZER_RULES` to a comma-separated list when you want specific rules to run:

```bash
SANITIZER_RULES=date-marker,timezone-marker,base-url
```

#### Date marker rule

Enable `date-marker` to target this narrow Claude Code date-line pattern:

```text
Today['’ʼʹ]s date is YYYY[-/]MM[-/]DD
```

In `normalize` mode it becomes:

```text
Today's date is YYYY-MM-DD
```

The date value is preserved. Unrelated dates and unrelated apostrophes are not modified.

#### Timezone marker rule

Enable `timezone-marker` and set `SANITIZER_TIMEZONE` to an IANA timezone, such as `America/Los_Angeles`, when you want the proxy to rewrite Claude Code timezone markers before they reach the upstream API.

The rule targets narrow marker formats in JSON string values:

```text
<timezone>Asia/Shanghai</timezone>
Timezone: Asia/Shanghai
Time zone: Asia/Shanghai
```

In `normalize` mode they become:

```text
<timezone>America/Los_Angeles</timezone>
Timezone: America/Los_Angeles
Time zone: America/Los_Angeles
```

The timezone sanitizer requires both `SANITIZER_RULES=timezone-marker` and `SANITIZER_TIMEZONE`. It does not modify inline prose such as `the timezone: Asia/Shanghai example`.

When markers are observed, the proxy logs aggregate metadata only:

```text
marker observed path=/v1/messages mode=normalize date_lines=1 apostrophe_variants=1 slash_dates=1 timezone_markers=1 base_urls=1 replacements=3
```

It does not log full prompts or request bodies.

#### Base URL rule

Enable `base-url` when you want the proxy to rewrite local proxy base URLs inside JSON string values before forwarding requests upstream. This keeps prompt-visible configuration snippets from exposing the local proxy endpoint.

With the default local listener, the rule targets:

```text
http://127.0.0.1:8787
http://localhost:8787
```

In `normalize` mode they become the configured public base URL. By default that public URL is the real `UPSTREAM_BASE_URL`; set `SANITIZER_PUBLIC_BASE_URL` when you want a different prompt-visible value, such as the official Anthropic API URL while forwarding through a channel provider.

```bash
SANITIZER_RULES=base-url SANITIZER_PUBLIC_BASE_URL=https://api.anthropic.com uv run claude-code-local-proxy
```

The rule only scans decoded JSON string values. It does not change headers or non-JSON bodies.

### Egress guard

The egress guard is disabled by default. Enable it with `EGRESS_GUARD_ENABLED=true` when you want the proxy to check its current public IP before each upstream request and block unsafe routes before forwarding anything to the upstream API. It supports two modes.

#### `country-code` mode

This is the default mode: `EGRESS_GUARD_MODE=country-code`.

The guard checks the current public IP, looks up that IP's country code, and returns `451` without forwarding the Claude Code request upstream if the country code is blocked. By default, blocked country codes are `CN,HK,MO,TW`. Override them with `EGRESS_GUARD_BLOCKED_COUNTRY_CODES`.

The guard uses public IP and geolocation providers without sending prompts, request bodies, response bodies, or credentials to those providers. When the current public IP needs to be refreshed, it sends one request to identify it, then uses a local `public_ip -> country_code` cache to avoid repeated GeoIP lookups for the same IP.

#### `fixed-ip` mode

Set `EGRESS_GUARD_MODE=fixed-ip` when you want to allow only one known public egress IP. `EGRESS_GUARD_FIXED_IP` is required in this mode; with `EGRESS_GUARD_FIXED_IP=203.0.113.10`, only that public IP is allowed. If the proxy observes any other public IP, it returns `451` before forwarding the request upstream.

#### Runtime cache settings

- `EGRESS_GUARD_PUBLIC_IP_CACHE_SECONDS=0` keeps the current public IP cache disabled by default, so a VPN route change is detected before the next Claude Code request is forwarded. Keep that default for `fixed-ip` mode when immediate IP-change detection matters. Set it to a short value such as `5` or `30` only when you want to reduce public IP provider calls during request bursts and accept that route changes may be detected after that TTL expires.
- `EGRESS_GUARD_IP_REGION_CACHE_SECONDS=86400` reuses the country code for a previously seen public IP for one day. This only affects `country-code` mode's GeoIP lookup cache.

For safety, the default is fail-closed: if all location providers are unreachable, the proxy returns `503` instead of forwarding the request. Set `EGRESS_GUARD_FAIL_CLOSED=false` only if availability is more important than leak prevention.

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

To normalize timezone markers inside Claude Code request bodies, configure the proxy:

```bash
SANITIZER_RULES=timezone-marker SANITIZER_TIMEZONE=America/Los_Angeles uv run claude-code-local-proxy
```

> Note: `TZ` is a Claude Code process setting, not a proxy setting. To make Claude Code and most child processes observe the target timezone, start Claude Code with `TZ` in its own process environment:
>
> ```bash
> TZ=America/Los_Angeles ANTHROPIC_BASE_URL=http://127.0.0.1:8787 claude
> ```
>
> Some timezone checks inspect system-level commands instead of the process timezone. For example, `date` observes `TZ`, but `readlink /etc/localtime` and some `stat /etc/localtime` checks report the system timezone. If you need Claude Code's shell checks to consistently report the target timezone, put small command shims ahead of the normal `PATH` and limit that override to the Claude Code wrapper:
>
> ```bash
> claude-with-local-proxy() {
>   TZ=America/Los_Angeles \
>     ANTHROPIC_BASE_URL=http://127.0.0.1:8787 \
>     PATH="$HOME/.local/claude-code-shims:$PATH" \
>     claude "$@"
> }
> ```
>
> The shim directory can live anywhere in your shell setup. Override only the commands Claude Code commonly uses for timezone probes, such as `date`, `readlink`, and `stat`, and forward every unrelated invocation to the real system command. Use an absolute path or temporarily remove the shim directory from `PATH` before forwarding, so the shim does not recursively call itself. This covers ordinary command lookups; it does not intercept absolute paths such as `/bin/date` or programs that call OS timezone APIs directly.

Start the proxy in the background:

```bash
make run-bg
```

The background target writes the process ID to `logs/claude-code-local-proxy.pid` and application logs to `logs/claude-code-local-proxy.log`. Stop that background process with:

```bash
make stop-bg
```

On macOS, install a user LaunchAgent so the proxy starts automatically when you log in:

```bash
make install-autostart
```

The LaunchAgent runs the same proxy command from this project directory, writes application logs to `logs/claude-code-local-proxy.log`, and loads `.env` from the project root. Installing it stops the manual `make run-bg` process first so launchd can own the running service. Check or remove it with:

```bash
make status-autostart
make uninstall-autostart
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
