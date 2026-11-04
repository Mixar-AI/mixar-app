# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parse the crash log Blender's handler writes (``creator_signals.cc``).

Layout::

    # Blender 5.2.0, Commit date: 2026-07-13 15:20, Hash fbe6228777e7
    <report log: operators, property changes, Info/Warning lines>

    # backtrace
    <native frames: macOS ``backtrace_symbols``, Linux ``backtrace_symbols``,
     or Windows exception record + stack + loaded modules>

    # mixar symbolication v1                  (Mixar builds from 4.3.8 on)
    mixar_version / git_sha / arch
    image base=0x.. vmaddr=0x.. size=0x.. id=<debug id> name=<file name>
    frame <n> 0x<return address>

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
    r"^\s*\d+\s+(?P<module>\S+)\s+(?P<address>0x[0-9a-fA-F]+)\s+(?P<function>.+?)"
    r"(?:\s+\+\s+(?P<offset>\d+))?\s*$"
)
_LINUX_FRAME = re.compile(
    r"^(?P<path>[^\s(]+)\((?P<function>[^)+]*)(?:\+(?P<offset>0x[0-9a-fA-F]+))?\)\s*\[(?P<address>0x[0-9a-fA-F]+)\]"
)
_SYM_IMAGE = re.compile(
    r"^image\s+base=(?P<base>0x[0-9a-fA-F]+)\s+vmaddr=(?P<vmaddr>0x[0-9a-fA-F]+)\s+"
    r"size=(?P<size>0x[0-9a-fA-F]+)\s+id=(?P<id>\S+)\s+name=(?P<name>.*?)\s*$"
)
_SYM_FRAME = re.compile(r"^frame\s+\d+\s+(?P<address>0x[0-9a-fA-F]+)\s*$")
_SYM_VALUE = re.compile(r"^(?P<key>mixar_version|git_sha|arch)\s+(?P<value>\S+)\s*$")
MAX_IMAGES = 32
_WIN_FRAME = re.compile(r"^(?P<module>\S[^:]*?)\s*:0x(?P<address>[0-9A-Fa-f]+)\s+(?P<symbol>.+?)\s*$")
_WIN_MODULE = re.compile(r"^0x(?P<base>[0-9A-Fa-f]+)\s+(?P<version>\S*)\s+(?P<name>\S+)")
_WIN_FIELD = re.compile(r"^(?P<key>ExceptionCode|Exception [A-Z]\w*)\s*:\s*(?P<value>.+?)\s*$")
_PY_FRAME = re.compile(r'^\s*File\s+"(?P<file>[^"]*)",\s+line\s+(?P<line>\d+)\s+in\s+(?P<function>.+?)\s*$')

APP_BINARIES = ("mixar", "mixar.exe")


def _basename(path: str) -> str:
    return re.split(r"[\\/]", path.strip())[-1]


def _sections(text: str) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    header, report, native, symbols, python = [], [], [], [], []
    target = report
    for index, line in enumerate(text.splitlines()):
        if index == 0 and line.startswith("#") and "backtrace" not in line:
            header.append(line)
            continue
        if line.startswith("# Python backtrace"):
            target = python
            continue
        if line.startswith("# mixar symbolication"):
            target = symbols
            continue
        if line.startswith("# backtrace"):
            target = native
            continue
        target.append(line)
    return header, report, native, symbols, python


def _symbolication(lines: list[str]) -> dict:
    """The symbolication block: build, images (file names only) and raw addresses."""
    values: dict = {}
    images: list[dict] = []
    addresses: list[int] = []
    for line in lines:
        stripped = line.strip()
        value = _SYM_VALUE.match(stripped)
        if value:
            values[value.group("key")] = value.group("value")
            continue
        image = _SYM_IMAGE.match(stripped)
        if image and len(images) < MAX_IMAGES:
            images.append({
                "name": _basename(image.group("name"))[:128],
                "id": "" if image.group("id") == "-" else image.group("id").lower()[:80],
                "base": int(image.group("base"), 16),
                "vmaddr": int(image.group("vmaddr"), 16),
                "size": int(image.group("size"), 16),
            })
            continue
        frame = _SYM_FRAME.match(stripped)
        if frame and len(addresses) < MAX_FRAMES:
            addresses.append(int(frame.group("address"), 16))
    return {"values": values, "images": images, "addresses": addresses}


def image_for(images: list[dict], address: int) -> dict | None:
    for image in images:
        if image["base"] <= address < image["base"] + max(image.get("size") or 0, 1):
            return image
    return None


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
            # "DllCanUnloadNow" for _ctypes.pyd is the nearest export, still a lead.
            "function": "" if symbol.lower() == "symbols not available" else symbol[:512],
            "offset": address - base if base is not None and address >= base else None,
            "_address": address,
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


def _agreeing(index: int, address: int, image, walk: list[dict]):
    """Walk line ``index`` when it names the block frame at ``address``, else None."""
    if index >= len(walk):
        return None
    line = walk[index]
    start = line.get("_address")
    module = str(line.get("module") or "").lower()
    if start is None or (image and module != str(image["name"]).lower()):
        return None
    if address == start:
        return line
    if not line.get("function") or address < start:
        return None
    if any(str(other.get("module") or "").lower() == module and other.get("function")
           and other.get("_address") is not None and start < other["_address"] <= address
           for other in walk):
        return None  # a nearer logged symbol: the walks disagree
    return line


def _posix(native: list[str]) -> tuple[dict, list[dict]]:
    frames = []
    for line in native:
        mac = _MAC_FRAME.match(line)
        if mac:
            frames.append({
                "module": mac.group("module"),
                "function": mac.group("function").strip(),
                "offset": int(mac.group("offset")) if mac.group("offset") else None,
                "address": int(mac.group("address"), 16),
            })
            continue
        linux = _LINUX_FRAME.match(line.strip())
        if linux:
            offset = linux.group("offset")
            frames.append({
                "module": _basename(linux.group("path")),
                "function": linux.group("function").strip(),
                "offset": int(offset, 16) if offset else None,
                "address": int(linux.group("address"), 16),
            })
    frames, dropped = _drop_chained_reraise(frames)
    # The POSIX handler only runs for SIGSEGV / SIGBUS (both "bad access").
    info = {
        "dropped_addresses": [frame["address"] for frame in dropped],
        "crash_type": "SIGSEGV",
        "crash_module": None,
        "app_binary": any(frame["module"].lower() in APP_BINARIES for frame in frames),
    }
    return info, frames


_TRAMPOLINES = ("_sigtramp", "__restore_rt")
_RERAISE = ("raise", "pthread_kill", "__pthread_kill", "_pthread_kill", "__GI_raise")


def _drop_chained_reraise(frames: list[dict]) -> tuple[list[dict], list[dict]]:
    """Python's faulthandler handles the signal first (``crash_reports/core/pyfault.py``)
    and re-raises it into Blender's handler, so the log reads: Blender's handler,
    trampoline, the re-raise (``pthread_kill`` / ``raise``), faulthandler, a second
    trampoline, then the faulting frames. Drop the middle stretch: the log reads as
    it did without faulthandler (handler, trampoline, fault)."""
    trampolines = [index for index, frame in enumerate(frames[:24])
                   if str(frame.get("function") or "") in _TRAMPOLINES]
    if len(trampolines) < 2:
        return frames, []
    first, second = trampolines[0], trampolines[1]
    stretch = frames[first + 1:second + 1]
    if not any(str(frame.get("function") or "") in _RERAISE for frame in stretch):
        return frames, []
    return frames[:first + 1] + frames[second + 1:], stretch


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
    header, report, native, symbols, python = _sections(text)
    match = _HEADER.match(header[0]) if header else None
    symbolication = _symbolication(symbols)
    if any(line.strip().startswith("Exception Record") for line in native):
        info, frames = _windows(native)
        platform = "windows"
    else:
        info, frames = _posix(native)
        platform = "darwin" if any("libsystem_" in f["module"] or f["module"] == "dyld" for f in frames) else (
            "linux" if any(".so" in f["module"] for f in frames) else None
        )
    images = symbolication["images"]
    addresses = symbolication["addresses"]
    # The faulthandler re-raise left the log: its addresses leave the block too.
    for address in info.pop("dropped_addresses", []):
        if address in addresses:
            addresses.remove(address)
    if addresses and (platform == "windows" or not any(frame.get("address") for frame in frames)):
        # Windows: Blender's walk stops at the first frame without symbols; the
        # block's walk from the exception context has every return address.
        # Blender's own walk names its frames: a named line prints the SYMBOL's
        # start (SymFromAddr), a nameless one the frame's pc. The two walks agree
        # frame by frame, so block frame i takes walk line i's name when both are
        # in the same module and the symbol starts at or below the frame's address
        # with no other logged symbol of that module between them (the server's
        # windows_frames rule, so both sides name the same frames).
        walk = list(frames)
        frames = []
        for index, address in enumerate(addresses):
            image = image_for(images, address)
            known = _agreeing(index, address, image, walk)
            frames.append({
                "module": image["name"] if image else (known["module"] if known else None),
                "function": known["function"] if known else "",
                "offset": address - image["base"] if image else (known["offset"] if known else None),
                "address": address,
            })
    for frame in frames:
        frame.pop("_address", None)
    if any(image["name"].lower() in APP_BINARIES for image in images):
        info["app_binary"] = True
    mixar_version = symbolication["values"].get("mixar_version")
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
        "app_version": mixar_version if mixar_version and mixar_version != "unknown" else None,
        "git_sha": (symbolication["values"].get("git_sha") or "")[:64] or None,
        "arch": symbolication["values"].get("arch"),
        "images": images,
    }
