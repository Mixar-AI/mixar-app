# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A local server's context window, read the way each server reports it.

Prod MIXAR-BACKEND-1XF: an Ollama server at 8,192 tokens cut every agent reply
for length before it answered. The AI Provider recap warns from this number.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.local_models.core import context_probe  # noqa: E402


def _server(routes: dict):
    """A localhost server answering ``routes[(method, path)]`` with JSON."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            seen.append((method, self.path, body, self.headers.get("Authorization")))
            payload = routes.get((method, self.path))
            self.send_response(200 if payload is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload if payload is not None else {"error": "nope"}).encode())

        def do_GET(self):  # noqa: N802
            self._answer("GET")

        def do_POST(self):  # noqa: N802
            self._answer("POST")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", seen


@pytest.mark.parametrize("routes,expected", [
    ({("GET", "/props"): {"default_generation_settings": {"n_ctx": 16384}}}, 16384),
    ({("GET", "/api/v0/models/qwen3%3A4b"): {"loaded_context_length": 4096}}, 4096),
    ({("GET", "/api/ps"): {"models": [{"name": "qwen3:4b", "context_length": 8192}]}}, 8192),
    ({("GET", "/api/ps"): {"models": []},
      ("POST", "/api/show"): {"parameters": "temperature 0.7\nnum_ctx 32768\n"}}, 32768),
    ({("GET", "/v1/models"): {"data": [{"id": "qwen3:4b", "max_model_len": 40960}]}}, 40960),
    ({("GET", "/v1/models"): {"data": [{"id": "qwen3:4b"}]}}, None),
])
def test_each_server_kind_reports_its_window(routes, expected):
    server, base, _seen = _server(routes)
    try:
        assert context_probe.context_window(f"{base}/v1", "qwen3:4b") == expected
    finally:
        server.shutdown()


def test_ollama_latest_tag_matches_and_the_key_is_sent():
    server, base, seen = _server({("GET", "/api/ps"): {"models": [
        {"name": "gemma4:e4b-latest", "context_length": 1},
        {"name": "gemma4:e4b:latest", "context_length": 8192}]}})
    try:
        assert context_probe.context_window(base, "gemma4:e4b", api_key="tok") == 8192
        assert all(auth == "Bearer tok" for *_rest, auth in seen)
    finally:
        server.shutdown()


def test_an_unreachable_server_is_unknown_not_an_error():
    assert context_probe.context_window("http://127.0.0.1:9/v1", "m") is None
    assert context_probe.context_window("", "m") is None
