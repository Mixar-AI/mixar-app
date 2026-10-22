# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Relay replies survive security software that rewrites their HTTP framing.

A Windows user's filter turned the relay's HTTP/1.0 Content-Length reply into
"transfer-encoding: chunked" over an unchunked JSON body, so http.client raised
IncompleteRead on every tools/list. Both local clients read such a reply anyway.
"""

import importlib.util
import json
from pathlib import Path
import socket
import threading

import pytest

from mixar.modules.mcp_bridge.core import connector


SCRIPT = Path(__file__).resolve().parents[2] / "src/scripts/mixar/mcp.py"
SPEC = importlib.util.spec_from_file_location("mixar_launcher_framing_test", SCRIPT.resolve())
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)

BODY = json.dumps({"jsonrpc": "2.0", "id": "init", "result": {"protocolVersion": "2025-11-25"}}).encode()
REWRITTEN = (b"HTTP/1.0 200 OK\r\ntransfer-encoding: chunked\r\nServer: MixarMCP Python/3.13.13\r\n"
             b"Content-Type: application/json\r\nCache-Control: no-store\r\n\r\n")


def chunked(body):
    return b"%x\r\n%s\r\n0\r\n\r\n" % (len(body), body)


def serve(reply):
    """A loopback server that answers one request with these exact bytes, then closes."""
    listener = socket.create_server(("127.0.0.1", 0))

    def run():
        conn, _ = listener.accept()
        with conn:
            conn.recv(65536)
            conn.sendall(reply)
            conn.shutdown(socket.SHUT_WR)
            while conn.recv(65536):  # Drain the request so close is not a reset.
                pass
        listener.close()
    threading.Thread(target=run, daemon=True).start()
    return {"port": listener.getsockname()[1], "token": "t" * 43}


@pytest.mark.parametrize("body", [BODY, chunked(BODY)], ids=["unchunked-body", "real-chunks"])
def test_connector_reads_a_reply_marked_chunked(body):
    assert connector.request(serve(REWRITTEN + body), "POST", "/mcp", {"jsonrpc": "2.0"}) == json.loads(BODY)


@pytest.mark.parametrize("body", [BODY, chunked(BODY)], ids=["unchunked-body", "real-chunks"])
def test_launcher_reads_a_reply_marked_chunked(body):
    status, data = launcher.local_request(serve(REWRITTEN + body), "POST", "/mcp", b"{}")
    assert (status, data) == (200, BODY)


def test_truncated_chunks_are_an_error_not_a_partial_body():
    with pytest.raises(ValueError):
        connector.request(serve(REWRITTEN + b"ff\r\n" + BODY), "POST", "/mcp", {"jsonrpc": "2.0"})
