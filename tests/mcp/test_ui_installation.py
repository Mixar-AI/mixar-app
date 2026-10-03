# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A copied setup path survives app replacement and cannot double-start it."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from mixar.modules.mcp_bridge.core import installation


@pytest.mark.skipif(os.name == "nt", reason="Unix bootstrap; Windows uses cmd.exe")
def test_stable_launcher_tracks_new_install_and_quotes_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_MCP_DISCOVERY_DIR", str(tmp_path / "discovery"))
    first = tmp_path / "app one $literal.py"
    second = tmp_path / "app two ' quoted.py"
    first.write_text("import json,sys; print(json.dumps(['one',*sys.argv[1:]]))")
    second.write_text("import json,sys; print(json.dumps(['two',*sys.argv[1:]]))")
    launcher = installation.provision(sys.executable, first, sys.executable)
    argv = [str(launcher), "a b", "$(not-a-command)"]
    assert json.loads(subprocess.check_output(argv, text=True)) == ["one", "a b", "$(not-a-command)"]
    assert installation.provision(sys.executable, second, sys.executable) == launcher
    assert json.loads(subprocess.check_output(argv, text=True)) == ["two", "a b", "$(not-a-command)"]
    assert launcher.stat().st_mode & 0o077 == 0


class _Launched:
    """A launch whose opener (/usr/bin/open on macOS) exited normally."""

    def wait(self, timeout=None):
        return 0


_LAUNCHED = _Launched()


def test_cold_start_is_coalesced_and_respects_disable(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_MCP_DISCOVERY_DIR", str(tmp_path / "discovery"))
    calls = []
    monkeypatch.setattr(installation.subprocess, "Popen", lambda *a, **kw: calls.append(a) or _LAUNCHED)
    installation.provision(sys.executable, tmp_path / "mcp.py", sys.executable, enabled=False)
    assert not installation.start_app()
    installation.provision(sys.executable, tmp_path / "mcp.py", sys.executable, enabled=True)
    assert not installation.start_in_progress()
    assert installation.start_app()
    assert not installation.start_app()
    assert installation.start_in_progress()  # A second host waits for that start.
    assert len(calls) == 1


def test_a_slow_first_launch_still_counts_as_starting(tmp_path, monkeypatch):
    """Gatekeeper, shader cache and sign-in restore can exceed a minute; the
    agent must not be told Mixar is not installed while it is launching."""
    import os
    import time
    monkeypatch.setenv("MIXAR_MCP_DISCOVERY_DIR", str(tmp_path / "discovery"))
    monkeypatch.setattr(installation.subprocess, "Popen", lambda *a, **kw: _LAUNCHED)
    installation.provision(sys.executable, tmp_path / "mcp.py", sys.executable, enabled=True)
    assert installation.start_app()
    marker = installation.directory() / "starting"
    two_minutes_ago = time.time() - 120
    os.utime(marker, (two_minutes_ago, two_minutes_ago))
    assert installation.start_in_progress() and not installation.start_app()
    long_ago = time.time() - installation.STARTING_SECONDS - 1
    os.utime(marker, (long_ago, long_ago))
    assert not installation.start_in_progress() and installation.start_app()


def test_starting_ends_when_the_app_is_up_or_the_launch_fails(tmp_path, monkeypatch):
    """A quit or crashed launch must not read as "starting" for three minutes."""
    monkeypatch.setenv("MIXAR_MCP_DISCOVERY_DIR", str(tmp_path / "discovery"))
    monkeypatch.setattr(installation.subprocess, "Popen", lambda *a, **kw: _LAUNCHED)
    installation.provision(sys.executable, tmp_path / "mcp.py", sys.executable, enabled=True)
    assert installation.start_app() and installation.start_in_progress()
    installation.started()  # The relay published its record.
    assert not installation.start_in_progress()

    def fail(*a, **kw):
        raise OSError("cannot launch")
    monkeypatch.setattr(installation.subprocess, "Popen", fail)
    assert not installation.start_app() and not installation.start_in_progress()


def test_publishing_the_relay_ends_starting():
    source = (Path(installation.__file__).with_name("relay.py")).read_text()
    start = source[source.index("    def start(self):"):source.index("    def stop(self):")]
    assert "started()" in start


@pytest.mark.parametrize("status,starting", [(1, False), (0, True)])
def test_a_mac_app_that_cannot_be_opened_is_not_starting(tmp_path, monkeypatch, status, starting):
    """/usr/bin/open itself always starts; its exit status says whether Mixar could be opened."""
    from types import SimpleNamespace
    monkeypatch.setenv("MIXAR_MCP_DISCOVERY_DIR", str(tmp_path / "discovery"))
    app = tmp_path / "Mixar.app" / "Contents" / "MacOS" / "Mixar"
    app.parent.mkdir(parents=True)
    app.write_text("")
    monkeypatch.setattr(installation.sys, "platform", "darwin")
    commands = []
    monkeypatch.setattr(installation.subprocess, "Popen",
                        lambda command, **kw: commands.append(command) or SimpleNamespace(wait=lambda timeout: status))
    installation.provision(sys.executable, tmp_path / "mcp.py", app, enabled=True)
    assert installation.start_app() is starting
    assert commands[0][0] == "/usr/bin/open" and installation.start_in_progress() is starting
