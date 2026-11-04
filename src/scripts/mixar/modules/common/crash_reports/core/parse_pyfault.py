# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parse :mod:`faulthandler`'s dump (``pyfault-<pid>.txt``, see ``pyfault.py``).

One dump per fatal signal / Windows exception::

    Fatal Python error: Segmentation fault          (POSIX)
    Windows fatal exception: access violation       (Windows)

    Current thread 0x00007ff8 (most recent call first):
      File "<path>", line 12 in render_preview
      File "<path>", line 90 in _tick

    Thread 0x00007ff9 (most recent call first):
      File "<path>", line 3 in run

    Extension modules: numpy.core._multiarray_umath, ... (total: 12)

Python 3.14 adds the thread name: ``Current thread 0x… [MainThread] (…)``.
Only the last dump counts (Windows also dumps first-chance exceptions that are
then handled; the crash is the last thing written), and only the crashing
thread (``Current thread``): its frames innermost LAST, as a Python traceback
prints them, files reduced by ``scrub.python_stack_file``.
"""

from __future__ import annotations

import re

from ..constants import MAX_PYTHON_STACK
from .scrub import python_stack_file

_HEADER = re.compile(r"^(?:Fatal Python error: (?P<signal>.+?)|Windows fatal exception: (?P<exception>.+?))\s*$")
_THREAD = re.compile(
    r"^(?P<current>Current thread|Thread) (?P<id>0x[0-9a-fA-F]+)(?: \[(?P<name>[^\]]*)\])?"
    r" \(most recent call first\):\s*$"
)
_THREAD_NAME = re.compile(r"^[A-Za-z_][\w.\-]{0,63}$")
_STACK = re.compile(r"^Stack \(most recent call first\):\s*$")
_FRAME = re.compile(r'^\s+File "(?P<file>.*)", line (?P<line>\d+|\?\?\?) in (?P<function>.+?)\s*$')

# Windows exception codes: crash.txt's ExceptionCode name, faulthandler's text.
_WINDOWS_TEXT = {
    "EXCEPTION_ACCESS_VIOLATION": "access violation",
    "EXCEPTION_FLT_DIVIDE_BY_ZERO": "float divide by zero",
    "EXCEPTION_FLT_OVERFLOW": "float overflow",
    "EXCEPTION_INT_DIVIDE_BY_ZERO": "int divide by zero",
    "EXCEPTION_INT_OVERFLOW": "integer overflow",
    "EXCEPTION_IN_PAGE_ERROR": "page error",
    "EXCEPTION_STACK_OVERFLOW": "stack overflow",
}
_WINDOWS_CODES = {
    "EXCEPTION_DATATYPE_MISALIGNMENT": 0x80000002,
    "EXCEPTION_BREAKPOINT": 0x80000003,
    "EXCEPTION_SINGLE_STEP": 0x80000004,
    "EXCEPTION_ARRAY_BOUNDS_EXCEEDED": 0xC000008C,
    "EXCEPTION_FLT_DENORMAL_OPERAND": 0xC000008D,
    "EXCEPTION_FLT_INEXACT_RESULT": 0xC000008F,
    "EXCEPTION_FLT_INVALID_OPERATION": 0xC0000090,
    "EXCEPTION_FLT_STACK_CHECK": 0xC0000092,
    "EXCEPTION_FLT_UNDERFLOW": 0xC0000093,
    "EXCEPTION_PRIV_INSTRUCTION": 0xC0000096,
    "EXCEPTION_ILLEGAL_INSTRUCTION": 0xC000001D,
    "EXCEPTION_NONCONTINUABLE_EXCEPTION": 0xC0000025,
    "EXCEPTION_INVALID_DISPOSITION": 0xC0000026,
    "EXCEPTION_GUARD_PAGE": 0x80000001,
    "EXCEPTION_INVALID_HANDLE": 0xC0000008,
}
# POSIX signals: the crash type, faulthandler's names. crash.txt calls SIGBUS SIGSEGV.
_SIGNALS = {
    "SIGSEGV": ("Segmentation fault", "Bus error"),
    "SIGBUS": ("Segmentation fault", "Bus error"),
    "SIGABRT": ("Aborted",),
    "SIGILL": ("Illegal instruction",),
    "SIGFPE": ("Floating-point exception",),
    "SIGTRAP": (),
    "SIGKILL": (),
}


def _blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    for line in text.splitlines():
        if _HEADER.match(line):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
    return blocks


def matches(header: str, crash_type: str | None) -> bool:
    """Whether a dump's header (``Windows fatal exception: access violation``)
    can be the crash a crash file records (``EXCEPTION_ACCESS_VIOLATION``)."""
    match = _HEADER.match(header or "")
    if not match:
        return False
    kind = (crash_type or "").strip().upper()
    if match.group("exception") is not None:
        text = match.group("exception").strip().lower()
        if not kind.startswith("EXCEPTION_"):
            return not kind  # a Windows dump never belongs to a POSIX crash
        if kind in _WINDOWS_TEXT:
            return text == _WINDOWS_TEXT[kind]
        if text.startswith("code 0x"):
            code = _WINDOWS_CODES.get(kind)
            return code is None or int(text[len("code "):], 16) == code
        return False
    if kind.startswith("EXCEPTION_"):
        return False
    names = _SIGNALS.get(kind)
    return True if names is None else match.group("signal").strip() in names


def parse_pyfault(text: str, crash_type: str | None = None) -> dict | None:
    """``{"python_stack", "python_thread", "header"}`` of the last dump, or None
    when there is none, it is not this crash's, or no thread was current."""
    blocks = _blocks(text or "")
    if not blocks:
        return None
    block = blocks[-1]
    if crash_type is not None and not matches(block[0], crash_type):
        return None
    thread = None
    frames: list[dict] = []
    current = False
    for line in block[1:]:
        heading = _THREAD.match(line)
        if heading:
            if current:
                break
            current = heading.group("current") == "Current thread"
            if current:
                thread = heading.group("id")
                # A code-given name ("MainThread", "MixarCrashReporter") only.
                if heading.group("name") and _THREAD_NAME.match(heading.group("name")):
                    thread += f" [{heading.group('name')}]"
            continue
        if _STACK.match(line):  # all_threads=False: the only stack is the crashing one
            if current:
                break
            current, thread = True, None
            continue
        if not current:
            continue
        frame = _FRAME.match(line)
        if frame:
            line_no = frame.group("line")
            frames.append({
                "file": python_stack_file(frame.group("file")),
                "line": int(line_no) if line_no.isdigit() else 0,
                "function": frame.group("function")[:128],
            })
        elif line.startswith("Extension modules:"):
            break
    if not current:
        return None
    frames.reverse()  # innermost last
    return {
        "header": block[0].strip()[:128],
        "python_stack": frames[-MAX_PYTHON_STACK:],
        "python_thread": thread,
    }
