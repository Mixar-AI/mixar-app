# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The MCP connector launcher never writes bytecode into the install directory.

It runs the bundle's own Python, so a `__pycache__` written beside the bundled
sources broke the signed macOS app ("Mixar is damaged", issue #2058). The
launcher shares the app's bytecode cache (`sys.pycache_prefix`) or writes none,
and every app start rewrites a launcher left by an older version.
"""

import ast
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from mixar.modules.mcp_bridge.core import installation


def _install(tmp_path):
    """A stand-in install directory: an entry script that imports a sibling module."""
    install = tmp_path / "Mixar.app" / "scripts"
    install.mkdir(parents=True)
    (install / "helper_mod.py").write_text("VALUE = 'imported'\n")
    entry = install / "entry.py"
    entry.write_text("import sys\nsys.path.insert(0, %r)\nimport helper_mod\nprint(helper_mod.VALUE)\n" % str(install))
    return install, entry


def _bytecode_under(path):
    return sorted(p for p in path.rglob("*.pyc"))


@pytest.mark.skipif(os.name == "nt", reason="Unix launcher; the .cmd shares the command line")
def test_the_launcher_writes_bytecode_to_the_app_cache_not_the_install(tmp_path, monkeypatch):
    cache = tmp_path / "Caches" / "Mixar" / "pycache"
    monkeypatch.setattr(installation.sys, "pycache_prefix", str(cache))
    install, entry = _install(tmp_path)
    launcher = installation.provision(sys.executable, entry, sys.executable)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    assert subprocess.check_output([str(launcher)], text=True, env=env).strip() == "imported"
    assert _bytecode_under(install) == []
    # Python mirrors the source's absolute directory under the prefix.
    cached = cache / str(install).lstrip(os.sep) / ("helper_mod.cpython-%d%d.pyc" % sys.version_info[:2])
    assert cached.is_file()


@pytest.mark.skipif(os.name == "nt", reason="Unix launcher; the .cmd shares the command line")
def test_without_an_app_cache_the_launcher_writes_no_bytecode(tmp_path, monkeypatch):
    monkeypatch.setattr(installation.sys, "pycache_prefix", None)
    install, entry = _install(tmp_path)
    launcher = installation.provision(sys.executable, entry, sys.executable)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    assert subprocess.check_output([str(launcher)], text=True, env=env).strip() == "imported"
    assert _bytecode_under(tmp_path) == []
    assert " -B " in launcher.read_text()


def test_both_launcher_forms_carry_the_bytecode_arguments():
    """The Windows .cmd and the Unix script are written from one command list."""
    tree = ast.parse(Path(installation.__file__).read_text(encoding="utf-8"))
    provision = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "provision")
    source = ast.unparse(provision)
    assert "command = [str(python), *_bytecode_args(), str(script)]" in source
    assert "subprocess.list2cmdline(command)" in source
    assert "shlex.join(command)" in source


def test_every_app_start_rewrites_an_older_launcher(tmp_path, monkeypatch):
    """runtime._tick provisions on its first tick whether MCP is on or off, so a
    launcher written by an older Mixar (no bytecode flag) is replaced at once."""
    from mixar.modules.mcp_bridge.core import runtime, tool_snapshot
    from mixar.modules.common.ui_control.core import service

    cache = tmp_path / "pycache"
    monkeypatch.setattr(installation.sys, "pycache_prefix", str(cache))
    old = installation.directory() / "mixar-mcp"
    old.parent.mkdir(parents=True)
    old.write_text("#!/bin/sh\nexec /old/python3.13 /old/mcp.py \"$@\"\n")

    wm = SimpleNamespace(mixie_instance_id="fixture", mixie_chat_is_logged_in=False,
                         mixie_chat_session_expired=False)
    monkeypatch.setattr(runtime, "bpy", SimpleNamespace(
        context=SimpleNamespace(window_manager=wm, scene=SimpleNamespace(name="Scene", mixie_session_id="")),
        app=SimpleNamespace(binary_path=str(tmp_path / "Mixar.app/Contents/MacOS/Mixar")),
        utils=SimpleNamespace(resource_path=lambda kind: str(tmp_path / "Mixar.app/Contents/Resources/5.2"))))
    monkeypatch.setattr(runtime, "get_config", lambda: {"mcp_enabled": False})
    monkeypatch.setattr(runtime, "get_server_url", lambda: "http://127.0.0.1:1")
    monkeypatch.setattr(runtime, "_registered", True)
    monkeypatch.setattr(runtime, "_provisioned", None)  # A fresh app process.
    monkeypatch.setattr(runtime, "_server", None)
    for module, name, value in (
            ("mixar.modules.space_mixie_chat.core.connection_manager", "get_connection_manager",
             lambda: SimpleNamespace(is_connected=False)),
            ("mixar.modules.space_mixie_chat.core.session", "get_session_manager",
             lambda: SimpleNamespace(instance_id="fixture"))):
        monkeypatch.setitem(sys.modules, module, SimpleNamespace(**{name: value}))
    monkeypatch.setattr(service, "unregister", lambda *a, **kw: None)
    monkeypatch.setattr(tool_snapshot, "forget", lambda: None)

    assert runtime._tick() == 1.0
    launcher = installation.directory() / ("mixar-mcp.cmd" if os.name == "nt" else "mixar-mcp")
    text = launcher.read_text()
    assert "pycache_prefix=" + str(cache) in text and "/old/" not in text
    assert runtime._provisioned is False
