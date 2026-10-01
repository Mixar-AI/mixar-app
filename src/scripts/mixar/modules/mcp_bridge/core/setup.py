# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable configuration snippets using the app's bundled Python."""

import json
from pathlib import Path
import shlex
import subprocess
import sys


def connection_config(client, resource_directory, executable=None, *, enabled=True):
    root = Path(resource_directory)
    if sys.platform == "win32":
        python = root / "python" / "bin" / "python.exe"
    else:
        python = root / "python" / "bin" / ("python%d.%d" % sys.version_info[:2])
    script = Path(__file__).resolve().parents[3] / "mcp.py"
    command, launch_args = str(python), [str(script)]
    if executable is not None:
        from .installation import provision
        bootstrap = provision(python, script, executable, enabled=enabled)
        if sys.platform == "win32":
            command, launch_args = "cmd.exe", ["/d", "/c", str(bootstrap)]
        else:
            command, launch_args = str(bootstrap), []
    if client == "CLAUDE_CODE":
        args = ["claude", "mcp", "add", "--scope", "user", "mixar", "--", command, *launch_args]
        return subprocess.list2cmdline(args) if sys.platform == "win32" else shlex.join(args)
    if client == "CLAUDE_DESKTOP":
        return json.dumps({"mcpServers": {"mixar": {"command": command, "args": launch_args}}}, indent=2)
    return "[mcp_servers.mixar]\ncommand = %s\nargs = %s\ntool_timeout_sec = 610\n" % (
        json.dumps(command), json.dumps(launch_args))
