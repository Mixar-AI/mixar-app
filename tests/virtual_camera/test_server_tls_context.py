# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A TLS SERVER socket must not be wrapped by the client trust store.

Startup replaces `ssl.SSLContext` process-wide with truststore's subclass so
every outbound client verifies against the OS store. truststore verifies the
PEER's chain inside `wrap_socket` — meaningless for a listening socket, and
fatal when the handshake is deferred, because the wrapped socket has no
`_sslobj` yet:

    AttributeError: 'NoneType' object has no attribute 'get_unverified_chain'

which is what took the virtual-camera server down on Windows.
"""

from __future__ import annotations

import ast
import ssl
from pathlib import Path

import pytest

from mixar.modules.common.network.core import trust

ROOT = Path(__file__).resolve().parents[2]
SERVER = (
    ROOT / "src/scripts/mixar/modules/virtual_camera/core/server.py"
).read_text(encoding="utf-8")


class _FakeInjectedContext(ssl.SSLContext):
    """Stands in for truststore's subclass: verifies the peer on wrap."""

    def wrap_socket(self, sock, **kwargs):  # noqa: ANN001, ANN201
        raise AttributeError(
            "'NoneType' object has no attribute 'get_unverified_chain'"
        )


def test_the_helper_returns_cpythons_own_class(monkeypatch):
    monkeypatch.setattr(ssl, "SSLContext", _FakeInjectedContext)
    context = trust.server_ssl_context()
    assert type(context) is not _FakeInjectedContext
    assert type(context).__module__ == "ssl"
    assert type(context).__name__ == "SSLContext"


def test_the_injected_class_would_have_failed(monkeypatch):
    """The bug, reproduced: the injected class raises on a server wrap."""
    monkeypatch.setattr(ssl, "SSLContext", _FakeInjectedContext)
    with pytest.raises(AttributeError, match="get_unverified_chain"):
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).wrap_socket(
            object(), server_side=True, do_handshake_on_connect=False
        )


def test_the_helper_survives_a_subclass_that_is_not_truststores(monkeypatch):
    """The MRO walk is the mechanism, not a name check on truststore."""

    class _Other(ssl.SSLContext):
        pass

    monkeypatch.setattr(ssl, "SSLContext", _Other)
    assert type(trust.server_ssl_context()).__name__ == "SSLContext"
    assert type(trust.server_ssl_context()) is not _Other


def test_the_server_uses_the_helper_and_never_the_module_attribute():
    tree = ast.parse(SERVER)
    start = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "start"
    )
    body = ast.unparse(start)
    assert "server_ssl_context()" in body
    # `ssl.SSLContext(...)` here is the injected class — the whole bug.
    assert "ssl.SSLContext(" not in body


def test_tls_failure_degrades_instead_of_killing_the_server():
    """Without TLS iOS withholds DeviceOrientation and the app is
    joystick-only, which is worth having. Anything narrower than `Exception`
    lets a new failure mode take the whole server down — which is exactly
    what the AttributeError from the trust store did."""
    tree = ast.parse(SERVER)
    start = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "start"
    )
    handlers = [
        handler
        for node in ast.walk(start)
        if isinstance(node, ast.Try)
        for handler in node.handlers
        if "wrap_socket" in ast.unparse(node)
    ]
    assert handlers, "the TLS block lost its try/except"
    assert any(
        getattr(handler.type, "id", None) == "Exception" for handler in handlers
    )
    body = ast.unparse(start)
    assert "tls_ok = False" in body
    # The reason goes to the log; the panel already states the consequence.
    assert "logger.warning" in body


def test_the_pairing_card_says_why_the_gyro_is_missing():
    """A server silently on HTTP looks like a broken phone gyro. One
    statement of it, beside the QR, not a second message in the server."""
    card = (
        ROOT
        / "src/source/blender/editors/space_view3d/view3d_director_cinema_phone.cc"
    ).read_text(encoding="utf-8")
    assert "mixar_virtual_camera_tls" in card
    assert "No secure link: joysticks only, no phone motion" in card
    # And the server states it ONCE: it records the flag the card reads and
    # logs the reason, rather than composing a second message of its own.
    tree = ast.parse(SERVER)
    start = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "start"
    )
    tls_block = next(
        ast.unparse(node)
        for node in ast.walk(start)
        if isinstance(node, ast.Try) and "wrap_socket" in ast.unparse(node)
    )
    assert "last_error" not in tls_block
