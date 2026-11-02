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

Each crash file is paired with the Python stacks ``faulthandler`` wrote for the
same crash (``pyfault.py``): the app's ``<state>/pyfault-<pid>.txt`` (the pid
from the breadcrumb or the ``.ips``, else the dump written within
``PYFAULT_MATCH_S`` of the crash file), a moved worker log's sibling
``<pid>-<kind>-<n>.pyfault.txt``, or a ``pyfault-<pid>.txt`` beside a worker log
still in its temp dir. Its crashing thread becomes ``python_stack``.

A crash of the render worker (a ``Mixar --background`` child of the app) is not
the app crashing: it is reported as kind ``worker_crash``, grouped apart. It is
recognised by where its crash log lives, or, for an ``.ips``, by its parent
process being Mixar.

Windows Error Reporting has nothing for Mixar: Blender's exception filter ends
the process itself, so a Windows crash is only ever in crash.txt.

Files are only read: Mixar never deletes or moves them, except its own copies
in ``mixar_render_worker_crashes`` and the faulthandler dumps, deleted once
handled (or too old). ``Store`` remembers what was handled.
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
    PYFAULT_MATCH_S,
    PYFAULT_PREFIX,
    PYFAULT_SUFFIX,
    SESSION_MATCH_SLACK_S,
    WORKER_CRASH_DIR,
    WORKER_PYFAULT_SUFFIX,
)
from .parse_crash_txt import parse_crash_txt
from .parse_ips import parse_ips
from .parse_pyfault import parse_pyfault
from .report import native_report, report_id_for

# <pid>-<kind>-<n>.crash.txt in mixar_render_worker_crashes
_WORKER_FILE_RE = re.compile(r"^\d+-(?P<kind>.+)-\d+\.crash\.txt$")
_CRASH_SUFFIX = ".crash.txt"
_PYFAULT_RE = re.compile(rf"^{re.escape(PYFAULT_PREFIX)}(?P<pid>\d+){re.escape(PYFAULT_SUFFIX)}$")


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
        session = session_for(sessions, mtime)
        pyfault_path, pyfault = pyfault_for(path, source, mtime, parsed, store=store, own_pid=own_pid,
                                            session=session, temp_dirs=temp_dirs)
        if pyfault and pyfault.get("python_stack"):
            parsed["python_stack"] = pyfault["python_stack"]
            parsed["python_thread"] = pyfault.get("python_thread")
        report = native_report(
            parsed,
            kind=kind,
            source="crash_txt" if source == "worker_crash_txt" else source,
            report_id=report_id,
            device_id=device_id,
            crashed_at=datetime.fromtimestamp(mtime, tz=timezone.utc),
            static=static,
            session=session,
            current=current,
            raw_text=text if source != "macos_ips" else None,
        )
        if pyfault_path and _deletable_pyfault(pyfault_path, store, temp_dirs):
            report["_pyfault_path"] = pyfault_path
        reports.append(report)
        if len(reports) >= limit:
            break
    return reports


# faulthandler dumps ------------------------------------------------------------

def _mtime(path: str) -> float | None:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def _main_pyfaults(directory: str, own_pid: int) -> dict[int, str]:
    """pid -> ``<state>/pyfault-<pid>.txt`` of other (ended) sessions."""
    found = {}
    try:
        names = os.listdir(directory)
    except OSError:
        return found
    for name in names:
        match = _PYFAULT_RE.match(name)
        if match and int(match.group("pid")) != own_pid:
            found[int(match.group("pid"))] = os.path.join(directory, name)
    return found


def _worker_dirs(temp_dirs: list[str]) -> list[str]:
    return [os.path.join(d, WORKER_CRASH_DIR) for d in temp_dirs if d]


def _lone_worker_pyfaults(temp_dirs: list[str]) -> list[str]:
    """Worker dumps the supervisor kept without a crash log (an abort: macOS's
    ``.ips`` has the native stack)."""
    out = []
    for directory in _worker_dirs(temp_dirs):
        for path in glob.glob(os.path.join(directory, "*" + WORKER_PYFAULT_SUFFIX)):
            if not os.path.exists(path[:-len(WORKER_PYFAULT_SUFFIX)] + _CRASH_SUFFIX):
                out.append(path)
    return out


def pyfault_for(path: str, source: str, mtime: float, parsed: dict, *, store, own_pid: int,
                session: dict | None = None, temp_dirs: list[str] | None = None) -> tuple[str | None, dict | None]:
    """The faulthandler dump written for this crash file and its parse
    (``python_stack``, ``python_thread``), or (None, None)."""
    crash_type = parsed.get("crash_type")
    candidates: list[str] = []
    near = True  # only a dump written within PYFAULT_MATCH_S of the crash file
    if source == "worker_crash_txt":
        if _WORKER_FILE_RE.match(os.path.basename(path)):
            candidates = [path[:-len(_CRASH_SUFFIX)] + WORKER_PYFAULT_SUFFIX]
            near = False  # moved together by the supervisor
        else:
            candidates = glob.glob(os.path.join(os.path.dirname(path), PYFAULT_PREFIX + "*" + PYFAULT_SUFFIX))
    elif source == "macos_ips" and parsed.get("kind") == "worker_crash":
        candidates = _lone_worker_pyfaults(temp_dirs or [])
        pid = parsed.get("pid")
        if isinstance(pid, int):
            for directory in temp_dirs or []:
                candidates += glob.glob(os.path.join(directory, *WORKER_TMP_CRASH_GLOB[:-1],
                                                     f"{PYFAULT_PREFIX}{pid}{PYFAULT_SUFFIX}"))
    else:
        main = _main_pyfaults(store.directory, own_pid)
        pid = parsed.get("pid") if source == "macos_ips" else (session or {}).get("pid")
        if isinstance(pid, int):
            candidates = [main[pid]] if pid in main else []
        else:
            candidates = list(main.values())
    best, best_gap = None, None
    for candidate in candidates:
        written = _mtime(candidate)
        if written is None:
            continue
        gap = abs(written - mtime)
        if near and gap > PYFAULT_MATCH_S:
            continue
        if best_gap is None or gap < best_gap:
            best, best_gap = candidate, gap
    if best is None:
        return None, None
    text = _read(best)
    parsed_dump = parse_pyfault(text or "", crash_type)
    return (best, parsed_dump) if parsed_dump else (None, None)


def _deletable_pyfault(path: str, store, temp_dirs: list[str]) -> bool:
    """Our own copies only: the app's dumps and the worker dumps the supervisor moved."""
    folder = os.path.realpath(os.path.dirname(path))
    ours = [os.path.realpath(store.directory)] + [os.path.realpath(d) for d in _worker_dirs(temp_dirs)]
    return folder in ours


def remove_pyfault(path: str | None) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


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
                    remove_pyfault(path[:-len(_CRASH_SUFFIX)] + WORKER_PYFAULT_SUFFIX)
                    continue
            except OSError:
                continue
            found.add(path)
        for path in glob.glob(os.path.join(directory, WORKER_CRASH_DIR, "*" + WORKER_PYFAULT_SUFFIX)):
            written = _mtime(path)
            if written is not None and now - written > MAX_FILE_AGE_DAYS * 86400:
                remove_pyfault(path)
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
            remove_pyfault(path[:-len(_CRASH_SUFFIX)] + WORKER_PYFAULT_SUFFIX)
