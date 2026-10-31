# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Offer the autosave of a session that crashed.

A clean quit deletes the session's ``<name>_<pid>_autosave.mixar`` and writes
``quit.blend``; a crash leaves the autosave behind. So an autosave whose
process is gone and which is newer than ``quit.blend`` is a session that did
not end cleanly. The splash lists the newest one, and the operator below opens
it with ``wm.recover_auto_save`` (untitled, so nothing is overwritten).

The cs-go-3 run (28 Oct) crashed after 1 h 50 min and the next launch showed
an empty splash: Blender's own File > Recover > Auto Save was the only way
back, and nobody looks there after a crash.
"""

import os
import re
import tempfile
import time

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

_AUTOSAVE_RE = re.compile(r"^(?:(?P<name>.+)_)?(?P<pid>\d+)_autosave\.mixar$")
QUIT_FILE = "quit.blend"
MAX_AGE_S = 14 * 24 * 3600

_cached = None


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        # os.kill(pid, 0) is not a liveness probe on Windows.
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = ctypes.c_void_p
            handle = kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
            if not handle:
                return ctypes.get_last_error() == 5  # access denied: it exists
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                    return True
                return code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(handle))
        except Exception:  # noqa: BLE001 - unknown means "maybe running": offer nothing
            return True
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def crashed_autosaves(tempdir_base, own_pid, now=None, alive=_pid_alive):
    """Autosaves of sessions that did not end cleanly, newest first.

    Each is ``{"path", "name", "mtime"}``; ``name`` is the project's file name
    without its extension, or "" for an untitled session.
    """
    now = time.time() if now is None else now
    try:
        entries = os.listdir(tempdir_base)
    except OSError:
        return []
    quit_path = os.path.join(tempdir_base, QUIT_FILE)
    clean_quit = os.path.getmtime(quit_path) if os.path.isfile(quit_path) else 0.0
    found = []
    for entry in entries:
        match = _AUTOSAVE_RE.match(entry)
        if not match:
            continue
        pid = int(match.group("pid"))
        path = os.path.join(tempdir_base, entry)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if pid == own_pid or mtime <= clean_quit or now - mtime > MAX_AGE_S:
            continue
        if alive(pid):
            continue  # another Mixar is still running and owns this autosave
        found.append({"path": path, "name": match.group("name") or "", "mtime": mtime})
    found.sort(key=lambda item: item["mtime"], reverse=True)
    return found


def _tempdir_base():
    session = bpy.app.tempdir
    if session:
        return os.path.dirname(os.path.normpath(session))
    return tempfile.gettempdir()


def latest_crashed_autosave():
    """The newest crashed session's autosave, scanned once per launch."""
    global _cached
    if _cached is None:
        try:
            found = crashed_autosaves(_tempdir_base(), os.getpid())
        except Exception:  # noqa: BLE001 - the splash must draw whatever happens here
            found = []
        _cached = found[0] if found else False
    return _cached or None


def label(entry) -> str:
    stamp = time.strftime("%b %d, %H:%M", time.localtime(entry["mtime"]))
    return f"{entry['name'] or 'Untitled'} · {stamp}"


class MIXAR_OT_recover_crashed_session(Operator):
    """Open the autosave of the session that ended without a clean quit"""

    bl_idname = "mixar.recover_crashed_session"
    bl_label = "Recover Crashed Session"
    bl_options = {'INTERNAL'}

    filepath: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        global _cached
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'WARNING'}, "The crashed session's autosave is gone")
            return {'CANCELLED'}
        result = bpy.ops.wm.recover_auto_save(filepath=self.filepath)
        if 'FINISHED' not in result:
            self.report({'WARNING'}, "Could not open the crashed session's autosave")
            return {'CANCELLED'}
        _cached = False  # recovered: the splash stops offering it this launch
        return {'FINISHED'}


classes = (MIXAR_OT_recover_crashed_session,)
