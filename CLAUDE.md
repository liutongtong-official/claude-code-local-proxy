# CLAUDE.md

Python 3.13 CLI app, packaged with `uv_build`, using stdlib HTTP proxying plus `python-dotenv` at runtime.

## Constraints

- Keep runtime defaults in `src/claude_code_local_proxy/config.py`; `.env.example` is documentation, not a source of truth.
- Do not log full prompts, request bodies, response bodies, or credentials. Marker logs may include aggregate counts only.
- Preserve streaming behavior in `proxy.py`: upstream responses should be relayed incrementally, not buffered into memory before responding.
- Keep `sanitize_json_value()` field-agnostic: recurse through decoded JSON values instead of depending on Anthropic/OpenAI-specific field names.
- Forward non-JSON bodies and invalid JSON unchanged.
- In `observe` mode, collect stats but forward the original body unchanged.

## Sanitizer rules

- Add string-level sanitizer rules under `src/claude_code_local_proxy/sanitizer_rules/`.
- Implement `SanitizerRule` from `sanitizer_rules/base.py`: expose `name` and `apply(text, mode) -> tuple[str, SanitizeStats]`.
- Register built-in rules in `DEFAULT_RULES` in `sanitizer.py`; rule order is the execution order.
- Keep each rule narrow. A rule should not know Anthropic/OpenAI message field names; JSON traversal belongs in `sanitize_json_value()`.
- Add direct rule tests and a pipeline-level test when registration or ordering matters.

## Recipes

- Use `make fmt` before final checks.
- Use `make check` as the full local gate after code changes.

See @README.md for user-facing usage and configuration.
