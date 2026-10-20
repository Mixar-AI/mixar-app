# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""A server's ``Retry-After`` never sets a sleep in `HTTPClient`.

urllib3's `Retry` honours the header by default: a 429 carrying it was
retried (429 is not even in ``status_forcelist``) after sleeping the full
value. A BYOK save answered 429 + ``Retry-After: 13996`` slept ~3.9 h and the
AI Provider Settings dialog stayed on "Validating with your provider…".

These drive the REAL session (adapter + `Retry`) against a local HTTP server.
Each request runs on a daemon thread joined with a short deadline, so a
regression fails fast instead of sleeping out the header.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import byok_client
from mixar.modules.common.api import client as client_module
from mixar.modules.common.api import retry_policy
from mixar.modules.common.api.exceptions import HTTPClientError, RateLimitError

DEADLINE_S = 5.0
CODEX_LIMIT_MSG = ("Your ChatGPT plan's Codex usage limit has been reached; it resets "
                   "in about 3 hours 53 minutes. Wait for it to reset or upgrade your "
                   "ChatGPT plan, then save again.")


class _Server:
    """Answers each request with the next scripted (status, headers, body)."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                outer.requests.append((self.command, self.path))
                index = min(len(outer.requests), len(outer.script)) - 1
                status, headers, body = outer.script[index]
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_PUT = do_POST = _answer

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def serve(monkeypatch):
    monkeypatch.setattr(client_module, "get_access_token", lambda: None)
    servers = []

    def _serve(*script):
        server = _Server(script)
        servers.append(server)
        return server

    yield _serve
    for server in servers:
        server.close()


def _client(server, **kwargs):
    client = client_module.HTTPClient(base_url=server.url, **kwargs)
    client._session.trust_env = False  # never route 127.0.0.1 through a proxy
    return client


def _call(fn):
    """Run ``fn`` on a daemon thread; (result, error, elapsed) within DEADLINE_S."""
    outcome = {}

    def _run():
        try:
            outcome["result"] = fn()
        except Exception as e:  # noqa: BLE001 — returned to the test
            outcome["error"] = e

    started = time.monotonic()
    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(DEADLINE_S)
    assert not worker.is_alive(), "request still sleeping — Retry-After was honoured"
    return outcome.get("result"), outcome.get("error"), time.monotonic() - started


def test_a_429_with_retry_after_returns_at_once_after_one_request(serve):
    server = serve((429, {"Retry-After": "30"}, {"status": "failure", "message": "slow"}))

    resp, error, elapsed = _call(
        lambda: _client(server).get("api/v1/anything", raise_for_status=False))

    assert error is None
    assert resp.status_code == 429
    assert elapsed < 1.0
    assert len(server.requests) == 1


def test_a_byok_save_429_reaches_the_dialog_with_the_server_message(serve):
    """The incident: PUT /agent/byok answered 429 + a 3.9 h Retry-After."""
    server = serve((429, {"Retry-After": "13996"},
                    {"detail": {"status": "failure", "message": CODEX_LIMIT_MSG}}))

    _, error, elapsed = _call(lambda: _client(server).put(
        "api/v1/agent/byok", json={"provider": "codex", "model": "gpt-5"}))

    assert isinstance(error, RateLimitError)
    assert error.status_code == 429
    assert error.retry_after == 13996.0
    assert elapsed < 1.0
    assert server.requests == [("PUT", "/api/v1/agent/byok")]
    # The BYOK worker's translation is what the dialog shows as byok_last_error.
    assert byok_client._translate_exception(error) == (False, None, CODEX_LIMIT_MSG)


def test_the_rate_limiter_s_message_wins_over_its_string_detail(serve):
    server = serve((429, {"Retry-After": "60"}, {
        "status": "failure", "message": "Too many requests. Please try again later.",
        "detail": "10 per 1 minute", "retry_after": 60}))

    _, error, _ = _call(lambda: _client(server).post("api/v1/anything", json={}))

    assert isinstance(error, RateLimitError)
    assert error.message == "Too many requests. Please try again later."
    assert error.retry_after == 60.0
    assert len(server.requests) == 1


def test_an_http_date_retry_after_still_maps_to_a_rate_limit_error(serve):
    """``float()`` on an HTTP-date used to raise inside the mapping, so the
    429 surfaced as a status-less error that reads as a network failure."""
    server = serve((429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
                    {"status": "failure", "message": "slow down"}))

    _, error, _ = _call(lambda: _client(server).get("api/v1/anything"))

    assert isinstance(error, RateLimitError)
    assert error.status_code == 429
    assert error.message == "slow down"
    assert error.retry_after is None


def test_a_no_retry_client_returns_a_429_at_once_too(serve):
    server = serve((429, {"Retry-After": "30"}, {"status": "failure", "message": "slow"}))

    resp, error, elapsed = _call(lambda: _client(server, retry_count=0).post(
        "api/v1/anything", json={}, raise_for_status=False))

    assert error is None and resp.status_code == 429
    assert elapsed < 1.0
    assert len(server.requests) == 1


def test_a_503_is_retried_on_backoff_and_its_retry_after_is_ignored(serve):
    """503 stays retryable (deploys, restarts), but only on the bounded
    exponential backoff — never the header's 30 s per attempt."""
    server = serve((503, {"Retry-After": "30"}, {"status": "failure", "message": "down"}))

    _, error, elapsed = _call(lambda: _client(server, retry_count=2, retry_delay=0.01).get(
        "api/v1/anything", raise_for_status=False))

    assert isinstance(error, HTTPClientError)  # retries exhausted
    assert len(server.requests) == 3  # the first try + 2 retries
    assert elapsed < 2.0


def test_a_transient_503_recovers_on_the_retry(serve):
    server = serve((503, {"Retry-After": "30"}, {"status": "failure", "message": "down"}),
                   (200, {}, {"status": "success", "data": {"ok": True}}))

    resp, error, elapsed = _call(lambda: _client(server, retry_delay=0.01).get(
        "api/v1/anything"))

    assert error is None and resp.status_code == 200
    assert len(server.requests) == 2
    assert elapsed < 2.0


@pytest.mark.parametrize("retry_count", [0, 3])
def test_no_built_retry_honours_retry_after(retry_count):
    retry = retry_policy.build_retry(retry_count, 1.0)

    assert retry.respect_retry_after_header is False
    assert retry.is_retry("PUT", 429, has_retry_after=True) is False
    assert retry.is_retry("POST", 413, has_retry_after=True) is False


@pytest.mark.parametrize("headers, body, expected", [
    ({"Retry-After": "30"}, None, 30.0),
    ({"Retry-After": " 7 "}, None, 7.0),
    ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None, None),
    ({}, {"retry_after": 60}, 60.0),
    ({}, {"detail": {"retry_after": 12}}, 12.0),
    ({}, {"data": {"retry_after_s": 4.5}}, 4.5),
    ({}, {"retry_after": -1}, None),
    ({}, {"retry_after": True}, None),
    ({}, "not json", None),
])
def test_retry_after_seconds(headers, body, expected):
    assert retry_policy.retry_after_seconds(headers, body) == expected
