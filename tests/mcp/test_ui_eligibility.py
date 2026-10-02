# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Account renewal reports upgrade requirements and cannot revive a revoked grant."""

import sys
from types import SimpleNamespace

import pytest
import requests

from mixar.modules.mcp_bridge.core import eligibility


@pytest.fixture
def renewal(monkeypatch):
    monkeypatch.setitem(sys.modules, "mixar.modules.auth.core.auth", SimpleNamespace(
        get_access_token=lambda: "fixture-only-token", refresh_access_token=lambda: {"success": False}))
    for name, value in (("_generation", 0), ("_deadline", 0), ("_refreshing", True), ("_reason", "starting")):
        monkeypatch.setattr(eligibility, name, value)
    now = [100.0]
    monkeypatch.setattr(eligibility.time, "monotonic", lambda: now[0])
    return {"backend_url": "http://127.0.0.1:1", "instance_id": "fixture", "headers": {}}, now


@pytest.mark.parametrize("code,reason", [
    (401, "signin_required"), (403, "account_unavailable"),
    (404, "backend_update_required"), (426, "client_update_required"),
])
def test_refusals_explain_the_required_recovery(renewal, monkeypatch, code, reason):
    context, _ = renewal
    monkeypatch.setattr(requests, "get", lambda *a, **kw: SimpleNamespace(status_code=code))
    eligibility._fetch(context, 0)
    assert eligibility.status() == {"eligible": False, "reason": reason}


def test_grant_expires_and_inflight_reply_cannot_revive_revocation(renewal, monkeypatch):
    context, now = renewal
    response = SimpleNamespace(status_code=200, json=lambda: {
        "eligible": True, "instance_id": "fixture", "contract": "mixar_ui_v1", "valid_for_seconds": 60})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: response)
    eligibility._fetch(context, 0)
    assert eligibility.valid()
    now[0] = 161
    assert eligibility.status() == {"eligible": False, "reason": "eligibility_expired"}
    eligibility.invalidate()
    eligibility._fetch(context, 0)  # Reply from before the revocation.
    assert not eligibility.valid()
