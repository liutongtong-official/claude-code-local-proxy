"""HTTP reverse proxy for Claude Code requests."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

from claude_code_local_proxy.egress_guard import (
    EgressChecker,
    EgressGuardBlocked,
    EgressGuardIpChanged,
    EgressGuardUnavailable,
)
from claude_code_local_proxy.sanitizer import (
    Mode,
    SanitizeStats,
    default_rules,
    sanitize_json_value,
)

LOGGER = logging.getLogger(__name__)
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_MAX_REQUEST_BODY_BYTES = 128 * 1024 * 1024
_RESPONSE_CHUNK_BYTES = 8 * 1024


@dataclass(frozen=True)
class ProxyConfig:
    upstream_base_url: str
    timeout_seconds: float
    mode: Mode = "normalize"
    sanitizer_rules: tuple[str, ...] = ()
    sanitizer_timezone: str | None = None
    sanitizer_public_base_url: str | None = None
    sanitizer_local_base_urls: tuple[str, ...] = ()
    egress_guard: EgressChecker | None = None


class RequestBodyError(Exception):
    """Raised when the inbound request body cannot be safely forwarded."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class SanitizingProxyHandler(BaseHTTPRequestHandler):
    """Forward requests to the configured upstream after optional JSON sanitizing."""

    config: ClassVar[ProxyConfig]
    protocol_version = "HTTP/1.1"
    server_version = "ClaudeCodeLocalProxy/0.1"

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy()

    def do_GET(self) -> None:  # noqa: N802
        self._proxy()

    def do_HEAD(self) -> None:  # noqa: N802
        self._proxy()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._proxy()

    def do_PATCH(self) -> None:  # noqa: N802
        self._proxy()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy()

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy()

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.info("%s - %s %s", self.address_string(), self.command, self._safe_log_path())

    def _proxy(self) -> None:
        if not self._egress_allowed():
            return

        try:
            body = self._read_body()
        except RequestBodyError as exc:
            self._send_json_error(exc.status, exc.message)
            return

        outbound_body, stats = self._maybe_sanitize_body(body)
        if stats.observed:
            LOGGER.info(
                "marker observed path=%s mode=%s date_lines=%d apostrophe_variants=%d "
                "slash_dates=%d timezone_markers=%d base_urls=%d replacements=%d",
                self._safe_log_path(),
                self.config.mode,
                stats.date_lines,
                stats.apostrophe_variants,
                stats.slash_dates,
                stats.timezone_markers,
                stats.base_urls,
                stats.replacements,
            )
        request = urllib.request.Request(
            self._target_url(),
            data=outbound_body if self.command not in {"GET", "HEAD"} else None,
            headers=self._forward_headers(outbound_body),
            method=self.command,
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.config.timeout_seconds)
        except urllib.error.HTTPError as exc:
            with exc:
                self._relay_response_safely(exc.code, exc.headers, exc)
            return
        except Exception as exc:  # pragma: no cover - exercised as runtime safety net
            LOGGER.exception("upstream request failed before response started")
            self._send_json_error(HTTPStatus.BAD_GATEWAY, str(exc))
            return

        with response:
            self._relay_response_safely(response.status, response.headers, response)

    def _egress_allowed(self) -> bool:
        if self.config.egress_guard is None:
            return True
        try:
            location = self.config.egress_guard.ensure_allowed()
        except EgressGuardBlocked as exc:
            location = exc.location
            LOGGER.warning(
                "egress blocked path=%s country_code=%s provider=%s ip=%s",
                self._safe_log_path(),
                location.country_code,
                location.provider,
                location.ip or "?",
            )
            self.close_connection = True
            self._send_json_error(HTTPStatus.UNAVAILABLE_FOR_LEGAL_REASONS, str(exc))
            return False
        except EgressGuardIpChanged as exc:
            LOGGER.warning(
                "egress fixed IP changed path=%s expected_ip=%s current_ip=%s",
                self._safe_log_path(),
                exc.expected_ip,
                exc.current_ip,
            )
            self.close_connection = True
            self._send_json_error(HTTPStatus.UNAVAILABLE_FOR_LEGAL_REASONS, str(exc))
            return False
        except EgressGuardUnavailable as exc:
            LOGGER.warning(
                "egress location unavailable path=%s provider_errors=%s",
                self._safe_log_path(),
                "; ".join(exc.provider_errors) or "none",
            )
            self.close_connection = True
            self._send_json_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
            return False
        if location is None:
            return True
        if location.provider == "fixed-ip":
            LOGGER.info(
                "egress fixed IP allowed path=%s expected_ip=%s current_ip=%s",
                self._safe_log_path(),
                location.ip or "?",
                location.ip or "?",
            )
        else:
            LOGGER.info(
                "egress allowed path=%s country_code=%s provider=%s ip=%s",
                self._safe_log_path(),
                location.country_code,
                location.provider,
                location.ip or "?",
            )
        return True

    def _read_body(self) -> bytes:
        if self.headers.get("transfer-encoding", "").lower() == "chunked":
            raise RequestBodyError(
                HTTPStatus.NOT_IMPLEMENTED,
                "chunked request bodies are not supported by this local proxy",
            )
        content_length = self.headers.get("content-length")
        if not content_length:
            return b""
        try:
            length = int(content_length)
        except ValueError as exc:
            raise RequestBodyError(HTTPStatus.BAD_REQUEST, "invalid Content-Length") from exc
        if length < 0:
            raise RequestBodyError(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
        if length > _MAX_REQUEST_BODY_BYTES:
            raise RequestBodyError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
        body = self.rfile.read(length)
        if len(body) < length:
            raise RequestBodyError(HTTPStatus.BAD_REQUEST, "incomplete request body")
        return body

    def _maybe_sanitize_body(self, body: bytes) -> tuple[bytes, SanitizeStats]:
        if not body or self.config.mode == "off" or not self._is_json_request():
            return body, SanitizeStats()
        try:
            decoded = json.loads(body)
        except ValueError:
            return body, SanitizeStats()
        sanitized, stats = sanitize_json_value(
            decoded,
            self.config.mode,
            default_rules(
                self.config.sanitizer_rules,
                self.config.sanitizer_timezone,
                self.config.sanitizer_public_base_url,
                self.config.sanitizer_local_base_urls,
            ),
        )
        if self.config.mode != "normalize" or not stats.changed:
            return body, stats
        return json.dumps(sanitized, ensure_ascii=False, separators=(",", ":")).encode(), stats

    def _is_json_request(self) -> bool:
        return self.headers.get_content_type() == "application/json"

    def _target_url(self) -> str:
        base = self.config.upstream_base_url.rstrip("/")
        parsed_path = urllib.parse.urlsplit(self.path)
        path = parsed_path.path if parsed_path.path.startswith("/") else f"/{parsed_path.path}"
        query = f"?{parsed_path.query}" if parsed_path.query else ""
        return f"{base}{path}{query}"

    def _safe_log_path(self) -> str:
        return urllib.parse.urlsplit(self.path).path or "/"

    def _forward_headers(self, body: bytes) -> dict[str, str]:
        headers: dict[str, str] = {}
        upstream_host = urllib.parse.urlsplit(self.config.upstream_base_url).netloc
        hop_by_hop = _hop_by_hop_header_names(self.headers)
        for key, value in self.headers.items():
            lower = key.lower()
            if lower in hop_by_hop or lower in {"host", "content-length"}:
                continue
            headers[key] = value
        headers["Host"] = upstream_host
        if self.command not in {"GET", "HEAD"}:
            headers["Content-Length"] = str(len(body))
        return headers

    def _relay_response_safely(self, status: int, headers: object, source: object) -> None:
        try:
            self._relay_upstream_response(status, headers, source)
        except Exception:
            LOGGER.warning("response relay failed after response started", exc_info=True)
            self.close_connection = True

    def _relay_upstream_response(self, status: int, headers: object, source: object) -> None:
        self.send_response(status)
        has_content_length = False
        hop_by_hop = _hop_by_hop_header_names(headers)
        for key, value in headers.items():  # type: ignore[attr-defined]
            lower = key.lower()
            if lower in hop_by_hop or lower in {"server", "date"}:
                continue
            if lower == "content-length":
                has_content_length = True
            self.send_header(key, value)
        if not has_content_length:
            self.close_connection = True
        self.end_headers()
        if self.command == "HEAD":
            return
        for chunk in _iter_response_chunks(source):
            self.wfile.write(chunk)
            self.wfile.flush()

    def _send_json_error(self, status: HTTPStatus, message: str) -> None:
        payload = json.dumps({"error": message}).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)


def _hop_by_hop_header_names(headers: Any) -> set[str]:
    names = set(_HOP_BY_HOP_HEADERS)
    connection = headers.get("Connection") or headers.get("connection")
    if isinstance(connection, str):
        names.update(part.strip().lower() for part in connection.split(",") if part.strip())
    return names


def _iter_response_chunks(source: Any) -> Iterator[bytes]:
    reader = getattr(source, "read1", None)
    if reader is None:
        reader = source.read
    while chunk := reader(_RESPONSE_CHUNK_BYTES):
        yield chunk


def run_server(host: str, port: int, config: ProxyConfig) -> None:
    SanitizingProxyHandler.config = config
    with ThreadingHTTPServer((host, port), SanitizingProxyHandler) as server:
        LOGGER.warning(
            "listening on http://%s:%d -> %s mode=%s",
            host,
            port,
            config.upstream_base_url,
            config.mode,
        )
        server.serve_forever()
