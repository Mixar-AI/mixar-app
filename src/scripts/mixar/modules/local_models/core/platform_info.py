# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""OS / CPU-arch keys and total-RAM probing for the runtime picker.

The (os_key, arch_key) pair indexes ``constants.RUNTIME_ASSETS``.
``total_ram_bytes()`` is failure-tolerant: any probing error returns 0,
which the catalog treats as "unknown" (no fit warnings) rather than
crashing a panel draw.

No bpy imports — safe on any thread.
"""

import ctypes
import os
import platform
import subprocess
import sys

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Same shape as modules/common/updates/constants.py PLATFORM_MAP.
PLATFORM_MAP = {
    "darwin": "mac",
    "win32": "windows",
    "win": "windows",
    "linux": "linux",
}

_ARCH_MAP = {
    "arm64": "arm64",
    "aarch64": "arm64",
    "x86_64": "x64",
    "amd64": "x64",
}


def os_key(platform_name: str = "") -> str:
    """Mixar OS key ("mac" | "windows" | "linux"), or "" when unknown."""
    raw = (platform_name or sys.platform).lower()
    if raw in PLATFORM_MAP:
        return PLATFORM_MAP[raw]
    for prefix, key in PLATFORM_MAP.items():
        if raw.startswith(prefix):
            return key
    return ""


def arch_key(machine: str = "") -> str:
    """Normalized CPU arch ("arm64" | "x64"), or "" when unknown."""
    raw = (machine or platform.machine()).lower()
    return _ARCH_MAP.get(raw, "")


def platform_key() -> tuple:
    """The (os_key, arch_key) tuple indexing RUNTIME_ASSETS."""
    return (os_key(), arch_key())


def _ram_linux() -> int:
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def _ram_mac() -> int:
    out = subprocess.run(
        ["sysctl", "-n", "hw.memsize"],
        capture_output=True, text=True, timeout=5, check=True,
    )
    return int(out.stdout.strip())


def _ram_windows() -> int:
    class MEMORYSTATUSEX(ctypes.Structure):
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

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0
    return int(status.ullTotalPhys)


def total_ram_bytes() -> int:
    """Total physical RAM in bytes, or 0 when it cannot be determined."""
    key = os_key()
    try:
        if key == "linux":
            return int(_ram_linux())
        if key == "mac":
            return int(_ram_mac())
        if key == "windows":
            return int(_ram_windows())
    except Exception as exc:
        logger.debug("RAM probe failed (%s): %s", key, exc)
    return 0
