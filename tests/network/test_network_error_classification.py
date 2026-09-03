# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Failure taxonomy for outbound network errors (modules/common/network)."""

import socket
import ssl

import pytest

from mixar.modules.common.network import classify_network_error
from mixar.modules.common.network.constants import (
    FAILURE_DNS,
    FAILURE_PROXY,
    FAILURE_REFUSED,
    FAILURE_RESET,
    FAILURE_TIMEOUT,
    FAILURE_TLS_HANDSHAKE,
    FAILURE_TLS_VERIFY,
    FAILURE_UNKNOWN,
    FAILURE_UNREACHABLE,
    SUPPORT_CODES,
)

URL = "https://api.mixar.app/api/v1/auth/desktop/token"


# Shapes of the exceptions the bundled clients actually raise, reproduced
# without importing them so the classifier stays library-agnostic.
class SSLError(Exception):
    pass


class ProxyError(Exception):
    pass


class ConnectTimeout(Exception):
    pass


class ConnectError(Exception):  # httpx
    pass


class WebSocketProxyException(Exception):
    pass


def _chained(outer, inner):
    try:
        raise inner
    except BaseException as cause:
        try:
            raise outer from cause
        except BaseException as chained:
            return chained


@pytest.mark.parametrize(
    "exc, kind",
    [
        (
            SSLError(
                "HTTPSConnectionPool(host='api.mixar.app', port=443): Max retries exceeded "
                "(Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] "
                "certificate verify failed: unable to get local issuer certificate (_ssl.c:1000)')))"
            ),
            FAILURE_TLS_VERIFY,
        ),
        (ssl.SSLCertVerificationError("self signed certificate in certificate chain"), FAILURE_TLS_VERIFY),
        (_chained(ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"), ssl.SSLError()), FAILURE_TLS_VERIFY),
        (ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:1000)"), FAILURE_TLS_HANDSHAKE),
        (ssl.SSLEOFError("EOF occurred in violation of protocol"), FAILURE_TLS_HANDSHAKE),
        (ProxyError("HTTPSConnectionPool: Max retries exceeded (Caused by ProxyError('Cannot connect to proxy.'))"), FAILURE_PROXY),
        (ProxyError("Tunnel connection failed: 407 Proxy Authentication Required"), FAILURE_PROXY),
        (WebSocketProxyException("failed CONNECT via proxy status: 403"), FAILURE_PROXY),
        (socket.gaierror(8, "nodename nor servname provided, or not known"), FAILURE_DNS),
        (ConnectError("[Errno 11001] getaddrinfo failed"), FAILURE_DNS),
        (ConnectError("Name or service not known"), FAILURE_DNS),
        (ConnectTimeout("HTTPSConnectionPool(host='api.mixar.app', port=443): Max retries exceeded (Caused by ConnectTimeoutError(...))"), FAILURE_TIMEOUT),
        (TimeoutError("timed out"), FAILURE_TIMEOUT),
        (ConnectionRefusedError(61, "Connection refused"), FAILURE_REFUSED),
        (ConnectError("[WinError 10061] No connection could be made because the target machine actively refused it"), FAILURE_REFUSED),
        (ConnectionResetError(54, "Connection reset by peer"), FAILURE_RESET),
        (ConnectError("[WinError 10054] An existing connection was forcibly closed by the remote host"), FAILURE_RESET),
        (OSError(51, "Network is unreachable"), FAILURE_UNREACHABLE),
        (OSError(113, "No route to host"), FAILURE_UNREACHABLE),
        (RuntimeError("something odd"), FAILURE_UNKNOWN),
    ],
)
def test_kind_from_exception_shape(exc, kind):
    failure = classify_network_error(exc, url=URL, environ={})
    assert failure.kind == kind
    assert failure.support_code == SUPPORT_CODES[kind]
    assert failure.host == "api.mixar.app"


def test_root_cause_wins_over_wrapper():
    wrapped = _chained(ConnectError("All connection attempts failed"), ssl.SSLCertVerificationError("certificate verify failed"))
    failure = classify_network_error(wrapped, url=URL, environ={})
    assert failure.kind == FAILURE_TLS_VERIFY
    assert "SSLCertVerificationError" in failure.detail
    assert "ConnectError" in failure.detail


def test_urllib_reason_attribute_is_inspected():
    err = OSError("<urlopen error [Errno 8] nodename nor servname provided>")
    err.reason = socket.gaierror(8, "nodename nor servname provided")
    assert classify_network_error(err, url=URL, environ={}).kind == FAILURE_DNS


def test_user_text_is_short_and_carries_support_code():
    failure = classify_network_error(ssl.SSLCertVerificationError("certificate verify failed"), url=URL, environ={})
    assert failure.user_text.endswith("(NET-TLS)")
    assert len(failure.message) < 100
    assert "MIXAR_CA_BUNDLE" in failure.hint


def test_hint_names_the_host():
    failure = classify_network_error(TimeoutError("timed out"), url="https://ws.example.com/x", environ={})
    assert "ws.example.com" in failure.hint


@pytest.mark.parametrize("kind_exc", [ConnectionRefusedError(61, "Connection refused"), socket.gaierror(8, "nodename nor servname")])
def test_connect_stage_failures_attribute_to_proxy_when_one_is_configured(kind_exc):
    failure = classify_network_error(kind_exc, url=URL, environ={"HTTPS_PROXY": "http://u:secret@proxy.corp:3128"})
    assert failure.kind == FAILURE_PROXY
    assert "secret" not in failure.hint


def test_timeout_keeps_kind_but_mentions_proxy():
    failure = classify_network_error(TimeoutError("timed out"), url=URL, environ={"https_proxy": "http://u:secret@proxy.corp:3128"})
    assert failure.kind == FAILURE_TIMEOUT
    assert "proxy is configured" in failure.hint
    assert "u:***@proxy.corp:3128" in failure.hint
    assert "secret" not in failure.hint


def test_unknown_message_includes_short_root_text():
    failure = classify_network_error(RuntimeError("x" * 200), url=None, environ={})
    assert failure.kind == FAILURE_UNKNOWN
    assert len(failure.message) < 90
    assert failure.host == "the server"
