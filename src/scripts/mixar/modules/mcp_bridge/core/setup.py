# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable configuration snippets using the app's bundled Python.

Every app runs the same stdio launcher; ``render`` writes it in one app's
configuration format (formats checked against each app's documentation on
2026-10-03; the website guide, constants.SETUP_GUIDE_URL, explains them).
``stable_launch`` names the per-user launcher without writing anything, for UI
drawing; ``connection_config`` also (re)writes it, for copying and adding.
"""

import json
from pathlib import Path
import shlex
import subprocess
import sys

#: Codex cuts a tool call off after its default timeout; a scene call may run 570 s.
CODEX_TOOL_TIMEOUT_SECONDS = 610
#: OpenCode stops listing a server's tools after 5 s by default; the launcher
#: may first have to start Mixar.
OPENCODE_TOOLS_TIMEOUT_MS = 60_000


def _wrap(bootstrap):
    if sys.platform == "win32":
        return "cmd.exe", ["/d", "/c", str(bootstrap)]
    return str(bootstrap), []


def stable_launch():
    """The launcher command at its fixed per-user path; writes nothing."""
    from .installation import directory
    return _wrap(directory() / ("mixar-mcp.cmd" if sys.platform == "win32" else "mixar-mcp"))


def launch(resource_directory, executable, enabled):
    """The launcher command, (re)writing the per-user launcher when ``executable`` is given."""
    root = Path(resource_directory)
    if sys.platform == "win32":
        python = root / "python" / "bin" / "python.exe"
    else:
        python = root / "python" / "bin" / ("python%d.%d" % sys.version_info[:2])
    script = Path(__file__).resolve().parents[3] / "mcp.py"
    if executable is None:
        return str(python), [str(script)]
    from .installation import provision
    return _wrap(provision(python, script, executable, enabled=enabled))


def command_line(args):
    return subprocess.list2cmdline(args) if sys.platform == "win32" else shlex.join(args)


def render(client, command, args):
    """One app's setup text for the given launch command."""
    if client == "CLAUDE_CODE":
        return command_line(["claude", "mcp", "add", "--scope", "user", "mixar", "--", command, *args])
    if client == "CODEX":
        return "[mcp_servers.mixar]\ncommand = %s\nargs = %s\ntool_timeout_sec = %d\n" % (
            json.dumps(command), json.dumps(args), CODEX_TOOL_TIMEOUT_SECONDS)
    if client == "CURSOR":
        server = {"type": "stdio", "command": command, "args": args}
        return json.dumps({"mcpServers": {"mixar": server}}, indent=2)
    if client == "VSCODE":
        server = {"type": "stdio", "command": command, "args": args}
        return json.dumps({"servers": {"mixar": server}}, indent=2)
    if client == "OPENCODE":
        server = {"type": "local", "command": [command, *args], "enabled": True,
                  "timeout": OPENCODE_TOOLS_TIMEOUT_MS}
        return json.dumps({"$schema": "https://opencode.ai/config.json", "mcp": {"mixar": server}}, indent=2)
    if client == "COMMAND":
        return command_line([command, *args])
    # JSON, CLAUDE_DESKTOP: the common mcpServers shape most apps accept.
    return json.dumps({"mcpServers": {"mixar": {"command": command, "args": args}}}, indent=2)


def connection_config(client, resource_directory, executable=None, *, enabled=True):
    return render(client, *launch(resource_directory, executable, enabled))
