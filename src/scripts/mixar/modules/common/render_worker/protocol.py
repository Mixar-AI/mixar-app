# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Line framing between the app and its render worker.

One JSON object per line. Worker messages are prefixed with :data:`MARK` so the
parent can tell them from Blender's own stdout (render progress, warnings).
Large payloads (PNG pixels, export reports) travel as FILES in the job folder;
a line only names them. No ``bpy``.

Parent -> worker (stdin):
    {"type": "job", "job": <id>, "kind": "preview"|"export", "snapshot": <path>,
     "scene": <name>, "view_layer": <name>, "params": {...}, "out": <path>,
     "images": <path or "">}
    {"type": "quit"}

Worker -> parent (stdout):
    {"type": "ready", "pid": int, "boot_s": float}
    {"type": "started", "job": <id>}
    {"type": "result", "job": <id>, "ok": bool, "out": <path>, "seconds": {...}}
    {"type": "exit", "reason": str}
"""

import json

MARK = "@@MIXAR_RENDER_WORKER@@"
JOB_KINDS = ("preview", "export")


def encode(message: dict) -> str:
    return MARK + json.dumps(message, separators=(",", ":")) + "\n"


def decode(line: str):
    """The message a worker line carries, or None for any other output."""
    if not isinstance(line, str):
        return None
    index = line.find(MARK)
    if index < 0:
        return None
    try:
        value = json.loads(line[index + len(MARK):])
    except ValueError:
        return None
    return value if isinstance(value, dict) and isinstance(value.get("type"), str) else None
