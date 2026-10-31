# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What to offer after a crash, and never the same broken file twice.

Input: every session directory (``journal.list_sessions``), the native
autosaves found in Blender's temp folder, and two filesystem probes. Output:
one offer (the newest crashed session's best save point, with the older ones
as fallbacks) or None.

Crash-loop guard: before a launch reads a save point it records
``restore_attempt`` in its OWN manifest, and marks it confirmed once the
restored document has run for a while. A dead session holding an unconfirmed
attempt died reading that point (or right after), so the point is never
offered again: the next older candidate is, as a "previous save point". The
failed paths are written into the offered session's ``failed_points`` so the
rule outlives the dead launch's directory.

Pure Python; ``exists``/``mtime``/``alive`` are injected so the rules are
unit-tested on plain dicts.
"""

from __future__ import annotations

import os
import re

AUTOSAVE_RE = re.compile(r"^(?:(?P<name>.+)_)?(?P<pid>\d+)_autosave\.mixar$")
QUIT_FILE = "quit.blend"
LEGACY_MAX_AGE_S = 14 * 24 * 3600
# A user save is "the newest state" only if the file on disk is that save.
_PROJECT_MTIME_SLACK_S = 2.0


def native_autosaves(tempdir_base: str, listdir=os.listdir, mtime=os.path.getmtime) -> list:
    """``<name>_<pid>_autosave.mixar`` files in Blender's temp folder."""
    try:
        entries = listdir(tempdir_base)
    except OSError:
        return []
    found = []
    for entry in entries:
        match = AUTOSAVE_RE.match(entry)
        if not match:
            continue
        path = os.path.join(tempdir_base, entry)
        try:
            when = mtime(path)
        except OSError:
            continue
        found.append({"path": path, "pid": int(match.group("pid")),
                      "name": match.group("name") or "", "mtime": when})
    return found


def _document_name(path: str) -> str:
    base = os.path.basename(path or "")
    stem, _ext = os.path.splitext(base)
    return stem


def candidates_for(session: dict, *, autosaves=(), exists=os.path.isfile,
                   mtime=os.path.getmtime) -> list:
    """Every restorable state of one session, newest first."""
    found = []
    for point in session.get("save_points") or []:
        found.append({"kind": "save_point", "path": point.get("file", ""),
                      "at": float(point.get("at") or 0.0),
                      "original_path": point.get("original_path", ""),
                      "scenes": list(point.get("scenes") or []),
                      "agent_scenes": list(point.get("agent_scenes") or []),
                      "jobs": list(point.get("jobs") or [])})
    started = float(session.get("started_at") or 0.0)
    pid = session.get("pid")
    for auto in autosaves:
        if auto.get("pid") == pid and float(auto.get("mtime") or 0.0) >= started - 1.0:
            found.append({"kind": "autosave", "path": auto["path"], "at": float(auto["mtime"]),
                          "original_path": session.get("document_path", ""),
                          "scenes": [], "agent_scenes": [], "jobs": []})
    saved = session.get("project_saved") or None
    if isinstance(saved, dict) and saved.get("path"):
        path = saved["path"]
        try:
            on_disk = mtime(path) if exists(path) else None
        except OSError:
            on_disk = None
        if on_disk is not None and on_disk >= float(saved.get("at") or 0.0) - _PROJECT_MTIME_SLACK_S:
            found.append({"kind": "project", "path": path, "at": float(saved.get("at") or 0.0),
                          "original_path": path, "scenes": [], "agent_scenes": [], "jobs": []})
    for point in session.get("inherited_points") or []:
        found.append({"kind": "inherited", "path": point.get("path", ""),
                      "at": float(point.get("at") or 0.0),
                      "original_path": point.get("original_path", ""),
                      "scenes": list(point.get("scenes") or []),
                      "agent_scenes": list(point.get("agent_scenes") or []),
                      "jobs": list(point.get("jobs") or [])})
    for snap in session.get("snapshots") or []:
        found.append({"kind": "snapshot", "path": snap.get("file", ""),
                      "at": float(snap.get("at") or 0.0),
                      "original_path": snap.get("original_path", ""),
                      "scenes": [], "agent_scenes": [], "jobs": []})
    # A native autosave or the project file knows nothing about the agent or
    # the jobs; the newest save point of the same session does.
    points = session.get("save_points") or []
    if points:
        newest = max(points, key=lambda p: float(p.get("at") or 0.0))
        for cand in found:
            if cand["kind"] in ("autosave", "project", "snapshot"):
                for key in ("scenes", "agent_scenes", "jobs"):
                    if not cand[key]:
                        cand[key] = list(newest.get(key) or [])
    found = [c for c in found if c["path"] and exists(c["path"])]
    # Newest first; on a tie the richer record wins (a save point knows the
    # agent's tabs and the jobs, a native autosave of the same moment does not).
    rank = {"save_point": 0, "project": 1, "autosave": 2, "inherited": 3, "snapshot": 4}
    found.sort(key=lambda c: (-c["at"], rank.get(c["kind"], 9)))
    return found


def crashed_restores(sessions: list, own_session: str = "") -> set:
    """Save points whose restore crashed: a dead session that recorded
    ``restore_attempt`` and never confirmed it died reading that point (or in
    the first seconds after)."""
    failed = set()
    for session in sessions:
        if session.get("alive") or session.get("session") == own_session:
            continue
        attempt = session.get("restore_attempt") or None
        if isinstance(attempt, dict) and attempt.get("point") and not attempt.get("confirmed"):
            failed.add(attempt["point"])
    return failed


def find_offer(sessions: list, *, own_session: str = "", autosaves=(), quit_mtime: float = 0.0,
               now: float = 0.0, exists=os.path.isfile, mtime=os.path.getmtime,
               pid_alive=lambda pid: False) -> dict | None:
    """The offer for this launch, or None.

    ``sessions`` are ``journal.list_sessions`` dicts (each with ``alive``).
    The returned dict carries everything the prompt and the restore need,
    plus ``failed_points`` (to persist before the read) and ``older`` (other
    crashed sessions, resolved together with this one so they never nag).
    """
    crashed = crashed_restores(sessions, own_session)
    known_pids = {s.get("pid") for s in sessions}
    offers = []
    debris = []
    for session in sessions:
        if session.get("alive") or session.get("session") == own_session:
            continue
        if session.get("clean_exit") or session.get("resolved"):
            continue
        failed = sorted(set(session.get("failed_points") or []) | crashed)
        all_cands = candidates_for(session, autosaves=autosaves, exists=exists, mtime=mtime)
        cands = [c for c in all_cands if c["path"] not in failed]
        if not cands:
            debris.append(session.get("dir", ""))
            continue
        failed = [p for p in failed if any(c["path"] == p for c in all_cands)]
        offers.append({
            "session": session.get("session"),
            "dir": session.get("dir", ""),
            "target": cands[0],
            "fallbacks": cands[1:],
            "failed_points": failed,
            "loop": bool(failed),
            "legacy": False,
        })
    # Native autosaves no manifest claims (a build before this one, or a
    # session whose journal could not be written): the 702ab7e9f rule — the
    # owner is gone and the file is newer than the last clean quit.
    for auto in autosaves:
        if auto.get("pid") in known_pids:
            continue
        when = float(auto.get("mtime") or 0.0)
        if when <= quit_mtime or (now and now - when > LEGACY_MAX_AGE_S):
            continue
        if pid_alive(auto.get("pid")) or auto["path"] in crashed:
            continue
        offers.append({
            "session": f"legacy-{auto['pid']}",
            "dir": "",
            "target": {"kind": "autosave", "path": auto["path"], "at": when,
                       "original_path": "", "name": auto.get("name", ""),
                       "scenes": [], "agent_scenes": [], "jobs": []},
            "fallbacks": [],
            "failed_points": [],
            "loop": False,
            "legacy": True,
        })
    if not offers:
        return {"debris": [d for d in debris if d]} if debris else None
    offers.sort(key=lambda o: -o["target"]["at"])
    offer = offers[0]
    offer["older"] = [o for o in offers[1:]]
    offer["name"] = (_document_name(offer["target"].get("original_path", ""))
                     or offer["target"].get("name", ""))
    offer["debris"] = [d for d in debris if d]
    return offer
