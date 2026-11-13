# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
macOS: What Else Runs From the App Bundle

An update nobody is watching (on quit, at launch) must not swap the
bundle under another Mixar: that instance would keep running old code
that lazily loads files from the new bundle. This answers "who else runs
from ``/Applications/Mixar.app``?" from the kernel's process table
(``libproc``: ``proc_listallpids``, ``proc_pidpath``, ``proc_pidinfo``)
— no subprocess, a few milliseconds, safe on the quit path.

Not holders: this process and its ancestors; its descendants (render
workers, sandbox children, the local model server), which normally end
as Mixar quits — the helper waits, bounded, for any that outlive it
before the swap (:mod:`mac_installer`); and a Mixar connector — a python an AI app runs as its MCP
server — which holds no user work and reconnects to the updated app.
Everything else from the bundle is: another Mixar first of all.

Reads only; imports no ``bpy``.
"""

import ctypes
import os
import struct
from collections import namedtuple

# proc_pidinfo(PROC_PIDTBSDINFO) answers a struct proc_bsdinfo (136
# bytes): pbi_ppid at offset 16, pbi_start_tvsec / pbi_start_tvusec (two
# uint64) at 120. Another account's process answers nothing; its path is
# still readable.
_PROC_PIDTBSDINFO = 3
_BSDINFO_SIZE = 136
_PPID_OFFSET = 16
_START_OFFSET = 120
_PATH_MAX = 4096
_MAX_DEPTH = 64

MIXAR = "mixar"            # another Mixar app
BACKGROUND = "background"  # anything else running from the bundle

Holder = namedtuple("Holder", "kind name pid")


def _libc():
    return ctypes.CDLL(None, use_errno=True)


def process_table():
    """``[{"pid", "ppid", "path", "created"}]`` for every readable process.

    ``ppid``/``created`` are None for another account's process. Raises
    OSError when the table itself cannot be read.
    """
    libc = _libc()
    count = libc.proc_listallpids(None, 0)
    if count <= 0:
        raise OSError(ctypes.get_errno(), "proc_listallpids failed")
    pids = (ctypes.c_int * (count + 64))()
    count = libc.proc_listallpids(pids, ctypes.sizeof(pids))
    if count <= 0:
        raise OSError(ctypes.get_errno(), "proc_listallpids failed")

    path = ctypes.create_string_buffer(_PATH_MAX)
    info = ctypes.create_string_buffer(_BSDINFO_SIZE)
    rows = []
    for pid in pids[:count]:
        if pid <= 0 or libc.proc_pidpath(pid, path, _PATH_MAX) <= 0:
            continue
        row = {"pid": pid, "ppid": None, "created": None,
               "path": os.fsdecode(path.value)}
        if libc.proc_pidinfo(pid, _PROC_PIDTBSDINFO, ctypes.c_uint64(0),
                             info, _BSDINFO_SIZE) == _BSDINFO_SIZE:
            row["ppid"] = struct.unpack_from("=I", info.raw, _PPID_OFFSET)[0]
            seconds, micros = struct.unpack_from("=QQ", info.raw, _START_OFFSET)
            row["created"] = seconds + micros / 1e6
        rows.append(row)
    return rows


def _within(path, bundle) -> bool:
    root = bundle.rstrip("/") + "/"
    return bool(path) and path.startswith(root)


def classify(rows, bundle, own_pid):
    """A :data:`Holder` for each process that blocks a silent install.

    Pure, so it is tested with canned tables.
    """
    by_pid = {row["pid"]: row for row in rows if isinstance(row.get("pid"), int)}

    def parent(pid):
        row = by_pid[pid]
        ppid = row.get("ppid")
        up = by_pid.get(ppid) if ppid else None
        if up is None or ppid == pid:
            return None
        # A reused PID belongs to a process started after its "child".
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
        if pid == own_pid or pid in own_ancestors or not _within(path, bundle):
            continue
        if own_pid in ancestors(pid):
            continue  # ours: ends as Mixar quits
        name = os.path.basename(path)
        if name.lower().startswith("python"):
            continue  # a Mixar connector
        relative = path[len(bundle.rstrip("/")) + 1:]
        kind = MIXAR if relative.startswith("Contents/MacOS/") else BACKGROUND
        holders.append(Holder(kind, "Mixar" if kind == MIXAR else name, pid))
    return holders


def blocking_apps(bundle, own_pid):
    """:func:`classify` over the live process table. Raises when unreadable."""
    return classify(process_table(), bundle, own_pid)
