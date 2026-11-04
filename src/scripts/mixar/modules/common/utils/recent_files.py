# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender's recent-files history (the source of File > Open Recent).

``<config>/recent-files.txt`` holds one path per line, newest first. Callers
pass ``bpy.utils.user_resource('CONFIG')`` so this stays plain Python (the
MCP project list and the splash share it).
"""

from pathlib import Path

PROJECT_SUFFIXES = (".mixar", ".blend")


def recent_project_paths(config_dir: str, limit: int) -> list:
    """Existing project files from the history, newest first, at most ``limit``."""
    history = Path(config_dir) / "recent-files.txt"
    try:
        lines = history.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found, seen = [], set()
    for line in (line.strip() for line in lines):
        if not line or line in seen:
            continue
        seen.add(line)
        path = Path(line)
        if path.suffix.lower() in PROJECT_SUFFIXES and path.is_file():
            found.append(path)
            if len(found) == limit:
                break
    return found
