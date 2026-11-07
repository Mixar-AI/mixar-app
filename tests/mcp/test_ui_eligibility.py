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
    for name, value in (("_generation", 0), ("_deadline", 0), ("_refreshing", True), ("_reason", "starting"),
                        ("_next_attempt", 0.0), ("_identity", None)):
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


def _poll(monkeypatch, codes):
    """Drive refresh() like the runtime timer, running each fetch inline; return
    a function that advances the clock, refreshes, and counts backend calls."""
    calls = []

    def get(*args, **kwargs):
        calls.append(kwargs["headers"]["X-Mixar-Instance-Id"])
        return SimpleNamespace(status_code=codes[0])

    class InlineThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(eligibility.threading, "Thread", InlineThread)
    monkeypatch.setattr(eligibility, "_refreshing", False)
    monkeypatch.setattr(eligibility, "_identity", None)
    monkeypatch.setattr(eligibility, "_next_attempt", 0.0)
    return calls


def _context(instance="fixture"):
    return {"backend_url": "http://127.0.0.1:1", "instance_id": instance, "headers": {},
            "connected": True, "signed_in": True}


@pytest.mark.parametrize("code", [426, 409])
def test_update_required_backs_off_to_fifteen_minutes(renewal, monkeypatch, code):
    _, now = renewal
    calls = _poll(monkeypatch, [code])
    for _ in range(179):  # Just under fifteen minutes of 5 s ticks (was 180 calls).
        eligibility.refresh(_context())
        now[0] += 5
    assert len(calls) == 1
    assert eligibility.status() == {"eligible": False, "reason": "client_update_required"}
    now[0] += 5
    eligibility.refresh(_context())  # A rolled-back floor is still found.
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["relaunch", "toggle"])
def test_update_required_renews_at_once_on_identity_change_or_toggle(renewal, monkeypatch, change):
    _, now = renewal
    calls = _poll(monkeypatch, [426])
    eligibility.refresh(_context())
    now[0] += 5
    if change == "toggle":  # UI control off (runtime calls invalidate) and on again.
        eligibility.invalidate()
        eligibility.refresh(_context())
    else:  # New instance / sign-in / backend.
        eligibility.refresh(_context("relaunched"))
    assert len(calls) == 2
    assert eligibility.status()["reason"] == "client_update_required"


def test_transient_failure_still_retries_every_five_seconds(renewal, monkeypatch):
    _, now = renewal
    codes = [503]
    calls = _poll(monkeypatch, codes)
    eligibility.refresh(_context())
    now[0] += 4
    eligibility.refresh(_context())
    assert len(calls) == 1
    now[0] += 1
    eligibility.refresh(_context())
    assert len(calls) == 2
    assert eligibility.status()["reason"] == "backend_unavailable"
