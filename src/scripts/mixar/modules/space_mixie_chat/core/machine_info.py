# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The machine block this client reports in ``system.handshake``.

The backend sizes the agent's geometry budget from it: how many unique faces a
scene may hold before a Cycles render is a memory risk on THIS machine. Without
it the backend assumes 16 GB, which is what a build on a 32/64 GB workstation
would be needlessly held to.

Pure and defensive: `psutil` is not in the embedded Python, so RAM comes from
`sysconf` on macOS/Linux and `GlobalMemoryStatusEx` on Windows, and every value
is `None` rather than an exception. Nothing here may ever fail a handshake.
"""

import ctypes
import os
import sys

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def physical_memory_bytes():
    """Installed RAM in bytes, or None when the platform will not say."""
    try:
        if sys.platform == "win32":
            return _windows_memory_bytes()
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        total = int(pages) * int(page_size)
        return total if total > 0 else None
    except Exception:  # noqa: BLE001 — a missing sysconf name is not an error here
        return None


def _windows_memory_bytes():
    """``GlobalMemoryStatusEx().ullTotalPhys``; None if the call fails."""

    class _MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    total = int(status.ullTotalPhys)
    return total if total > 0 else None


def gpu_memory_bytes():
    """Dedicated VRAM in bytes — currently always None, and the field is declared
    so the wire shape does not change when a source for it exists.

    Blender exposes no VRAM query (`gpu.capabilities` reports limits, not size,
    and the Cycles device preferences list devices without their memory), and on
    Apple silicon there is no separate pool at all: the GPU allocates out of the
    same RAM, which is exactly why a Cycles scene build can get the process
    killed. None is the honest answer here, not a gap — the budget is derived
    from `memory_bytes`.
    """
    return None


def machine_block():
    """``{"memory_bytes", "gpu_memory_bytes", "platform"}`` for the handshake."""
    block = {
        "memory_bytes": physical_memory_bytes(),
        "gpu_memory_bytes": gpu_memory_bytes(),
        "platform": sys.platform,
    }
    if block["memory_bytes"] is None:
        logger.debug("Machine memory unavailable; the backend will assume 16 GB")
    return block
