# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Chat image paste on Linux reads Wayland clipboards too.

``_paste_linux`` used xclip only, so an image paste on a Wayland session did
nothing. Under ``WAYLAND_DISPLAY`` it now tries ``wl-paste`` first and falls
back to xclip (XWayland); on X11 it runs xclip alone.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.space_mixie_chat.core import clipboard_image as CI  # noqa: E402


def _fake_run(calls, answers):
    def run(cmd, **kwargs):
        calls.append(cmd[0])
        answer = answers[cmd[0]]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(returncode=0, stdout=answer)
    return run


def test_wayland_uses_wl_paste(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(CI.subprocess, "run", _fake_run(calls, {"wl-paste": b"png"}))
    out = tmp_path / "p.png"
    assert CI._paste_linux(str(out)) == str(out)
    assert calls == ["wl-paste"] and out.read_bytes() == b"png"


def test_wayland_falls_back_to_xclip(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(CI.subprocess, "run", _fake_run(
        calls, {"wl-paste": FileNotFoundError(), "xclip": b"png"}))
    out = tmp_path / "p.png"
    assert CI._paste_linux(str(out)) == str(out)
    assert calls == ["wl-paste", "xclip"]


def test_x11_runs_xclip_only(monkeypatch, tmp_path):
    calls = []
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(CI.subprocess, "run", _fake_run(
        calls, {"xclip": subprocess.TimeoutExpired("xclip", 5)}))
    assert CI._paste_linux(str(tmp_path / "p.png")) is None
    assert calls == ["xclip"]
