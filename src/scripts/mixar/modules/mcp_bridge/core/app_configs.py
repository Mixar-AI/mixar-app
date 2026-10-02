# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-app setup for the Connect dialog: where each app keeps its MCP config,
and one-click adding for Claude Code and Codex.

No bpy here: adding runs on a worker thread. Claude Code is changed only
through its own ``claude mcp`` command. Codex has no command for the tool
timeout Mixar needs, so its ``[mcp_servers.mixar]`` table is written into
config.toml directly: only that table, re-parsed before it replaces the file,
with the previous file kept as config.toml.mixar-backup. Formats and paths
checked against each app's documentation on 2026-10-03.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from mixar.modules.common.i18n import n_
from .setup import CODEX_TOOL_TIMEOUT_SECONDS, render

#: Dialog order: key, label (a product name, never translated), how to use the snippet.
APPS = (
    ("CLAUDE_CODE", "Claude Code", n_("Run once in a terminal, or click Add to Claude Code.")),
    ("CODEX", "Codex", n_("Add to ~/.codex/config.toml, or click Add to Codex.")),
    ("CLAUDE_DESKTOP", "Claude Desktop", n_("Merge into claude_desktop_config.json (Settings > Developer > Edit Config).")),
    ("CURSOR", "Cursor", n_("Merge into ~/.cursor/mcp.json (or a project's .cursor/mcp.json).")),
    ("VSCODE", "VS Code", n_("Merge into the user mcp.json (command: MCP: Open User Configuration).")),
    ("OPENCODE", "OpenCode", n_("Merge into ~/.config/opencode/opencode.json.")),
    ("JSON", "Other app (JSON)", n_("Merge into the app's mcpServers configuration (Windsurf, Cline, Gemini CLI...).")),
    ("COMMAND", "Other app (command)", n_("Give this command to any app that can run a local (stdio) MCP server.")),
)
ADDABLE = ("CLAUDE_CODE", "CODEX")
CLI_TIMEOUT = 60


def label(app):
    return next(name for key, name, _ in APPS if key == app)


def _home():
    return Path.home()


def _appdata():
    return Path(os.environ.get("APPDATA") or _home() / "AppData" / "Roaming")


def codex_home():
    return Path(os.environ["CODEX_HOME"]).expanduser() if os.environ.get("CODEX_HOME") else _home() / ".codex"


def config_path(app):
    """The app's user-level MCP configuration file, or None when it has none to open."""
    mac, win = sys.platform == "darwin", sys.platform == "win32"
    if app == "CODEX":
        return codex_home() / "config.toml"
    if app == "CLAUDE_DESKTOP":
        if mac:
            return _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        return _appdata() / "Claude" / "claude_desktop_config.json" if win else None
    if app == "CURSOR":
        return _home() / ".cursor" / "mcp.json"
    if app == "VSCODE":
        if mac:
            return _home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
        return (_appdata() / "Code" if win else _home() / ".config" / "Code") / "User" / "mcp.json"
    if app == "OPENCODE":
        return None if win else _home() / ".config" / "opencode" / "opencode.json"
    return None


# ---------------------------------------------------------------- Claude Code

def _search_path():
    """PATH plus the usual CLI install folders: a GUI app does not inherit the shell's PATH."""
    home = _home()
    extra = [home / ".local" / "bin", home / ".claude" / "local", Path("/opt/homebrew/bin"),
             Path("/usr/local/bin"), home / ".npm-global" / "bin", home / ".bun" / "bin",
             _appdata() / "npm"]
    return os.pathsep.join([os.environ.get("PATH", ""), *map(str, extra)])


def find_cli(name):
    found = shutil.which(name, path=_search_path())
    if found or sys.platform == "win32":
        return found
    shell = os.environ.get("SHELL") or "/bin/zsh"
    try:
        out = subprocess.run([shell, "-lc", "command -v " + name], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    line = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    return line if line.startswith("/") and Path(line).is_file() else None


def _run(args):
    env = {**os.environ, "PATH": os.pathsep.join([str(Path(args[0]).parent), _search_path()])}
    result = subprocess.run(args, capture_output=True, text=True, timeout=CLI_TIMEOUT, env=env)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def add_to_claude_code(command, args, cli=None):
    """Returns (status, detail): status is added, updated, already or failed."""
    cli = cli or find_cli("claude")
    if not cli:
        return "failed", n_("Claude Code's claude command was not found. Copy the command and run it in a terminal.")
    add = [cli, "mcp", "add", "--scope", "user", "mixar", "--", command, *args]
    code, out = _run(add)
    if code == 0:
        return "added", ""
    if "already exists" not in out:
        return "failed", _first_line(out)
    code, current = _run([cli, "mcp", "get", "mixar"])
    if code == 0 and command in current and all(arg in current for arg in args):
        return "already", ""
    code, out = _run([cli, "mcp", "remove", "--scope", "user", "mixar"])
    if code != 0:
        return "failed", _first_line(out)
    code, out = _run(add)
    return ("updated", "") if code == 0 else ("failed", _first_line(out))


def _first_line(text):
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[0][:200] if lines else "The command failed."


# ---------------------------------------------------------------------- Codex

_TABLE = re.compile(r'^\s*\[\s*mcp_servers\s*\.\s*(?:mixar|"mixar")\s*(?:\.[^\]]*)?\]\s*(?:#.*)?$')
_ANY_TABLE = re.compile(r"^\s*\[")


def _without_mixar_table(text):
    """Drop [mcp_servers.mixar] and its sub-tables; everything else is kept verbatim."""
    kept, inside = [], False
    for line in text.splitlines(keepends=True):
        if _TABLE.match(line):
            inside = True
            continue
        if inside and _ANY_TABLE.match(line):
            inside = False
        if not inside:
            kept.append(line)
    return "".join(kept)


def add_to_codex(command, args, path=None):
    """Returns (status, detail): status is added, updated, already or failed."""
    import tomllib
    path = Path(path) if path else codex_home() / "config.toml"
    if not path.parent.is_dir():
        return "failed", n_("Codex's settings folder was not found; open Codex once, then try again.")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        entry = tomllib.loads(text).get("mcp_servers", {}).get("mixar")
    except tomllib.TOMLDecodeError:
        return "failed", n_("Codex's config.toml could not be read; copy the setup and add it by hand.")
    if (isinstance(entry, dict) and entry.get("command") == command and list(entry.get("args", [])) == args
            and entry.get("tool_timeout_sec", 0) >= CODEX_TOOL_TIMEOUT_SECONDS):
        return "already", ""
    stripped = _without_mixar_table(text) if entry is not None else text
    if entry is not None and stripped == text:
        return "failed", n_("Codex defines mixar in a form Mixar cannot update; edit config.toml by hand.")
    block = render("CODEX", command, args)
    updated = stripped.rstrip("\n") + ("\n\n" if stripped.strip() else "") + block
    backup = path.with_name(path.name + ".mixar-backup")
    if path.exists():
        shutil.copy2(path, backup)
    temporary = path.with_name("." + path.name + ".mixar-tmp")
    try:
        temporary.write_text(updated, encoding="utf-8")
        written = tomllib.loads(updated)["mcp_servers"]["mixar"]
        if written.get("command") != command:
            raise ValueError("mixar entry did not round-trip")
        os.replace(temporary, path)
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError):
        temporary.unlink(missing_ok=True)
        return "failed", n_("Codex's config.toml was left unchanged; copy the setup and add it by hand.")
    return ("updated" if entry is not None else "added"), ""


def add(app, command, args):
    try:
        if app == "CLAUDE_CODE":
            return add_to_claude_code(command, args)
        if app == "CODEX":
            return add_to_codex(command, args)
    except subprocess.TimeoutExpired:
        return "failed", n_("The app's command did not finish; copy the setup and add it by hand.")
    except OSError as exc:
        return "failed", "Could not run the app's command (%s); copy the setup instead." % exc.strerror
    return "failed", n_("This app is set up by pasting its configuration.")
