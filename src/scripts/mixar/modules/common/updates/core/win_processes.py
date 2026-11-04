# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Processes Holding the Windows Install

Before quitting for an update, the app asks which OTHER processes run a
binary from its install directory. Windows Installer cannot replace a file
in use: it schedules the replacement for the next reboot, reports 3010 and
the relaunch starts the old build.

Each holder is classified by what the user can do about it:

- ``MIXAR_WINDOW`` — another Mixar with a visible window; the user closes it.
- ``CONNECTOR`` — the Mixar connector (MCP server, ``<install>\\python\\bin\\
  python.exe``) kept running by a live AI app such as Claude, Codex or
  Cursor, named after that app. It is a stateless forwarder whose cached
  port and token are stale once Mixar restarts, so the update ends it (the
  AI app respawns or reconnects it); one that cannot be ended is named.
- ``BACKGROUND`` — Mixar's own work: our descendants, a windowless Mixar
  (the asset-preview backfill ``mixar.exe -b`` an earlier session left
  running, indexing render shards) or a python started by a Mixar. It ends
  by itself, so the update waits for it.
- ``ABANDONED_CONNECTOR`` — a connector whose AI app is gone. It holds no
  user work, so the update ends it.
- ``OTHER`` — anything else from the install directory, named by basename.

Our own ancestors are left out: a launcher waiting on us ends with us.

The table comes straight from Win32 — a Toolhelp snapshot, each process's
image path and creation time, the owners of visible top-level windows — in
a few tens of milliseconds and without a subprocess, because it runs on the
UI thread. A parent link counts only while the parent is alive and not
younger than the child, so a reused PID never adopts an orphan. Only
basenames ever leave this module. Any failure answers "nothing found": the
helper's own wait still guards the install.
"""

import logging
import ntpath
import time
from collections import namedtuple
from functools import lru_cache

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_MIXAR_BINARIES = frozenset({
    "mixar.exe", "mixar-launcher.exe", "blender.exe", "blender-launcher.exe",
})
# Shells between an AI app and the connector's python.exe; the first
# ancestor that is not one of these is the app to name.
_SHELLS = frozenset({"cmd.exe", "conhost.exe", "powershell.exe", "pwsh.exe"})
_MAX_DEPTH = 16

# Holder kinds.
MIXAR_WINDOW = "mixar"
CONNECTOR = "connector"
BACKGROUND = "background"
ABANDONED_CONNECTOR = "abandoned_connector"
OTHER = "other"
# What Restart & Update stops for and names: what only the user can end,
# plus a connector that could not be ended (named after its AI app).
USER_CLOSABLE = frozenset({MIXAR_WINDOW, CONNECTOR, OTHER})
# Ended before quitting: they hold no user work.
ENDED_BY_UPDATE = frozenset({CONNECTOR, ABANDONED_CONNECTOR})

# One process holding the install directory. ``name`` is what a toast may
# show (a basename, "Mixar", or the AI app hosting a connector); ``created``
# re-identifies ``pid`` before it is ended.
Holder = namedtuple("Holder", "kind name pid created")

_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_INVALID_PARAMETER = 87  # OpenProcess on a PID that no longer exists
_STILL_ACTIVE = 259  # GetExitCodeProcess of a process that has not exited
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_PATH_CHARS = 32768
_SLOW_CHECK_MS = 50


# ============================================================================
# Classification (pure)
# ============================================================================


def _is_within(path: str, root: str) -> bool:
    from .app_paths import is_within

    return is_within(path, root)


def _strip_exe(name: str) -> str:
    return name[:-4] if name.lower().endswith(".exe") else name


def classify(rows, install_dir: str, own_pid: int) -> list:
    """A :data:`Holder` for each other process running from *install_dir*.

    *rows* are :func:`_process_table` dicts. Pure, so it is tested with
    canned tables.
    """
    by_pid = {}
    for row in rows:
        try:
            by_pid[int(row["pid"])] = row
        except (KeyError, TypeError, ValueError):
            continue

    def parent(pid):
        """The live parent of *pid*; None when it is gone or its PID was reused."""
        row = by_pid[pid]
        try:
            ppid = int(row.get("ppid") or 0)
        except (TypeError, ValueError):
            return None
        up = by_pid.get(ppid)
        if not ppid or ppid == pid or up is None:
            return None
        # "Not younger" rather than "older": creation times move in system
        # clock ticks, and a shell and the python it starts at once can
        # share one. A reused PID belongs to a process started later.
        mine, theirs = row.get("created"), up.get("created")
        if mine is not None and theirs is not None and theirs > mine:
            return None
        return ppid

    def ancestors(pid):
        chain = []
        up = parent(pid)
        while up is not None and up not in chain and len(chain) < _MAX_DEPTH:
            chain.append(up)
            up = parent(up)
        return chain

    own_ancestors = set(ancestors(own_pid)) if own_pid in by_pid else set()
    holders = []
    for pid, row in by_pid.items():
        path = row.get("path") or ""
        if pid == own_pid or pid in own_ancestors or not _is_within(path, install_dir):
            continue
        name = ntpath.basename(path)
        lineage = ancestors(pid)
        if own_pid in lineage:
            kind = BACKGROUND
        elif name.lower() in _MIXAR_BINARIES:
            kind, name = (MIXAR_WINDOW, "Mixar") if row.get("has_window") else (BACKGROUND, name)
        elif name.lower().startswith("python"):
            kind, name = _python_holder(name, lineage, by_pid, install_dir)
        else:
            kind = OTHER
        holders.append(Holder(kind, name, pid, row.get("created")))
    return holders


def _python_holder(name, lineage, by_pid, install_dir):
    """``(kind, name)`` for a python from the install dir, judged by who started it."""
    for pid in lineage:
        row = by_pid[pid]
        host = str(row.get("name") or "")
        if host.lower() in _MIXAR_BINARIES:
            return BACKGROUND, name
        if host.lower() in _SHELLS or _is_within(row.get("path") or "", install_dir):
            continue
        return CONNECTOR, _strip_exe(host)
    return ABANDONED_CONNECTOR, name


# ============================================================================
# Win32
# ============================================================================


@lru_cache(maxsize=1)
def _win32():
    """kernel32/user32 entry points with their signatures (Windows only)."""
    import ctypes
    from ctypes import wintypes
    from types import SimpleNamespace

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    handle, entry = wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)
    filetime = ctypes.POINTER(wintypes.FILETIME)
    for func, argtypes, restype in (
        (kernel32.CreateToolhelp32Snapshot, [wintypes.DWORD, wintypes.DWORD], handle),
        (kernel32.Process32FirstW, [handle, entry], wintypes.BOOL),
        (kernel32.Process32NextW, [handle, entry], wintypes.BOOL),
        (kernel32.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], handle),
        (kernel32.QueryFullProcessImageNameW,
         [handle, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)],
         wintypes.BOOL),
        (kernel32.GetProcessTimes, [handle, filetime, filetime, filetime, filetime],
         wintypes.BOOL),
        (kernel32.TerminateProcess, [handle, wintypes.UINT], wintypes.BOOL),
        (kernel32.GetExitCodeProcess, [handle, ctypes.POINTER(wintypes.DWORD)],
         wintypes.BOOL),
        (kernel32.CloseHandle, [handle], wintypes.BOOL),
        (user32.EnumWindows, [enum_proc, wintypes.LPARAM], wintypes.BOOL),
        (user32.IsWindowVisible, [wintypes.HWND], wintypes.BOOL),
        (user32.GetWindowLongW, [wintypes.HWND, ctypes.c_int], wintypes.LONG),
        (user32.GetWindowRect, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
        (user32.GetWindowThreadProcessId,
         [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
    ):
        func.argtypes, func.restype = argtypes, restype
    return SimpleNamespace(
        ctypes=ctypes, wintypes=wintypes, kernel32=kernel32, user32=user32,
        PROCESSENTRY32W=PROCESSENTRY32W, enum_proc=enum_proc,
        invalid_handle=ctypes.c_void_p(-1).value,
    )


def _created(w, handle):
    """Creation time of the process behind *handle* (FILETIME ticks), or None."""
    times = [w.wintypes.FILETIME() for _ in range(4)]
    if not w.kernel32.GetProcessTimes(handle, *(w.ctypes.byref(t) for t in times)):
        return None
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def _image(w, pid, buffer):
    """``(full image path, creation time)``; ``(None, None)`` when access is denied."""
    handle = w.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None, None
    try:
        size = w.wintypes.DWORD(len(buffer))
        ok = w.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, w.ctypes.byref(size))
        return (buffer.value if ok else None), _created(w, handle)
    finally:
        w.kernel32.CloseHandle(handle)


def _windowed_pids(w) -> set:
    """PIDs owning a visible, non-tool top-level window with a size."""
    pids = set()
    rect = w.wintypes.RECT()
    owner = w.wintypes.DWORD()

    def visit(hwnd, _lparam):
        try:
            if (w.user32.IsWindowVisible(hwnd)
                    and not w.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOOLWINDOW
                    and w.user32.GetWindowRect(hwnd, w.ctypes.byref(rect))
                    and rect.right > rect.left and rect.bottom > rect.top):
                w.user32.GetWindowThreadProcessId(hwnd, w.ctypes.byref(owner))
                pids.add(owner.value)
        except Exception:  # noqa: BLE001 - a raising callback would end the walk
            pass
        return True

    w.user32.EnumWindows(w.enum_proc(visit), 0)
    return pids


def _process_table() -> list:
    """Every process as ``{pid, ppid, name, path, created, has_window}``.

    ``path`` and ``created`` are None where Windows denies access (another
    account's or a protected process): such a process can still be an
    ancestor, never a holder.
    """
    w = _win32()
    windowed = _windowed_pids(w)
    snapshot = w.kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == w.invalid_handle:
        raise OSError(w.ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    rows = []
    try:
        entry = w.PROCESSENTRY32W()
        entry.dwSize = w.ctypes.sizeof(entry)
        buffer = w.ctypes.create_unicode_buffer(_PATH_CHARS)
        more = w.kernel32.Process32FirstW(snapshot, w.ctypes.byref(entry))
        while more:
            pid = int(entry.th32ProcessID)
            path, created = _image(w, pid, buffer)
            rows.append({
                "pid": pid, "ppid": int(entry.th32ParentProcessID),
                "name": entry.szExeFile, "path": path, "created": created,
                "has_window": pid in windowed,
            })
            more = w.kernel32.Process32NextW(snapshot, w.ctypes.byref(entry))
    finally:
        w.kernel32.CloseHandle(snapshot)
    return rows


# ============================================================================
# Public API
# ============================================================================


def blocking_apps(install_dir: str, own_pid: int) -> list:
    """:data:`Holder` list for *install_dir*; ``[]`` when unknown."""
    if not install_dir:
        return []
    try:
        started = time.perf_counter()
        rows = _process_table()
        holders = classify(rows, install_dir, own_pid)
    except Exception as e:  # noqa: BLE001 - never block an update on this check
        logger.warning("Could not list processes using the install directory: %s", e)
        return []
    elapsed_ms = (time.perf_counter() - started) * 1000
    # It runs on the UI thread (every few seconds while waiting): only a
    # slow check is worth an info line.
    logger.log(
        logging.INFO if elapsed_ms > _SLOW_CHECK_MS else logging.DEBUG,
        "Install-dir check: %d processes in %.0f ms, holders %s", len(rows), elapsed_ms,
        [(holder.kind, holder.name, holder.pid) for holder in holders],
    )
    return holders


def process_state(pid: int):
    """``(alive, created)`` for *pid* (Windows).

    ``alive`` is False once the process has exited (or the PID was never
    used); ``created`` is its creation time in FILETIME ticks, None when
    Windows denies access — the process then counts as alive. Raises when
    the Win32 calls themselves fail; callers decide what that means.
    """
    w = _win32()
    handle = w.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return w.ctypes.get_last_error() != _ERROR_INVALID_PARAMETER, None
    try:
        code = w.wintypes.DWORD()
        # An exited process lives on while someone holds a handle to it.
        if (w.kernel32.GetExitCodeProcess(handle, w.ctypes.byref(code))
                and code.value != _STILL_ACTIVE):
            return False, None
        return True, _created(w, handle)
    finally:
        w.kernel32.CloseHandle(handle)


def terminate(holder) -> bool:
    """End *holder*'s process (Windows). True once it is gone.

    The PID is re-identified by its creation time first, so a process that
    reused it since the snapshot is never ended in its place.
    """
    try:
        w = _win32()
        handle = w.kernel32.OpenProcess(
            _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION, False, int(holder.pid))
        if not handle:
            return w.ctypes.get_last_error() == _ERROR_INVALID_PARAMETER
        try:
            if holder.created is not None and _created(w, handle) != holder.created:
                return True  # the process we classified has already exited
            return bool(w.kernel32.TerminateProcess(handle, 1))
        finally:
            w.kernel32.CloseHandle(handle)
    except Exception as e:  # noqa: BLE001 - reported to the caller as "still running"
        logger.debug("Could not end pid %s: %s", getattr(holder, "pid", "?"), e)
        return False
