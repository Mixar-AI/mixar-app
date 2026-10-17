#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Two instances sharing one refresh token must not log each other out.

The desktop mints a DETERMINISTIC idempotency key per refresh token
(`auth._refresh_idempotency_key`, a uuid5), so two Mixar instances that share
the OS keychain and race to refresh the same token send the SAME key. The
backend then coordinates them (begin -> wait -> complete): both receive the
same rotated pair instead of the loser getting a 401 reuse that would clear
the shared credentials and log both out.

This replays that against a running backend, using the desktop's OWN key
function, and shows the control (the old random-key behaviour) still conflicts.

    QA_BACKEND=http://127.0.0.1:8002 QA_EMAIL=raj@mixar.app QA_PASSWORD=... \
        python3 tests/qa/multi_instance_refresh_e2e.py
"""
import concurrent.futures as cf
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "scripts"))
import requests  # noqa: E402

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()
from mixar.modules.auth.core import auth  # noqa: E402

BASE = os.environ.get("QA_BACKEND", "http://127.0.0.1:8002") + "/api/v1/auth"
EMAIL = os.environ["QA_EMAIL"]
PASSWORD = os.environ["QA_PASSWORD"]


def _login():
    r = requests.post(f"{BASE}/login/json", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    r.raise_for_status()
    d = r.json().get("data", r.json())
    return d["refresh_token"]


def _refresh(rt, key):
    r = requests.post(f"{BASE}/refresh", json={"refresh_token": rt},
                      headers={"Idempotency-Key": key}, timeout=15)
    return r.status_code, (r.json().get("data", r.json())).get("refresh_token")


def _race(rt, key_a, key_b):
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        a = ex.submit(_refresh, rt, key_a)
        b = ex.submit(_refresh, rt, key_b)
        return a.result(), b.result()


def main():
    # The fix: both instances use the desktop's deterministic key for the token.
    rt = _login()
    key = auth._refresh_idempotency_key(rt)
    (ca, ta), (cb, tb) = _race(rt, key, key)
    assert sorted((ca, cb)) == [200, 200], f"expected both 200, got {ca},{cb}"
    assert ta and ta == tb, "both instances must receive the SAME rotated pair"
    assert uuid.UUID(key).version == 5
    print("FIX: two instances, same deterministic key -> both 200, same new pair. No logout.")

    # The control: the old random-per-attempt keys still conflict (the bug).
    rt2 = _login()
    (ca, _), (cb, _) = _race(rt2, str(uuid.uuid4()), str(uuid.uuid4()))
    assert sorted((ca, cb)) == [200, 401], f"expected one 200 one 401, got {ca},{cb}"
    print("CONTROL: random per-attempt keys -> one 200, one 401 (the logout bug).")
    print("PASS")


if __name__ == "__main__":
    main()
