# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parent side: whether a second copy of the document fits in memory.

A worker opens a snapshot of the whole document, so it needs about as much
memory as the app holds now (measured: a 1.9 GB file, 6.5 GB resident in the
app, 6.3 GB in its worker). Before a job goes to a worker, :func:`worker_fits`
compares this process's resident memory with what the system has available:

- the worker is used when available >= resident x :data:`HEADROOM` and the
  app holds less than :data:`MAX_RESIDENT_BYTES`;
- otherwise the caller runs the job in-process, as before the worker existed;
- memory that cannot be read keeps the worker (today's behaviour).

Readers are ctypes / procfs calls (well under a millisecond), never a
subprocess: this runs on the main thread, once per job. No ``bpy``.
"""

import ctypes
import os
import sys

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

#: Above this the app is too big to copy (about a 3-4 GB file).
MAX_RESIDENT_BYTES = 8 * 1024 ** 3
#: The worker's copy plus room for the render and the app's own growth.
HEADROOM = 1.25
_GB = float(1024 ** 3)


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------

class _ProcTaskInfo(ctypes.Structure):
    # <sys/proc_info.h> struct proc_taskinfo
    _fields_ = [("pti_virtual_size", ctypes.c_uint64), ("pti_resident_size", ctypes.c_uint64),
                ("pti_total_user", ctypes.c_uint64), ("pti_total_system", ctypes.c_uint64),
                ("pti_threads_user", ctypes.c_uint64), ("pti_threads_system", ctypes.c_uint64),
                ("pti_policy", ctypes.c_int32), ("pti_faults", ctypes.c_int32),
                ("pti_pageins", ctypes.c_int32), ("pti_cow_faults", ctypes.c_int32),
                ("pti_messages_sent", ctypes.c_int32), ("pti_messages_received", ctypes.c_int32),
                ("pti_syscalls_mach", ctypes.c_int32), ("pti_syscalls_unix", ctypes.c_int32),
                ("pti_csw", ctypes.c_int32), ("pti_threadnum", ctypes.c_int32),
                ("pti_numrunning", ctypes.c_int32), ("pti_priority", ctypes.c_int32)]


class _VMStatistics64(ctypes.Structure):
    # <mach/vm_statistics.h> struct vm_statistics64 (natural_t = uint32)
    _fields_ = [("free_count", ctypes.c_uint32), ("active_count", ctypes.c_uint32),
                ("inactive_count", ctypes.c_uint32), ("wire_count", ctypes.c_uint32),
                ("zero_fill_count", ctypes.c_uint64), ("reactivations", ctypes.c_uint64),
                ("pageins", ctypes.c_uint64), ("pageouts", ctypes.c_uint64),
                ("faults", ctypes.c_uint64), ("cow_faults", ctypes.c_uint64),
                ("lookups", ctypes.c_uint64), ("hits", ctypes.c_uint64),
                ("purges", ctypes.c_uint64), ("purgeable_count", ctypes.c_uint32),
                ("speculative_count", ctypes.c_uint32), ("decompressions", ctypes.c_uint64),
                ("compressions", ctypes.c_uint64), ("swapins", ctypes.c_uint64),
                ("swapouts", ctypes.c_uint64), ("compressor_page_count", ctypes.c_uint32),
                ("throttled_count", ctypes.c_uint32), ("external_page_count", ctypes.c_uint32),
                ("internal_page_count", ctypes.c_uint32),
                ("total_uncompressed_pages_in_compressor", ctypes.c_uint64)]


_PROC_PIDTASKINFO = 4
_HOST_VM_INFO64 = 4


def _libc():
    return ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)


def _darwin_resident():
    libc = _libc()
    info = _ProcTaskInfo()
    size = ctypes.sizeof(info)
    libc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p,
                                  ctypes.c_int]
    if libc.proc_pidinfo(os.getpid(), _PROC_PIDTASKINFO, 0, ctypes.byref(info), size) != size:
        return None
    return int(info.pti_resident_size)


def _darwin_available():
    """Free + inactive + purgeable pages: what the system can hand a new
    process without paging out anyone's working set."""
    libc = _libc()
    libc.mach_host_self.restype = ctypes.c_uint32
    host = libc.mach_host_self()
    try:
        stats = _VMStatistics64()
        count = ctypes.c_uint32(ctypes.sizeof(stats) // ctypes.sizeof(ctypes.c_int32))
        libc.host_statistics64.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p,
                                           ctypes.POINTER(ctypes.c_uint32)]
        if libc.host_statistics64(host, _HOST_VM_INFO64, ctypes.byref(stats),
                                  ctypes.byref(count)) != 0:
            return None
        page = ctypes.c_size_t(0)
        libc.host_page_size.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_size_t)]
        if libc.host_page_size(host, ctypes.byref(page)) != 0 or not page.value:
            return None
        pages = int(stats.free_count) + int(stats.inactive_count) + int(stats.purgeable_count)
        return pages * int(page.value)
    finally:
        try:  # mach_host_self() hands out a send right each call
            task = ctypes.c_uint32.in_dll(libc, "mach_task_self_").value
            libc.mach_port_deallocate(task, host)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------

def _linux_resident():
    with open("/proc/self/statm", encoding="ascii") as handle:
        fields = handle.read().split()
    return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")


def _linux_available():
    with open("/proc/meminfo", encoding="ascii") as handle:
        for line in handle:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    return None


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64)]


def _windows_resident():
    kernel32 = ctypes.WinDLL("kernel32")
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters),
                                            counters.cb):
        return None
    return int(counters.WorkingSetSize)


def _windows_available():
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullAvailPhys)


_READERS = {"darwin": (_darwin_resident, _darwin_available),
            "linux": (_linux_resident, _linux_available),
            "win32": (_windows_resident, _windows_available)}


def _read(reader):
    try:
        value = reader()
    except Exception:
        return None
    return int(value) if value is not None and value > 0 else None


def readings():
    """``(resident_bytes, available_bytes)``; either is None when unreadable."""
    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    readers = _READERS.get(platform)
    if readers is None:
        return None, None
    return _read(readers[0]), _read(readers[1])


def decide(resident, available):
    """``(use_worker, reason)`` for the given readings (pure)."""
    if resident is None or available is None:
        return True, "memory_unknown"
    if resident >= MAX_RESIDENT_BYTES:
        return False, "document_too_large"
    if available < resident * HEADROOM:
        return False, "low_memory"
    return True, "fits"


def worker_fits(kind: str) -> bool:
    """Whether a ``kind`` job should go to a worker; logs the decision."""
    resident, available = readings()
    use_worker, reason = decide(resident, available)
    logger.info("Render worker %s: %s (%s; resident %s, available %s)",
                kind, "worker" if use_worker else "in-process", reason, _gb(resident),
                _gb(available))
    return use_worker


def _gb(value) -> str:
    return "unknown" if value is None else "%.2f GB" % (value / _GB)
