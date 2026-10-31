# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Find the crash files earlier Mixar sessions left behind and build reports.

Sources (newest first, at most ``MAX_REPORTS_PER_LAUNCH`` per launch):
- ``<tempdir base>/*.crash.txt``: Blender's handler (``mixar.crash.txt``, or
  ``<blend name>.crash.txt`` when a file was open). Only logs whose stack runs
  in the Mixar binary count; a vanilla Blender's log in the same folder is
  skipped.
- ``~/Library/Logs/DiagnosticReports/Mixar*.ips`` on macOS: crashes Blender's
  handler does not catch (abort, terminate, the pre-4.3.1 SIGBUS path).

Windows Error Reporting has nothing for Mixar: Blender's exception filter ends
the process itself, so a Windows crash is only ever in crash.txt.

Files are only read: Mixar never deletes or moves them. ``Store`` remembers
what was handled.
"""

from __future__ import annotations

import glob
import os
import time
from datetime import datetime, timezone

from ..constants import (
    CRASH_TXT_GLOB,
    MACOS_REPORT_GLOB,
    MACOS_REPORTS_DIR,
    MAX_FILE_AGE_DAYS,
    MAX_FILE_BYTES,
    MAX_REPORTS_PER_LAUNCH,
    SESSION_MATCH_SLACK_S,
)
from .parse_crash_txt import parse_crash_txt
from .parse_ips import parse_ips
from .report import native_report, report_id_for


def default_report_dirs(platform: str) -> list[str]:
    """OS crash-report folders worth reading on this platform."""
    return [os.path.expanduser(MACOS_REPORTS_DIR)] if platform == "darwin" else []


def candidate_files(temp_dirs: list[str], report_dirs: list[str] | None = None,
                    now: float | None = None) -> list[tuple[str, str, float]]:
    """(path, source, mtime) of recent crash files, newest first."""
    now = time.time() if now is None else now
    found: dict[str, tuple[str, str, float]] = {}
    patterns = [(os.path.join(d, CRASH_TXT_GLOB), "crash_txt") for d in temp_dirs if d]
    patterns += [(os.path.join(d, MACOS_REPORT_GLOB), "macos_ips") for d in (report_dirs or []) if d]
    for pattern, source in patterns:
        for path in glob.glob(pattern):
            try:
                stat = os.stat(path)
            except OSError:
                continue
            if stat.st_size > MAX_FILE_BYTES or now - stat.st_mtime > MAX_FILE_AGE_DAYS * 86400:
                continue
            found[os.path.realpath(path)] = (path, source, stat.st_mtime)
    return sorted(found.values(), key=lambda item: item[2], reverse=True)


def _read(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(MAX_FILE_BYTES)
    except OSError:
        return None


def session_for(sessions: list[dict], mtime: float) -> dict | None:
    """The breadcrumb whose session was alive when the file was written."""
    best = None
    for session in sessions:
        started = float(session.get("started_at") or 0)
        updated = float(session.get("updated_at") or 0)
        if started - 5 <= mtime <= updated + SESSION_MATCH_SLACK_S:
            if best is None or started > float(best.get("started_at") or 0):
                best = session
    return best


def build_reports(
    *,
    temp_dirs: list[str],
    report_dirs: list[str] | None = None,
    store,
    own_pid: int,
    device_id: str,
    static: dict,
    current: dict,
    limit: int = MAX_REPORTS_PER_LAUNCH,
) -> list[dict]:
    """Wire reports for crash files not yet handled (worker thread)."""
    sessions = store.sessions(own_pid)
    reports = []
    for path, source, mtime in candidate_files(temp_dirs, report_dirs):
        text = _read(path)
        if not text:
            continue
        if source == "crash_txt":
            parsed = parse_crash_txt(text)
            report_id = report_id_for("crash_txt", text)
        else:
            parsed = parse_ips(text)
            report_id = report_id_for("ips", str((parsed or {}).get("report_key") or text))
        if not parsed or not parsed.get("is_mixar"):
            continue
        if store.is_sent(report_id):
            continue
        reports.append(native_report(
            parsed,
            source=source,
            report_id=report_id,
            device_id=device_id,
            crashed_at=datetime.fromtimestamp(mtime, tz=timezone.utc),
            static=static,
            session=session_for(sessions, mtime),
            current=current,
            raw_text=text if source == "crash_txt" else None,
        ))
        if len(reports) >= limit:
            break
    return reports
