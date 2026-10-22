# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile startup module for onboarding_tour_telemetry_e2e.py.

Copied into ``<profile>/scripts/startup/`` so it loads before the tour can
start. Replaces the analytics worker's delivery (``capture._post_batch``)
with an append to ``$MIXAR_QA_TELEMETRY_LOG`` (one JSON event per line):
the events are what the app would really send — consent, auth and guest
gates included — but nothing leaves the machine, so QA never reaches
PostHog. The flush interval drops to 0.5 s so assertions do not wait 10 s;
the final flush at quit lands in the same file.

``$MIXAR_QA_TELEMETRY_CALLS`` additionally records every call of the
module's ``capture`` (callers that import it at call time, as the tour
telemetry does) BEFORE its gates: a fresh device starts as a guest, whose
events are never delivered, so the first-run start is only visible there.
Inert unless MIXAR_QA=1.
"""

import importlib
import json
import os
import threading

_LOCK = threading.Lock()


def _append(path, rows):
    with _LOCK, open(path, "a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, default=str) + "\n")


def _install(log_path, calls_path):
    # The analytics package re-exports ``capture`` the FUNCTION; patch the module.
    cap = importlib.import_module("mixar.modules.common.analytics.capture")
    deliver = cap.capture

    def record(batch):
        _append(log_path, batch)

    def capture(event, properties=None, *, context=None):
        if calls_path:
            try:
                _append(calls_path, [{"event": event, "properties": dict(properties or {})}])
            except Exception:  # noqa: BLE001 - recording must never break capture
                pass
        return deliver(event, properties, context=context)

    cap._post_batch = record
    cap.capture = capture
    cap.FLUSH_INTERVAL_SECONDS = 0.5
    print("[qa_tour_telemetry] analytics delivery recorded locally", flush=True)


if os.environ.get("MIXAR_QA") == "1" and os.environ.get("MIXAR_QA_TELEMETRY_LOG"):
    try:
        _install(os.environ["MIXAR_QA_TELEMETRY_LOG"],
                 os.environ.get("MIXAR_QA_TELEMETRY_CALLS"))
    except Exception as exc:  # never break startup
        print(f"[qa_tour_telemetry] install FAILED: {exc}", flush=True)


def register():
    pass


def unregister():
    pass
