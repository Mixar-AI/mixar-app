# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scene snapshot names the open file; it never carries its path."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import bpy  # noqa: E402  (the root conftest's stub)

from mixar.modules.connector.core import scene_snapshot  # noqa: E402


def _scene(monkeypatch, filepath):
    monkeypatch.setattr(bpy.context.scene, "objects", [])
    monkeypatch.setattr(bpy.context.scene, "name", "Scene")
    monkeypatch.setattr(bpy.context.scene, "frame_current", 1)
    monkeypatch.setattr(bpy.data, "filepath", filepath)


def test_saved_file_is_reported_by_basename_only(monkeypatch):
    _scene(monkeypatch, "/home/alice/projects/secret-client/hero.blend")
    snapshot = scene_snapshot.scene_snapshot()
    assert snapshot["file_name"] == "hero.blend"
    assert snapshot["saved"] is True
    assert "filepath" not in snapshot
    assert "alice" not in repr({k: v for k, v in snapshot.items() if k != "render_engine"})


def test_unsaved_file_reports_no_name(monkeypatch):
    _scene(monkeypatch, "")
    snapshot = scene_snapshot.scene_snapshot()
    assert snapshot["file_name"] == ""
    assert snapshot["saved"] is False
