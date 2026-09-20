# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Sync requests must refresh+retry on ANY 401, not just raise_for_status.

raise_for_status=False call sites (asset_search metered endpoints, status
probes) used to skip token refresh entirely, so after token expiry every
call failed raw 401 until some other module happened to refresh it.
"""

from types import SimpleNamespace

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.api import client as client_module


class _Response:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data
        self.ok = status_code < 400
        self.headers = {}
        self.text = str(data)

    def json(self):
        return self._data


def _client_with_responses(monkeypatch, responses, tokens):
    client = client_module.HTTPClient(base_url="https://api.example.test")
    calls = []

    def request(**kwargs):
        calls.append(kwargs["headers"].get("Authorization"))
        return next(responses)

    client._session = SimpleNamespace(request=request)
    monkeypatch.setattr(
        client_module, "get_access_token", lambda: next(tokens)
    )
    return client, calls


def test_sync_auth_refresh_fires_without_raise_for_status(monkeypatch):
    monkeypatch.setattr(
        client_module, "refresh_access_token", lambda: {"success": True}
    )
    responses = iter((_Response(401, {"detail": "expired"}),
                      _Response(200, {"data": {"results": []}})))
    tokens = iter(["stale-token", "fresh-token"])
    client, calls = _client_with_responses(monkeypatch, responses, tokens)

    resp = client.post(
        "api/v1/asset-search/search",
        data={"prompt": "chair"},
        raise_for_status=False,
    )

    assert [c for c in calls if c] == ["Bearer stale-token", "Bearer fresh-token"]
    assert resp.success is True
    assert resp.status_code == 200


def test_sync_auth_refresh_failure_still_returns_raw_response(monkeypatch):
    monkeypatch.setattr(
        client_module, "refresh_access_token", lambda: {"success": False}
    )
    responses = iter((_Response(401, {"detail": "expired"}),))
    tokens = iter(["stale-token"])
    client, calls = _client_with_responses(monkeypatch, responses, tokens)

    resp = client.post("api/v1/asset-search/search", raise_for_status=False)

    # No retry when the refresh fails — the 401 rides through as before.
    assert len(calls) == 1
    assert resp.success is False
    assert resp.status_code == 401


def test_sync_auth_refresh_failure_raises_for_status_callers(monkeypatch):
    import pytest

    monkeypatch.setattr(
        client_module, "refresh_access_token", lambda: {"success": False}
    )
    responses = iter((_Response(401, {"detail": "expired"}),))
    tokens = iter(["stale-token"])
    client, _calls = _client_with_responses(monkeypatch, responses, tokens)

    with pytest.raises(client_module.AuthenticationError):
        client.post("api/v1/asset-search/search", raise_for_status=True)
