# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Remove everything personal from crash text before it leaves the machine.

- e-mail addresses become ``<email>``;
- the directory part of every absolute path (POSIX, ``C:\\``, UNC, ``~``)
  becomes ``<path>``; only the last component survives, and a ``.blend`` /
  ``.mixar`` name becomes ``<file>.blend``;
- the OS user name (and the home folder's name) becomes ``<user>`` wherever it
  still appears;
- Blender's report log keeps operator names and property names only: values,
  operator arguments (file paths, prompts) and Info / Warning text are dropped.

The backend runs the same path / e-mail rules again (defence in depth).
"""

from __future__ import annotations

import getpass
import os
import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_UNC = re.compile(r"(?<![\w:\\])\\\\[^\\/\r\n\"'<>|]+\\(?:[^\\/:*?\"<>|\r\n]+\\)*")
_WIN = re.compile(r"\b[A-Za-z]:(?:\\\\|[\\/])(?:[^\\/:*?\"<>|\r\n]+(?:\\\\|[\\/]))*")
_POSIX = re.compile(r"(?<![\w.:/\\-])/(?:[^/\r\n\"'<>:()\[\]]+/)+")
_TILDE = re.compile(r"~[\\/](?:[^\\/\r\n\"'<>:]+[\\/])*")
_BLEND = re.compile(r"[^\\/\s\"'<>:]+\.(blend|mixar)\d*\b", re.IGNORECASE)

_REPORT_PROPERTY = re.compile(r"^(?P<lhs>bpy\.[\w.\[\]\"' ]+?)\s*=\s*.*#\s*Property\s*$")
_REPORT_OPERATOR = re.compile(r"^(?P<op>bpy\.ops\.\w+\.\w+)\(.*\)\s*#\s*Operator\s*$")
_REPORT_OTHER = re.compile(r"#\s*(Info|Warning|Error|Debug)\s*$")
_REPORT_INDEX = re.compile(r"\[[^\]]*\]")

_cached_names: tuple[str, ...] | None = None


def local_user_names() -> tuple[str, ...]:
    """The OS account name and the home folder's name (3+ characters)."""
    global _cached_names
    if _cached_names is None:
        names = set()
        for getter in (getpass.getuser, lambda: os.path.basename(os.path.expanduser("~"))):
            try:
                value = (getter() or "").strip()
            except Exception:  # noqa: BLE001 - a missing name scrubs nothing
                value = ""
            if len(value) >= 3:
                names.add(value)
        _cached_names = tuple(sorted(names, key=len, reverse=True))
    return _cached_names


def scrub_text(text: str, user_names: tuple[str, ...] | None = None) -> str:
    """Remove e-mails, path directories and the local user name."""
    if not text:
        return text
    text = _EMAIL.sub("<email>", text)
    text = _UNC.sub(r"<path>\\", text)
    text = _WIN.sub(r"<path>\\", text)
    text = _TILDE.sub("<path>/", text)
    text = _POSIX.sub("<path>/", text)
    text = _BLEND.sub(lambda m: f"<file>.{m.group(1).lower()}", text)
    for name in local_user_names() if user_names is None else user_names:
        text = re.sub(rf"(?<![\w]){re.escape(name)}(?![\w])", "<user>", text, flags=re.IGNORECASE)
    return text


def scrub_report_line(line: str) -> str | None:
    """One report-log line reduced to its operator or property name, or None."""
    stripped = line.strip()
    if not stripped:
        return None
    prop = _REPORT_PROPERTY.match(stripped)
    if prop:
        lhs = _REPORT_INDEX.sub("[]", prop.group("lhs").strip())
        return f"{lhs} = <redacted>  # Property"
    op = _REPORT_OPERATOR.match(stripped)
    if op:
        return f"{op.group('op')}()  # Operator"
    if _REPORT_OTHER.search(stripped):
        return None
    if stripped.startswith("bpy."):
        return re.split(r"[(=\s]", stripped, maxsplit=1)[0]
    return None


def operator_name(line: str) -> str | None:
    """``bpy.ops.mixie_chat.send_message`` for an operator report line."""
    op = _REPORT_OPERATOR.match(line.strip())
    return op.group("op") if op else None


def python_file(path: str) -> str:
    """A script path reduced to its in-app part (``mixar/modules/...``) or basename."""
    normalized = (path or "").replace("\\", "/")
    # (marker, characters of the marker to drop): keep "mixar/...", "startup/...",
    # "addons_core/..." and a package path below site-packages.
    for marker, drop in (("/mixar/", 1), ("/scripts/startup/", 9), ("/scripts/addons_core/", 9),
                         ("/site-packages/", 15)):
        index = normalized.rfind(marker)
        if index >= 0:
            return normalized[index + drop:]
    if normalized.startswith("mixar/"):
        return normalized
    return normalized.rsplit("/", 1)[-1]


def scrub_crash_text(text: str, user_names: tuple[str, ...] | None = None) -> str:
    """A whole crash.txt with the report log reduced and every path scrubbed."""
    if not text:
        return text
    out: list[str] = []
    in_report_log = False
    for index, line in enumerate(text.splitlines()):
        if index == 0 and line.startswith("# "):
            out.append(line)
            in_report_log = True
            continue
        if line.startswith("# backtrace") or line.startswith("# Python backtrace"):
            in_report_log = False
            out.append(line)
            continue
        if in_report_log:
            reduced = scrub_report_line(line)
            if reduced is not None:
                out.append(reduced)
            continue
        out.append(line)
    return scrub_text("\n".join(out), user_names)


def scrub_value(value, user_names: tuple[str, ...] | None = None):
    """Scrub every string in a JSON-shaped value."""
    if isinstance(value, str):
        return scrub_text(value, user_names)
    if isinstance(value, list):
        return [scrub_value(item, user_names) for item in value]
    if isinstance(value, dict):
        return {key: scrub_value(item, user_names) for key, item in value.items()}
    return value
