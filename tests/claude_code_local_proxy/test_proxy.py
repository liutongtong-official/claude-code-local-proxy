"""End-to-end tests for the local reverse proxy."""

from __future__ import annotations

import http.client
import io
import json
import threading
import urllib.error
import urllib.request
from email.message import Message
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import ClassVar

import pytest

from claude_code_local_proxy.egress_guard import (
    EgressGuardBlocked,
    EgressGuardIpChanged,
    EgressGuardUnavailable,
    EgressLocation,
)
from claude_code_local_proxy.proxy import (
    ProxyConfig,
    RequestBodyError,
    SanitizingProxyHandler,
)


class CaptureHandler(BaseHTTPRequestHandler):
    captured_body: ClassVar[bytes] = b""
    request_count: ClassVar[int] = 0

    def do_POST(self) -> None:  # noqa: N802
        type(self).request_count += 1
        content_length = int(self.headers["content-length"])
        type(self).captured_body = self.rfile.read(content_length)
        response = b'{"ok":true}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        return


class BlockingGuard:
    def ensure_allowed(self) -> None:
        raise EgressGuardBlocked(
            EgressLocation(provider="test", country_code="CN", ip="203.0.113.10")
        )


class UnavailableGuard:
    def ensure_allowed(self) -> None:
        raise EgressGuardUnavailable(("test: unavailable",))


class ChangedIpGuard:
    def ensure_allowed(self) -> None:
        raise EgressGuardIpChanged(expected_ip="198.51.100.10", current_ip="203.0.113.10")


def test_proxy_normalizes_json_body_before_forwarding() -> None:
    upstream = HTTPServer(("127.0.0.1", 0), CaptureHandler)
    CaptureHandler.request_count = 0
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    upstream_url = f"http://127.0.0.1:{upstream.server_port}"

    SanitizingProxyHandler.config = ProxyConfig(
        upstream_base_url=upstream_url, timeout_seconds=5, mode="normalize"
    )
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), SanitizingProxyHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()

    try:
        payload = json.dumps(
            {"system": "Todayʹs date is 2026/06/30."},
            ensure_ascii=False,
        ).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/v1/messages",
            data=payload,
            headers={"content-type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.read() == b'{"ok":true}'

        assert json.loads(CaptureHandler.captured_body) == {"system": "Today's date is 2026-06-30."}
        assert CaptureHandler.request_count == 1
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()


def test_proxy_rejects_chunked_request_body() -> None:
    SanitizingProxyHandler.config = ProxyConfig(
        upstream_base_url="http://127.0.0.1:1",
        timeout_seconds=5,
        mode="normalize",
    )
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), SanitizingProxyHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    connection: http.client.HTTPConnection | None = None

    try:
        connection = http.client.HTTPConnection("127.0.0.1", proxy.server_address[1], timeout=5)
        connection.putrequest("POST", "/v1/messages")
        connection.putheader("Transfer-Encoding", "chunked")
        connection.endheaders()

        response = connection.getresponse()
        assert response.status == HTTPStatus.NOT_IMPLEMENTED
        assert b"chunked request bodies" in response.read()
    finally:
        if connection is not None:
            connection.close()
        proxy.shutdown()
        proxy.server_close()


def test_proxy_blocks_request_before_forwarding_when_egress_is_blocked() -> None:
    upstream = HTTPServer(("127.0.0.1", 0), CaptureHandler)
    CaptureHandler.request_count = 0
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    upstream_url = f"http://127.0.0.1:{upstream.server_port}"

    SanitizingProxyHandler.config = ProxyConfig(
        upstream_base_url=upstream_url,
        timeout_seconds=5,
        mode="normalize",
        egress_guard=BlockingGuard(),
    )
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), SanitizingProxyHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()

    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/v1/messages",
            data=b'{"prompt":"secret"}',
            headers={"content-type": "application/json"},
            method="POST",
        )

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request, timeout=5)

        assert exc_info.value.code == HTTPStatus.UNAVAILABLE_FOR_LEGAL_REASONS
        assert b"blocked region" in exc_info.value.read()
        assert CaptureHandler.request_count == 0
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()


def test_proxy_returns_503_before_forwarding_when_egress_is_unavailable() -> None:
    upstream = HTTPServer(("127.0.0.1", 0), CaptureHandler)
    CaptureHandler.request_count = 0
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    upstream_url = f"http://127.0.0.1:{upstream.server_port}"

    SanitizingProxyHandler.config = ProxyConfig(
        upstream_base_url=upstream_url,
        timeout_seconds=5,
        mode="normalize",
        egress_guard=UnavailableGuard(),
    )
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), SanitizingProxyHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()

    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/v1/messages",
            data=b'{"prompt":"secret"}',
            headers={"content-type": "application/json"},
            method="POST",
        )

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request, timeout=5)

        assert exc_info.value.code == HTTPStatus.SERVICE_UNAVAILABLE
        assert b"fail-closed policy" in exc_info.value.read()
        assert CaptureHandler.request_count == 0
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()


def test_proxy_blocks_request_before_forwarding_when_fixed_egress_ip_changes() -> None:
    upstream = HTTPServer(("127.0.0.1", 0), CaptureHandler)
    CaptureHandler.request_count = 0
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    upstream_url = f"http://127.0.0.1:{upstream.server_port}"

    SanitizingProxyHandler.config = ProxyConfig(
        upstream_base_url=upstream_url,
        timeout_seconds=5,
        mode="normalize",
        egress_guard=ChangedIpGuard(),
    )
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), SanitizingProxyHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()

    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/v1/messages",
            data=b'{"prompt":"secret"}',
            headers={"content-type": "application/json"},
            method="POST",
        )

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request, timeout=5)

        assert exc_info.value.code == HTTPStatus.UNAVAILABLE_FOR_LEGAL_REASONS
        assert b"expected_ip=198.51.100.10" in exc_info.value.read()
        assert CaptureHandler.request_count == 0
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()


def test_proxy_strips_query_from_marker_logs(caplog: pytest.LogCaptureFixture) -> None:
    upstream = HTTPServer(("127.0.0.1", 0), CaptureHandler)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    upstream_url = f"http://127.0.0.1:{upstream.server_port}"

    SanitizingProxyHandler.config = ProxyConfig(
        upstream_base_url=upstream_url,
        timeout_seconds=5,
        mode="observe",
    )
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), SanitizingProxyHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()

    try:
        payload = json.dumps({"system": "Todayʹs date is 2026/06/30."}, ensure_ascii=False).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/v1/messages?api_key=secret",
            data=payload,
            headers={"content-type": "application/json"},
            method="POST",
        )

        with (
            caplog.at_level("INFO", logger="claude_code_local_proxy.proxy"),
            urllib.request.urlopen(request, timeout=5) as response,
        ):
            assert response.read() == b'{"ok":true}'

        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert "path=/v1/messages" in messages
        assert "api_key=secret" not in messages
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()


def test_proxy_forwards_invalid_utf8_json_body_unchanged() -> None:
    upstream = HTTPServer(("127.0.0.1", 0), CaptureHandler)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    upstream_url = f"http://127.0.0.1:{upstream.server_port}"

    SanitizingProxyHandler.config = ProxyConfig(
        upstream_base_url=upstream_url,
        timeout_seconds=5,
        mode="normalize",
    )
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), SanitizingProxyHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()

    try:
        payload = b"{\xff}"
        request = urllib.request.Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/v1/messages",
            data=payload,
            headers={"content-type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.read() == b'{"ok":true}'

        assert CaptureHandler.captured_body == payload
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()


def test_read_body_rejects_incomplete_content_length() -> None:
    handler = object.__new__(SanitizingProxyHandler)
    headers = Message()
    headers["Content-Length"] = "10"
    handler.headers = headers
    handler.rfile = io.BytesIO(b"short")

    with pytest.raises(RequestBodyError) as exc_info:
        handler._read_body()

    assert exc_info.value.status == HTTPStatus.BAD_REQUEST
    assert exc_info.value.message == "incomplete request body"


def test_proxy_does_not_duplicate_server_and_date_headers() -> None:
    upstream = HTTPServer(("127.0.0.1", 0), CaptureHandler)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    upstream_url = f"http://127.0.0.1:{upstream.server_port}"

    SanitizingProxyHandler.config = ProxyConfig(
        upstream_base_url=upstream_url,
        timeout_seconds=5,
        mode="normalize",
    )
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), SanitizingProxyHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()

    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/v1/messages",
            data=b"{}",
            headers={"content-type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.read() == b'{"ok":true}'
            assert len(response.headers.get_all("Server", [])) == 1
            assert len(response.headers.get_all("Date", [])) == 1
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()
