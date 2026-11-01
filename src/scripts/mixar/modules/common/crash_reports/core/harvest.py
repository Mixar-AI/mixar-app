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
- the background render worker's crash logs, which its supervisor moves to
  ``<tmp>/mixar_render_worker_crashes/<pid>-<kind>-<n>.crash.txt`` (or, if it
  could not, still in ``<tmp>/mixar_render_worker/<app pid>/worker-<kind>/tmp/``).

A crash of the render worker (a ``Mixar --background`` child of the app) is not
the app crashing: it is reported as kind ``worker_crash``, grouped apart. It is
recognised by where its crash log lives, or, for an ``.ips``, by its parent
process being Mixar.

Windows Error Reporting has nothing for Mixar: Blender's exception filter ends
the process itself, so a Windows crash is only ever in crash.txt.

Files are only read: Mixar never deletes or moves them, except its own copies
in ``mixar_render_worker_crashes``, deleted once handled (or too old). ``Store``
remembers what was handled.
"""

from __future__ import annotations

import glob
import os
import re
import time
from datetime import datetime, timezone

from ..constants import (
    CRASH_TXT_GLOB,
    WORKER_CRASH_GLOB,
    WORKER_TMP_CRASH_GLOB,
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

# <pid>-<kind>-<n>.crash.txt in mixar_render_worker_crashes
_WORKER_FILE_RE = re.compile(r"^\d+-(?P<kind>.+)-\d+\.crash\.txt$")


def default_report_dirs(platform: str) -> list[str]:
    """OS crash-report folders worth reading on this platform."""
    return [os.path.expanduser(MACOS_REPORTS_DIR)] if platform == "darwin" else []


def candidate_files(temp_dirs: list[str], report_dirs: list[str] | None = None,
                    now: float | None = None) -> list[tuple[str, str, float]]:
    """(path, source, mtime) of recent crash files, newest first."""
    now = time.time() if now is None else now
    found: dict[str, tuple[str, str, float]] = {}
    patterns = [(os.path.join(d, CRASH_TXT_GLOB), "crash_txt") for d in temp_dirs if d]
    for glob_parts in (WORKER_CRASH_GLOB, WORKER_TMP_CRASH_GLOB):
        patterns += [(os.path.join(d, *glob_parts), "worker_crash_txt") for d in temp_dirs if d]
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


def worker_kind(path: str) -> str | None:
    """``render`` for ``.../mixar_render_worker_crashes/123-render-1.crash.txt``
    or ``.../worker-render/tmp/mixar.crash.txt``."""
    match = _WORKER_FILE_RE.match(os.path.basename(path))
    if match:
        return match.group("kind")[:32]
    parts = os.path.normpath(path).split(os.sep)
    for part in reversed(parts):
        if part.startswith("worker-"):
            return part[len("worker-"):][:32] or None
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
        kind = "native"
        if source in ("crash_txt", "worker_crash_txt"):
            parsed = parse_crash_txt(text)
            report_id = report_id_for("crash_txt", text)
            if source == "worker_crash_txt":
                kind = "worker_crash"
                if parsed is not None:
                    parsed["worker_kind"] = worker_kind(path)
        else:
            parsed = parse_ips(text)
            report_id = report_id_for("ips", str((parsed or {}).get("report_key") or text))
        if not parsed or not parsed.get("is_mixar"):
            continue
        kind = parsed.get("kind") or kind
        if store.is_sent(report_id):
            continue
        reports.append(native_report(
            parsed,
            kind=kind,
            source="crash_txt" if source == "worker_crash_txt" else source,
            report_id=report_id,
            device_id=device_id,
            crashed_at=datetime.fromtimestamp(mtime, tz=timezone.utc),
            static=static,
            session=session_for(sessions, mtime),
            current=current,
            raw_text=text if source != "macos_ips" else None,
        ))
        if len(reports) >= limit:
            break
    return reports


# Our own worker crash copies -------------------------------------------------

def worker_crash_files(temp_dirs: list[str], now: float | None = None) -> set[str]:
    """The crash logs waiting in ``mixar_render_worker_crashes``; files past
    ``MAX_FILE_AGE_DAYS`` are deleted on the way (never reported)."""
    now = time.time() if now is None else now
    found = set()
    for directory in temp_dirs:
        if not directory:
            continue
        for path in glob.glob(os.path.join(directory, *WORKER_CRASH_GLOB)):
            try:
                if now - os.stat(path).st_mtime > MAX_FILE_AGE_DAYS * 86400:
                    os.unlink(path)
                    continue
            except OSError:
                continue
            found.add(path)
    return found


def remove_handled_worker_crashes(temp_dirs: list[str], store) -> None:
    """Delete our worker crash copies the sent ledger has handled (sent, or
    refused for good). Only that folder: the app's own crash logs stay."""
    handled = store.sent_ids()
    if not handled:
        return
    for path in worker_crash_files(temp_dirs):
        text = _read(path)
        if text is not None and report_id_for("crash_txt", text) in handled:
            try:
                os.unlink(path)
            except OSError:
                pass
