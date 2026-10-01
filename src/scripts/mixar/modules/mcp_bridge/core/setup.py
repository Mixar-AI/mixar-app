# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable configuration snippets using the app's bundled Python."""

import json
from pathlib import Path
import shlex
import subprocess
import sys


def connection_config(client, resource_directory):
    root = Path(resource_directory)
    if sys.platform == "win32":
        python = root / "python" / "bin" / "python.exe"
    else:
        python = root / "python" / "bin" / ("python%d.%d" % sys.version_info[:2])
    script = Path(__file__).resolve().parents[3] / "mcp.py"
    if client == "CLAUDE_CODE":
        args = ["claude", "mcp", "add", "--scope", "user", "mixar", "--", str(python), str(script)]
        return subprocess.list2cmdline(args) if sys.platform == "win32" else shlex.join(args)
    if client == "CLAUDE_DESKTOP":
        return json.dumps({"mcpServers": {"mixar": {"command": str(python), "args": [str(script)]}}}, indent=2)
    return "[mcp_servers.mixar]\ncommand = %s\nargs = [%s]\ntool_timeout_sec = 610\n" % (
        json.dumps(str(python)), json.dumps(str(script)))
