# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Python stacks of a native crash: :mod:`faulthandler` into a file per process.

A native crash inside ``python313`` / ``_ctypes`` or any C extension is
triggered by Python code, and Blender's crash log only has the Python stack of
the crashing thread when that thread held the GIL. ``faulthandler`` dumps every
Python thread, the crashing one marked ``Current thread``, from the thread
state the crashing thread owns, GIL or not. The app enables it from
``bootstrap/crash_reports_module.py`` into ``<state>/pyfault-<pid>.txt``, the
render worker from ``worker_main.py`` into its own temp folder; the crash
reporter pairs the file with the crash log on the next launch
(``harvest.pyfault_for``).

Chaining with Blender's own handlers (``creator_signals.cc``, installed by
``main_signal_setup()`` in ``main()`` long before Python starts):

- POSIX: ``faulthandler.enable()`` puts its handler in front with
  ``sigaction(SA_NODEFER)`` and keeps the displaced one; on a fatal signal it
  dumps, restores the displaced handler and ``raise()``s, so Blender's handler
  runs next and writes ``*.crash.txt`` as before. One exception: ``SIGBUS``.
  ``BLI_mmap`` installs a ``SA_SIGINFO`` handler on the first memory-mapped
  ``.blend`` read (``userpref.blend``, before Python starts) that recovers
  I/O faults in mapped files by the fault address. A ``raise()`` carries no
  fault address, so with faulthandler in front a recoverable fault would end
  the app; that handler is put back in front after enabling
  (:func:`_keep_mmap_recovery_first`) and a ``SIGBUS`` crash then has the
  crash log's own Python backtrace only. faulthandler also gives the main
  thread an alternate signal stack (``SA_ONSTACK``, ``2 * SIGSTKSZ``: 16 KB
  on Linux); Blender's handler, chained from it, would run there too, and it
  does far more (backtrace, file I/O, temp purge) than that stack was sized
  for. The alternate stack is put back as it was (none,
  :func:`_restore_alt_stack`): both handlers run on the thread's own stack,
  as Blender's always did. The crash log's native stack then shows the
  re-raise between two trampolines; ``parse_crash_txt`` drops it.
- Windows: a vectored exception handler that dumps and returns
  ``EXCEPTION_CONTINUE_SEARCH``, so Blender's unhandled-exception filter
  still runs. faulthandler also installs CRT ``signal()`` handlers: the CRT's
  start-up frame filter would call them for an illegal instruction or a
  divide by zero, and their re-``raise()`` under ``SIG_DFL`` is ``_exit(3)``,
  which never reaches Blender's filter (no crash log). They are put back to
  ``SIG_DFL`` (:func:`_restore_windows_crt`); the vectored handler dumps
  every exception code on its own. It also dumps first-chance exceptions that
  something then handles, so the file can hold dumps that were no crash: the
  harvester takes the last dump and checks its exception against the crash
  log's, and the reporter empties the file past ``PYFAULT_MAX_BYTES``.

Nothing is enabled when faulthandler already is (``-X faulthandler``,
``PYTHONFAULTHANDLER``): that owner keeps it. A clean exit disables it and
deletes the file (:func:`disable`).
"""

from __future__ import annotations

import faulthandler
import os
import sys

from ..constants import PYFAULT_PREFIX, PYFAULT_SUFFIX

_file = None
_path: str | None = None


def file_name(pid: int) -> str:
    return f"{PYFAULT_PREFIX}{pid}{PYFAULT_SUFFIX}"


def path() -> str | None:
    """This process's dump file, while faulthandler writes to it."""
    return _path


def enable(directory: str, pid: int | None = None) -> str | None:
    """Dump the Python stacks of a native crash into ``<directory>/pyfault-<pid>.txt``.

    Main thread only (Windows resets CRT signal handlers). Returns the file's
    path, or None when faulthandler is someone else's or could not start.
    """
    global _file, _path
    if _file is not None:
        return _path
    if faulthandler.is_enabled():
        return None
    target = os.path.join(directory, file_name(pid or os.getpid()))
    try:
        os.makedirs(directory, exist_ok=True)
        handle = open(target, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return None
    sigbus = _sigbus_action()
    alt_stack = _alt_stack()
    crt_default = _crt_default_signals()
    try:
        faulthandler.enable(file=handle, all_threads=True)
    except Exception:  # noqa: BLE001 - no Python stack, never a broken start-up
        handle.close()
        _unlink(target)
        return None
    _file, _path = handle, target
    _keep_mmap_recovery_first(sigbus)
    _restore_alt_stack(alt_stack)
    _restore_windows_crt(crt_default)
    return target


def disable(remove: bool = True) -> None:
    """A clean exit: stop dumping, close the file and (by default) delete it."""
    global _file, _path
    handle, target = _file, _path
    if handle is None:
        return
    _file = _path = None
    try:
        faulthandler.disable()
    except Exception:  # noqa: BLE001
        pass
    try:
        handle.close()
    except OSError:
        pass
    if remove and target:
        _unlink(target)


def _unlink(target: str) -> None:
    try:
        os.unlink(target)
    except OSError:
        pass


# POSIX: SIGBUS stays with BLI_mmap's recovery ------------------------------

def _libc():
    import ctypes

    return ctypes.CDLL(None, use_errno=True)


def _sigaction_layout() -> tuple[int, int] | None:
    """(offset of ``sa_flags`` in ``struct sigaction``, ``SA_SIGINFO``)."""
    import ctypes

    if ctypes.sizeof(ctypes.c_void_p) != 8:
        return None
    if sys.platform == "darwin":
        return 12, 0x40  # handler, sigset_t (u32), int flags
    if sys.platform.startswith("linux"):
        return 136, 0x4  # handler, sigset_t (128 bytes), int flags, restorer
    return None


def _sigbus_action():
    """The current ``SIGBUS`` action when it is a ``SA_SIGINFO`` handler (BLI_mmap's
    fault-address recovery), else None. Blender's crash handler uses ``signal()``."""
    import signal

    layout = _sigaction_layout()
    if os.name == "nt" or layout is None or not hasattr(signal, "SIGBUS"):
        return None
    try:
        import ctypes

        action = ctypes.create_string_buffer(256)
        if _libc().sigaction(int(signal.SIGBUS), None, action) != 0:
            return None
    except Exception:  # noqa: BLE001
        return None
    offset, siginfo = layout
    flags = int.from_bytes(action.raw[offset:offset + 4], sys.byteorder)
    return action if flags & siginfo else None


def _keep_mmap_recovery_first(action) -> None:
    if action is None:
        return
    import signal

    try:
        _libc().sigaction(int(signal.SIGBUS), action, None)
    except Exception:  # noqa: BLE001
        pass


def _stack_t():
    """``stack_t`` for this platform, with its ``SS_DISABLE``, or None."""
    import ctypes

    if ctypes.sizeof(ctypes.c_void_p) != 8:
        return None
    if sys.platform == "darwin":
        fields = [("ss_sp", ctypes.c_void_p), ("ss_size", ctypes.c_size_t), ("ss_flags", ctypes.c_int)]
        disable = 4
    elif sys.platform.startswith("linux"):
        fields = [("ss_sp", ctypes.c_void_p), ("ss_flags", ctypes.c_int), ("ss_size", ctypes.c_size_t)]
        disable = 2
    else:
        return None
    return type("stack_t", (ctypes.Structure,), {"_fields_": fields}), disable


def _alt_stack():
    """This thread's alternate signal stack before faulthandler adds its own."""
    layout = _stack_t()
    if os.name == "nt" or layout is None:
        return None
    try:
        import ctypes

        current = layout[0]()
        if _libc().sigaltstack(None, ctypes.byref(current)) != 0:
            return None
        return current
    except Exception:  # noqa: BLE001
        return None


def _restore_alt_stack(before) -> None:
    """Put the main thread's alternate signal stack back (usually: none)."""
    if before is None:
        return
    try:
        import ctypes

        stack_type, disable = _stack_t()
        if before.ss_flags & disable or not before.ss_sp:
            # macOS refuses SS_DISABLE with a size below MINSIGSTKSZ (ENOMEM).
            size = 1 << 17
            before = stack_type(None, size, disable) if sys.platform == "darwin" else stack_type(None, disable, size)
        _libc().sigaltstack(ctypes.byref(before), None)
    except Exception:  # noqa: BLE001
        pass


# Windows: the vectored handler only, never the CRT signal() handlers --------

def _crt_default_signals() -> tuple:
    if os.name != "nt":
        return ()
    import signal

    out = []
    for name in ("SIGSEGV", "SIGILL", "SIGFPE"):
        number = getattr(signal, name, None)
        try:
            if number is not None and signal.getsignal(number) == signal.SIG_DFL:
                out.append(number)
        except (ValueError, OSError):
            continue
    return tuple(out)


def _restore_windows_crt(signals: tuple) -> None:
    import signal

    for number in signals:
        try:
            signal.signal(number, signal.SIG_DFL)
        except (ValueError, OSError):
            continue
