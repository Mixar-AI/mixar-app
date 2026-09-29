# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Every REST request carries this build's ``X-Client-Version``.

The backend's force-update gate judges the header first and only falls back
to ``users.client_version`` (last writer across every install on the
account) without it. REST requests used to omit it, so the generation
catalog fetch and every gated generation route were judged by whichever
machine on a shared login reported last.
"""

from types import SimpleNamespace

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.api import client as client_module
from mixar.modules.common.api import client_version
from mixar.modules.common.api.services.generation_catalog_service import (
    GenerationCatalogService,
)
from mixar.modules.common.updates.core import update_checker
from mixar.modules.paint.procedural_materials import matgen_client


@pytest.fixture(autouse=True)
def _reset_version_cache(monkeypatch):
    monkeypatch.setattr(client_version, "_cached_version", None)
    monkeypatch.setattr(client_module, "get_access_token", lambda: "tok")


def _set_version(monkeypatch, value):
    def fake():
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(update_checker, "get_runtime_version", fake)


class _Response:
    status_code = 200
    ok = True
    headers = {"Content-Type": "application/json", "ETag": 'W/"v1"'}
    text = "{}"

    def json(self):
        return {"data": {"capabilities": []}}


def _recording_client():
    client = client_module.HTTPClient(base_url="https://api.example.test")
    sent = []

    def request(**kwargs):
        sent.append(kwargs["headers"])
        return _Response()

    client._session = SimpleNamespace(request=request)
    return client, sent


def test_default_headers_carry_known_version(monkeypatch):
    _set_version(monkeypatch, "4.1.2")
    headers = client_module.HTTPClient(
        base_url="https://api.example.test"
    )._get_default_headers()
    assert headers["X-Client-Version"] == "4.1.2"
    assert headers["Authorization"] == "Bearer tok"


@pytest.mark.parametrize("value", [None, "", RuntimeError("boom")])
def test_unknown_version_omits_header(monkeypatch, value):
    _set_version(monkeypatch, value)
    headers = client_module.HTTPClient(
        base_url="https://api.example.test"
    )._get_default_headers()
    assert "X-Client-Version" not in headers
    assert headers["Authorization"] == "Bearer tok"


def test_catalog_fetch_sends_version_alongside_if_none_match(monkeypatch):
    _set_version(monkeypatch, "4.1.2")
    client, sent = _recording_client()

    resp = GenerationCatalogService(client=client).get_catalog(etag='W/"v0"')

    assert resp.success
    assert sent[0]["X-Client-Version"] == "4.1.2"
    assert sent[0]["If-None-Match"] == 'W/"v0"'


def test_known_version_is_cached_unknown_is_retried(monkeypatch):
    calls = []

    def fake():
        calls.append(1)
        return None if len(calls) == 1 else "4.1.2"

    monkeypatch.setattr(update_checker, "get_runtime_version", fake)

    assert client_version.get_client_version() is None
    assert client_version.get_client_version() == "4.1.2"
    assert client_version.get_client_version() == "4.1.2"
    assert len(calls) == 2


def test_matgen_direct_requests_carry_version(monkeypatch):
    # matgen_client talks to the gated mat-gen router with raw requests,
    # bypassing HTTPClient, so it stamps the header itself.
    _set_version(monkeypatch, "4.1.2")
    headers = matgen_client._auth_headers("tok")
    assert headers == {"Authorization": "Bearer tok", "X-Client-Version": "4.1.2"}
