# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Stable local entrypoint refreshed by the installed app, with no system Python."""

import json
import ntpath
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid

from ..constants import LAUNCHER_FEATURES
from .discovery import discovery_directory


def directory():
    return discovery_directory().parent / "connector"


def _atomic(path, data, mode=0o600):
    temporary = path.with_name("."+uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


_PREFIX_OPTION = "pycache_prefix="


def _bytecode_args(windows=False):
    """The launcher's Python never writes into the install directory.

    A ``__pycache__`` written there breaks the signed macOS bundle, so it
    shares the app's bytecode cache (``sys.pycache_prefix``, set before the
    app's Python starts) or, without one, writes no bytecode at all. A
    Windows ``.cmd`` carries non-ASCII text only inside ``%LOCALAPPDATA%``
    (see ``_cmd_argument``); a cache it would mangle is not used.
    """
    prefix = sys.pycache_prefix
    if prefix and windows:
        rest = _localappdata_rest(prefix)
        if not (prefix if rest is None else rest).isascii():
            prefix = None
    return ["-X", _PREFIX_OPTION+prefix] if prefix else ["-B"]


def _localappdata_rest(path):
    """``path`` below ``%LOCALAPPDATA%`` as the part after it (``\\Mixar\\...``), else None.
    Windows rules: case-insensitive, either slash."""
    base = os.environ.get("LOCALAPPDATA", "").rstrip("\\/")
    if not base or len(path) <= len(base)+1 or path[len(base)] not in "\\/":
        return None
    if ntpath.normcase(path[:len(base)]) != ntpath.normcase(base):
        return None
    return path[len(base):]


def _cmd_argument(arg):
    """One argument of the ``.cmd`` launcher's command line.

    Every argument is double-quoted: ``subprocess.list2cmdline`` quotes only
    arguments with spaces, and cmd.exe splits an unquoted ``&`` or ``^`` (a
    user name such as ``R&D``) into another command. ``%`` is doubled for the
    batch parser; a trailing backslash is doubled so it does not escape the
    closing quote for the program's argv parser. Windows paths cannot hold ``"``.

    The bytecode cache below ``%LOCALAPPDATA%`` (the default) is written as
    that reference, its ``%`` left single: cmd.exe decodes a batch file in the
    console code page, so a non-ASCII user name (``Jöhn``) written literally
    reaches Python mangled, while an expanded variable keeps its exact value.
    (``chcp 65001`` would too, but it changes the code page of the console the
    MCP client shares, for the rest of that session.)
    """
    text = arg.replace("%", "%%")
    if arg.startswith(_PREFIX_OPTION):
        rest = _localappdata_rest(arg[len(_PREFIX_OPTION):])
        if rest is not None:
            text = _PREFIX_OPTION+"%LOCALAPPDATA%"+rest.replace("%", "%%")
    return '"'+text+"\\"*(len(text)-len(text.rstrip("\\")))+'"'


def _cmd_line(command):
    return " ".join(_cmd_argument(arg) for arg in command)+" %*"


def _localappdata_option(command):
    """Index of a ``-X pycache_prefix=`` value below ``%LOCALAPPDATA%``, else None."""
    for index in range(1, len(command)):
        arg = command[index]
        if command[index-1] == "-X" and arg.startswith(_PREFIX_OPTION) \
                and _localappdata_rest(arg[len(_PREFIX_OPTION):]) is not None:
            return index
    return None


def _cmd_text(command):
    """The Windows launcher: ``command`` as a cmd.exe line, then the caller's arguments.
    The same text works from ``cmd /d /c``, ``cmd /d /s /c ""…""`` and a direct start.

    A cache written as ``%LOCALAPPDATA%`` is guarded: a client that starts the
    launcher without that variable would expand it to nothing, and the cache
    would become ``\\Mixar\\...`` at the root of the current drive. Such a start
    writes no bytecode (``-B``). ``goto``, not a parenthesised block, so a ``)``
    in a path or an argument cannot end it; CRLF, because cmd.exe's label search
    can miss a label in a batch file with bare LF line ends.
    """
    lines = ["@echo off"]
    index = _localappdata_option(command)
    if index is None:
        lines.append(_cmd_line(command))
    else:
        lines += ["if not defined LOCALAPPDATA goto nocache", _cmd_line(command), "exit /b",
                  ":nocache", _cmd_line([*command[:index-1], "-B", *command[index+1:]])]
    return "".join(line+"\r\n" for line in lines)


def provision(python, script, executable, enabled=True):
    """(Re)write the launcher; the app does so on every start (runtime._tick).

    ``features`` names what this Mixar's launcher honours (a reader that knows
    only ``version`` 1 ignores it): the Claude plugin starts only a launcher
    whose record lists "hide_media_generation", so an older Mixar fails closed.
    """
    root = directory()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink():
        raise OSError("Connector directory must not be a symlink")
    if os.name != "nt":
        if root.stat().st_uid != os.getuid():
            raise OSError("Connector directory belongs to another user")
        root.chmod(0o700)
    manifest = {"version": 1, "python": str(python), "script": str(script),
                "executable": str(executable), "enabled": bool(enabled), "features": list(LAUNCHER_FEATURES)}
    _atomic(root / "installation.json", json.dumps(manifest))
    windows = os.name == "nt"
    command = [str(python), *_bytecode_args(windows), str(script)]
    if windows:
        path = root / "mixar-mcp.cmd"
        _atomic(path, _cmd_text(command))
    else:
        path = root / "mixar-mcp"
        _atomic(path, "#!/bin/sh\nexec "+shlex.join(command)+' "$@"\n', 0o700)
    return path


# A first launch (Gatekeeper, shader cache, sign-in restore) can take well over
# a minute before the relay appears; until then Mixar counts as starting. The
# marker is removed as soon as an app publishes its relay or the launch fails,
# so a quit or crashed app is not "starting" for the rest of the window.
STARTING_SECONDS = 180
OPEN_WAIT_SECONDS = 5
# Restart & Update writes the "updating" marker before the app quits: its
# helper replaces the files and relaunches Mixar itself, so a connector that
# finds no app meanwhile must wait rather than launch the old (or half
# replaced) binary. The relaunched app removes the marker when it publishes
# its relay; the bound keeps a helper that died from holding the cold start.
UPDATING_SECONDS = 900


def disabled():
    """The user turned MCP off in Mixar.

    The app rewrites the manifest whenever the switch changes (runtime._tick),
    so a missing relay with ``enabled: false`` here means the switch, not a
    closed Mixar. No manifest (never set up) or an unreadable one says nothing.
    """
    try:
        info = json.loads((directory() / "installation.json").read_text())
    except (OSError, ValueError):
        return False
    return isinstance(info, dict) and info.get("version") == 1 and info.get("enabled") is False


# Set by a launch that found an update being installed and is quitting
# again: its relay must not end the update's window (see keep_updating).
_keep_updating = False


def keep_updating():
    """This Mixar is not the one the update brings back: leave the marker.

    A Mixar opened by hand while the helper installs says so and quits a
    few seconds later — but its relay publishes first, and started() would
    otherwise take that for the relaunch and let a connector cold-start
    the old or half-replaced binary. Called before the relay's first tick.
    """
    global _keep_updating
    _keep_updating = True


def started():
    """A launched Mixar is up (its relay is published), or the launch failed.

    Also ends an update's "updating" window: the relaunched app is this one
    — unless keep_updating() said it is a launch that is quitting again.
    """
    names = ("starting",) if _keep_updating else ("starting", "updating")
    for name in names:
        try:
            (directory() / name).unlink()
        except OSError:
            pass


def _fresh(name, seconds):
    try:
        return time.time()-(directory() / name).stat().st_mtime <= seconds
    except OSError:
        return False


def updating():
    """Restart & Update is replacing Mixar (within the last UPDATING_SECONDS);
    its helper brings the app back, so nothing else may launch one."""
    return _fresh("updating", UPDATING_SECONDS)


def mark_updating():
    """Called by Restart & Update right before the app quits to be replaced."""
    root = directory()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker = root / "updating"
    marker.touch()
    os.utime(marker)


def clear_updating():
    """The update did not go ahead after all (the quit was aborted)."""
    try:
        (directory() / "updating").unlink()
    except OSError:
        pass


def start_in_progress():
    """An MCP host started Mixar within the last STARTING_SECONDS, or an
    update is replacing it and will relaunch it."""
    return _fresh("starting", STARTING_SECONDS) or updating()


def start_app():
    """At most one cold start across simultaneous MCP hosts; no repeated resurrection."""
    if updating():
        return False  # the update helper relaunches Mixar itself
    root = directory()
    try:
        info = json.loads((root / "installation.json").read_text())
    except (OSError, ValueError):
        return False
    if info.get("version") != 1 or info.get("enabled") is not True:
        return False
    executable = Path(info["executable"])
    if not executable.is_absolute() or not executable.is_file():
        return False
    marker = root / "starting"
    try:
        if marker.exists() and time.time()-marker.stat().st_mtime > STARTING_SECONDS:
            marker.unlink()
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.close(fd)
    command = [str(executable)]
    if sys.platform == "darwin":
        bundle = next((p for p in executable.parents if p.suffix == ".app"), None)
        if bundle:
            command = ["/usr/bin/open", "-a", str(bundle)]
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        started()
        return False
    if command[0] == "/usr/bin/open":
        # open hands the launch to LaunchServices and exits at once; a non-zero
        # status means Mixar could not be opened, so nothing is starting.
        try:
            if process.wait(timeout=OPEN_WAIT_SECONDS) != 0:
                started()
                return False
        except subprocess.TimeoutExpired:
            pass
    return True
