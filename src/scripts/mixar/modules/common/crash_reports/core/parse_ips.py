# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parse a macOS crash report (``~/Library/Logs/DiagnosticReports/Mixar-*.ips``).

An ``.ips`` file is one JSON header line followed by a JSON body. macOS writes
one for every Mixar crash, including the ones Blender's handler never sees
(``SIGABRT``: ``std::terminate``, asserts, ``abort()`` from ``BLI_mmap``'s
``SIGBUS`` handler before 4.3.1).

A report whose parent process is Mixar is the background render worker
(``common/render_worker``: the app spawns ``Mixar --background``); it is
returned as ``kind: worker_crash`` so it is never counted as the app crashing.

A ``SIGSEGV`` / ``SIGBUS`` that Mixar raised on itself is the re-raise at the
end of Blender's handler: the real stack is in ``mixar.crash.txt`` and the
``.ips`` "triggered" thread is whichever thread received the re-raise, so such
reports are skipped (``None``).
"""

from __future__ import annotations

import json
from datetime import datetime

from ..constants import MAX_FRAMES

HANDLED_SIGNALS = ("SIGSEGV", "SIGBUS")


def _crashed_at(header: dict) -> str | None:
    raw = header.get("timestamp") or ""
    for fmt in ("%Y-%m-%d %H:%M:%S.%f %z", "%Y-%m-%d %H:%M:%S %z"):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue
    return None


def parse_ips(text: str) -> dict | None:
    """The parsed crash, or None when it is not Mixar's or Blender's handler ran."""
    try:
        first, rest = text.split("\n", 1)
        header = json.loads(first)
        body = json.loads(rest)
    except (ValueError, AttributeError):
        return None
    if header.get("app_name") != "Mixar" and not str(header.get("bundleID", "")).startswith("com.mixar."):
        return None
    exception = body.get("exception") or {}
    termination = body.get("termination") or {}
    signal = exception.get("signal") or ""
    if signal in HANDLED_SIGNALS and exception.get("type") == "EXC_CRASH" and termination.get("byProc") == "Mixar":
        return None
    threads = body.get("threads") or []
    images = body.get("usedImages") or []
    index = body.get("faultingThread")
    thread = next((t for t in threads if t.get("triggered")), None)
    if thread is None and isinstance(index, int) and 0 <= index < len(threads):
        thread = threads[index]
    frames = []
    for frame in (thread or {}).get("frames", [])[:MAX_FRAMES]:
        image_index = frame.get("imageIndex")
        image = images[image_index] if isinstance(image_index, int) and 0 <= image_index < len(images) else {}
        frames.append({
            "module": str(image.get("name") or "")[:128] or None,
            "function": str(frame.get("symbol") or "")[:512],
            "offset": frame.get("imageOffset") if isinstance(frame.get("imageOffset"), int) else None,
        })
    os_version = (body.get("osVersion") or {}).get("train") or header.get("os_version")
    crash_type = signal or exception.get("type") or "unknown"
    thread_name = (thread or {}).get("queue") or (thread or {}).get("name")
    worker = body.get("parentProc") == "Mixar"
    return {
        "kind": "worker_crash" if worker else "native",
        "report_key": header.get("incident_id") or body.get("incident"),
        "app_version": header.get("app_version") or (body.get("bundleInfo") or {}).get("CFBundleShortVersionString"),
        "blender_version": None,
        "build_hash": None,
        "platform": "darwin",
        "os_version": str(os_version)[:64] if os_version else None,
        "crashed_at": _crashed_at(header),
        "crash_type": crash_type,
        "crash_module": frames[0]["module"] if frames else None,
        "is_mixar": True,
        "thread": "main" if thread_name == "com.apple.main-thread" else (str(thread_name)[:64] if thread_name else None),
        "frames": frames,
        "python_frames": [],
        "operators": [],
        "cpu_arch": body.get("cpuType"),
        "model": body.get("modelCode"),
    }
