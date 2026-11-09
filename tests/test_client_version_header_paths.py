# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every outbound request path carries ``X-Client-Version``.

A backend blue/green deploy routes a client version to the fleet built for
it by this header (ALB lane rule). A path that omits it lands on the other
fleet: the WebSocket would stream from one backend while REST calls hit
another, and a sign-in could reach a backend that does not know the build.
``HTTPClient`` stamps every REST call; these are the hand-rolled paths.
Source-level pins (``bpy`` is a mock here), one assertion per path.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "src/scripts/mixar/modules"


def _src(rel: str) -> str:
    return (MODULES / rel).read_text(encoding="utf-8")


def test_agent_websocket_upgrade_sends_the_version():
    src = _src("space_mixie_chat/core/socket_connection.py")
    assert "client_version_headers" in src
    # The header list is built before create_connection and extended with it.
    assert src.index("client_version_headers()") < src.index("websocket.create_connection(")


def test_dictation_websocket_upgrade_sends_the_version():
    src = _src("space_mixie_chat/core/voice_input/transport.py")
    assert src.count("header=self._upgrade_headers()") == 2
    assert "client_version_headers" in src
    assert "header={'Authorization'" not in src


def test_auth_module_raw_requests_use_the_shared_headers():
    """login, refresh, me, handoff (auth.py), the SSO token exchange and both
    guest calls build their headers through auth_headers()."""
    helper = _src("auth/core/request_headers.py")
    assert "client_version_headers" in helper
    assert _src("auth/core/auth.py").count("auth_headers(") == 4
    assert _src("auth/core/sso.py").count("auth_headers(") == 1
    assert _src("auth/core/guest.py").count("auth_headers(") == 2
    for rel in ("auth/core/auth.py", "auth/core/sso.py", "auth/core/guest.py"):
        src = _src(rel)
        assert '"accept": "application/json"' not in src and "'accept': 'application/json'" not in src, rel


def test_native_desktop_token_exchange_sends_the_version():
    src = (ROOT / "src/source/creator/creator_startup.cc").read_text(encoding="utf-8")
    # Both transport branches: WinHTTP (Windows) and libcurl (macOS/Linux).
    assert src.count("X-Client-Version") >= 2


def test_the_client_version_report_sends_the_version(monkeypatch):
    """PUT /notifications/me/client-version builds its own headers."""
    from mixar.modules.common.api import client_version
    from mixar.modules.common.notifications import rest_api

    sent = {}

    def put(url, headers, json, timeout):
        sent.update(url=url, headers=headers)
        return type("Ok", (), {"raise_for_status": lambda self: None, "json": lambda self: {"status": "success"}})()

    monkeypatch.setattr(client_version, "get_client_version", lambda: "3.1.49")
    monkeypatch.setattr(rest_api.requests, "put", put)
    assert rest_api.report_client_version("https://h", "t", "3.1.49")
    assert sent["url"].endswith("/me/client-version")
    assert sent["headers"]["X-Client-Version"] == "3.1.49" and sent["headers"]["Authorization"] == "Bearer t"


def test_version_header_helper_is_the_single_source():
    src = _src("common/api/client_version.py")
    assert 'CLIENT_VERSION_HEADER = "X-Client-Version"' in src
    assert "get_runtime_version" in src
