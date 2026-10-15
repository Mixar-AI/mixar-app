# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""``export_selected_mesh`` never leaves its temp file behind: none is created
without a selection, and an exporter or read failure removes it."""

import sys
from pathlib import Path
import os
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.common.job_queue.core import model_io as MIO  # noqa: E402


class _Obj:
    def __init__(self, name, type_="MESH"):
        self.name, self.type = name, type_

    def select_set(self, _value):
        pass


class _Objects(list):
    active = None

    def __contains__(self, name):
        return any(o.name == name for o in self)


def _context(selected):
    objects = _Objects(selected)
    return SimpleNamespace(
        selected_objects=list(selected),
        view_layer=SimpleNamespace(objects=objects),
    )


@pytest.fixture
def temp_files(monkeypatch, tmp_path):
    made = []

    # mkstemp returns an OS-level fd that the caller closes itself.
    def _mkstemp_fd(suffix="", prefix=""):
        path = tmp_path / f"{prefix}{len(made)}{suffix}"
        fd = os.open(path, os.O_CREAT | os.O_RDWR)
        made.append(path)
        return fd, str(path)

    monkeypatch.setattr(MIO.tempfile, "mkstemp", _mkstemp_fd)
    return made


def test_no_selection_creates_no_temp_file(temp_files):
    with pytest.raises(ValueError):
        MIO.export_selected_mesh(_context([_Obj("Lamp", "LIGHT")]))
    assert temp_files == []


def test_exporter_failure_removes_the_temp_file(temp_files, monkeypatch):
    def _boom(**_kwargs):
        Path(_kwargs["filepath"]).write_bytes(b"partial")
        raise RuntimeError("exporter crashed")

    monkeypatch.setattr(MIO.bpy.ops.export_scene, "gltf", _boom, raising=False)
    with pytest.raises(RuntimeError):
        MIO.export_selected_mesh(_context([_Obj("Cube")]))
    assert len(temp_files) == 1
    assert not temp_files[0].exists()


def test_success_returns_bytes_and_removes_the_temp_file(temp_files, monkeypatch):
    def _write(**kwargs):
        Path(kwargs["filepath"]).write_bytes(b"glTF")

    monkeypatch.setattr(MIO.bpy.ops.export_scene, "gltf", _write, raising=False)
    data, name = MIO.export_selected_mesh(_context([_Obj("Cube")]))
    assert (data, name) == (b"glTF", "export.glb")
    assert not temp_files[0].exists()
