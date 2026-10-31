# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The crash reporter's worker thread: breadcrumb, harvest, send.

The main thread only hands it a context snapshot (heartbeat) or an exception
report; every file read / write, keyring lookup and HTTP call happens here.

Sending needs all of: Share Usage Data on, a signed-in account, not a guest.
Until then crash files simply stay where they are and exceptions wait in
``pending.json``. Outcome of one POST:
- 2xx: handled, recorded in ``sent.json`` (never sent again);
- 401 / 403 / 429 / 5xx / network error: kept, retried on a later heartbeat;
- any other 4xx: the server refuses it for good; recorded so it is not retried.
"""

from __future__ import annotations

import os
import threading
import time

from mixar.config.logging_config import get_logger

from ..constants import ENDPOINT, REQUEST_TIMEOUT_S
from . import harvest
from .store import Store

logger = get_logger(__name__)

SENT, LATER, REFUSED = "sent", "later", "refused"


def default_gate() -> bool:
    """Consent on, signed in, not a guest (keyring read: worker thread only)."""
    try:
        from mixar.modules.common.analytics.preferences import is_enabled

        if not is_enabled():
            return False
        from mixar.modules.auth.core.auth import get_access_token

        if not get_access_token():
            return False
        from mixar.modules.auth.core.guest import is_guest

        return not is_guest()
    except Exception:  # noqa: BLE001 - unknown means "not now"
        return False


def default_device_id() -> str | None:
    try:
        from mixar.modules.auth.core.device import get_device_id

        return get_device_id()
    except Exception:  # noqa: BLE001
        return None


def default_send(payload: dict) -> str:
    """POST one report; the client stamps auth and x-telemetry-consent."""
    try:
        from mixar.modules.common.api.client import get_http_client

        response = get_http_client().post(
            ENDPOINT, json=payload, timeout=REQUEST_TIMEOUT_S, raise_for_status=False,
        )
    except Exception as exc:  # noqa: BLE001 - offline / TLS / timeout: try again later
        logger.debug("Crash report not sent yet: %s", type(exc).__name__)
        return LATER
    status = int(getattr(response, "status_code", 0) or 0)
    if 200 <= status < 300:
        return SENT
    if status in (0, 401, 403, 408, 429) or status >= 500:
        return LATER
    logger.debug("Crash report refused by the server (HTTP %s)", status)
    return REFUSED


def _wire(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if not key.startswith("_")}


class Reporter:
    def __init__(self, *, state_dir: str, temp_dirs: list[str], static: dict, report_dirs: list[str] | None = None,
                 own_pid: int | None = None, gate=default_gate, send=default_send, device_id=default_device_id):
        self.store = Store(state_dir)
        self.temp_dirs = list(temp_dirs)
        self.report_dirs = list(report_dirs or [])
        self.static = dict(static)
        self.own_pid = own_pid or os.getpid()
        self._gate = gate
        self._send = send
        self._device_id = device_id
        self._started_at = time.time()
        self._current: dict = {}
        self._new_exceptions: list[dict] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.harvest_done = False

    # Main-thread API (no I/O) ---------------------------------------------
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="MixarCrashReporter", daemon=True)
            self._thread.start()

    def heartbeat(self, current: dict) -> None:
        with self._lock:
            self._current = dict(current)
        self._wake.set()

    def enqueue_exception(self, payload: dict) -> None:
        with self._lock:
            self._new_exceptions.append(payload)
        self._wake.set()

    def current(self) -> dict:
        with self._lock:
            return dict(self._current)

    def stop(self, *, clean: bool) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if clean:
            self.store.remove_session(self.own_pid)

    # Worker ------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - reporting never takes the app down
                logger.debug("Crash reporter tick failed: %s", exc)

    def tick(self) -> None:
        """One pass: breadcrumb, persist new exceptions, then send if allowed."""
        current = self.current()
        self.store.write_session(self.own_pid, {
            "pid": self.own_pid,
            "started_at": self._started_at,
            "updated_at": time.time(),
            "context": {**self.static, **current},
        })
        with self._lock:
            fresh, self._new_exceptions = self._new_exceptions, []
        if fresh:
            self.store.add_pending(fresh)
        if self.harvest_done and not self.store.pending():
            return
        if not self._gate():
            return
        device_id = self._device_id()
        if not device_id:
            return
        if not self.harvest_done:
            self.harvest_done = self._send_crash_files(device_id, current)
        self._send_pending(device_id)

    def _send_crash_files(self, device_id: str, current: dict) -> bool:
        reports = harvest.build_reports(
            temp_dirs=self.temp_dirs, report_dirs=self.report_dirs, store=self.store, own_pid=self.own_pid,
            device_id=device_id, static=self.static, current=current,
        )
        complete = True
        for payload in reports:
            outcome = self._send(_wire(payload))
            if outcome == LATER:
                complete = False
                break
            self.store.mark_sent(payload["report_id"], outcome)
        return complete

    def _send_pending(self, device_id: str) -> None:
        handled = set()
        for payload in self.store.pending():
            report_id = payload.get("report_id")
            if not report_id:
                continue
            outcome = self._send(_wire({**payload, "device_id": device_id}))
            if outcome == LATER:
                break
            handled.add(report_id)
        self.store.remove_pending(handled)
