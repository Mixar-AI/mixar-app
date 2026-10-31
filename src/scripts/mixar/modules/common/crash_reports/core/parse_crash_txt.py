# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parse the crash log Blender's handler writes (``creator_signals.cc``).

Layout::

    # Blender 5.2.0, Commit date: 2026-07-13 15:20, Hash fbe6228777e7
    <report log: operators, property changes, Info/Warning lines>

    # backtrace
    <native frames: macOS ``backtrace_symbols``, Linux ``backtrace_symbols``,
     or Windows exception record + stack + loaded modules>

    # Python backtrace
      File "<path>", line N in <function>      (innermost first)

Only what grouping and triage need is kept: the build line, operator names,
frames (module, function, offset), the Python frames (in-app path, function,
line) and, on Windows, the exception code and module. No path survives:
modules are basenames and script paths are reduced by ``scrub.python_file``.
"""

from __future__ import annotations

import re

from ..constants import MAX_FRAMES, MAX_OPERATORS
from .scrub import operator_name, python_file

_HEADER = re.compile(r"^#\s+Blender\s+(?P<version>[\w.\-]+)(?:,.*?Hash\s+(?P<hash>[0-9a-f]+))?", re.IGNORECASE)
_MAC_FRAME = re.compile(
    r"^\s*\d+\s+(?P<module>\S+)\s+0x[0-9a-fA-F]+\s+(?P<function>.+?)(?:\s+\+\s+(?P<offset>\d+))?\s*$"
)
_LINUX_FRAME = re.compile(
    r"^(?P<path>[^\s(]+)\((?P<function>[^)+]*)(?:\+(?P<offset>0x[0-9a-fA-F]+))?\)\s*\[0x[0-9a-fA-F]+\]"
)
_WIN_FRAME = re.compile(r"^(?P<module>\S[^:]*?)\s*:0x(?P<address>[0-9A-Fa-f]+)\s+(?P<symbol>.+?)\s*$")
_WIN_MODULE = re.compile(r"^0x(?P<base>[0-9A-Fa-f]+)\s+(?P<version>\S*)\s+(?P<name>\S+)")
_WIN_FIELD = re.compile(r"^(?P<key>ExceptionCode|Exception [A-Z]\w*)\s*:\s*(?P<value>.+?)\s*$")
_PY_FRAME = re.compile(r'^\s*File\s+"(?P<file>[^"]*)",\s+line\s+(?P<line>\d+)\s+in\s+(?P<function>.+?)\s*$')

APP_BINARIES = ("mixar", "mixar.exe")


def _basename(path: str) -> str:
    return re.split(r"[\\/]", path.strip())[-1]


def _sections(text: str) -> tuple[list[str], list[str], list[str], list[str]]:
    header, report, native, python = [], [], [], []
    target = report
    for index, line in enumerate(text.splitlines()):
        if index == 0 and line.startswith("#") and "backtrace" not in line:
            header.append(line)
            continue
        if line.startswith("# Python backtrace"):
            target = python
            continue
        if line.startswith("# backtrace"):
            target = native
            continue
        target.append(line)
    return header, report, native, python


def _windows(native: list[str]) -> tuple[dict, list[dict]]:
    fields: dict[str, str] = {}
    stack: list[tuple[str, int, str]] = []
    modules: dict[str, int] = {}
    block = ""
    for line in native:
        stripped = line.strip()
        if stripped.startswith("Stack trace:"):
            block = "stack"
            continue
        if stripped.startswith("Loaded Modules"):
            block = "modules"
            continue
        if stripped.startswith("Threads:"):
            block = "threads"
            continue
        field = _WIN_FIELD.match(stripped)
        if field and block == "":
            fields.setdefault(field.group("key").replace(" ", ""), field.group("value"))
            continue
        if block == "stack":
            frame = _WIN_FRAME.match(stripped)
            if frame:
                stack.append((frame.group("module").strip(), int(frame.group("address"), 16),
                              frame.group("symbol").strip()))
        elif block == "modules":
            module = _WIN_MODULE.match(stripped)
            if module:
                modules[module.group("name").lower()] = int(module.group("base"), 16)
    frames = []
    for module, address, symbol in stack:
        base = modules.get(module.lower())
        frames.append({
            "module": _basename(module),
            "function": "" if symbol.lower() == "symbols not available" else symbol,
            "offset": address - base if base is not None and address >= base else None,
        })
    code = fields.get("ExceptionCode", "")
    info = {
        "crash_type": code.split(" (")[0].strip() or "EXCEPTION_UNKNOWN",
        "crash_module": _basename(fields.get("ExceptionModule", "")) or None,
        "app_binary": any(name in APP_BINARIES for name in modules),
    }
    exception_address = fields.get("ExceptionAddress", "")
    if not frames and exception_address.startswith("0x") and info["crash_module"]:
        base = modules.get(info["crash_module"].lower())
        address = int(exception_address, 16)
        frames.append({"module": info["crash_module"], "function": "",
                       "offset": address - base if base is not None and address >= base else None})
    return info, frames


def _posix(native: list[str]) -> tuple[dict, list[dict]]:
    frames = []
    for line in native:
        mac = _MAC_FRAME.match(line)
        if mac:
            frames.append({
                "module": mac.group("module"),
                "function": mac.group("function").strip(),
                "offset": int(mac.group("offset")) if mac.group("offset") else None,
            })
            continue
        linux = _LINUX_FRAME.match(line.strip())
        if linux:
            offset = linux.group("offset")
            frames.append({
                "module": _basename(linux.group("path")),
                "function": linux.group("function").strip(),
                "offset": int(offset, 16) if offset else None,
            })
    # The POSIX handler only runs for SIGSEGV / SIGBUS (both "bad access").
    info = {
        "crash_type": "SIGSEGV",
        "crash_module": None,
        "app_binary": any(frame["module"].lower() in APP_BINARIES for frame in frames),
    }
    return info, frames


def _thread(frames: list[dict]) -> str | None:
    names = " ".join(str(frame.get("function") or "") for frame in frames)
    if "do_job_thread" in names or "wm_job" in names:
        return "job"
    if re.search(r"(?:^|\W)main(?:\W|$)", names) or "WM_main" in names:
        return "main"
    if "_pthread_start" in names or "thread_start" in names or "start_thread" in names:
        return "worker"
    return None


def parse_crash_txt(text: str) -> dict | None:
    """The parsed crash, or None when the text is not a Blender crash log."""
    if not text or "# backtrace" not in text:
        return None
    header, report, native, python = _sections(text)
    match = _HEADER.match(header[0]) if header else None
    if any(line.strip().startswith("Exception Record") for line in native):
        info, frames = _windows(native)
        platform = "windows"
    else:
        info, frames = _posix(native)
        platform = "darwin" if any("libsystem_" in f["module"] or f["module"] == "dyld" for f in frames) else (
            "linux" if any(".so" in f["module"] for f in frames) else None
        )
    operators = [name for name in (operator_name(line) for line in report) if name]
    python_frames = []
    for line in python:
        frame = _PY_FRAME.match(line)
        if frame:
            python_frames.append({
                "file": python_file(frame.group("file")),
                "function": frame.group("function")[:128],
                "line": int(frame.group("line")),
            })
    return {
        "blender_version": match.group("version") if match else None,
        "build_hash": (match.group("hash") if match else None) or None,
        "platform": platform,
        "crash_type": info["crash_type"],
        "crash_module": info["crash_module"],
        "is_mixar": bool(info["app_binary"]),
        "thread": _thread(frames),
        "frames": frames[:MAX_FRAMES],
        "python_frames": python_frames[:MAX_FRAMES],
        "operators": operators[-MAX_OPERATORS:],
    }
