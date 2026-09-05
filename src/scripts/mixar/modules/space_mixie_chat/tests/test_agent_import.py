# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent file import (#1251) — the client-side picker bridge.

Pins the path invariant end to end: the native open dialog stores the path
in a process-local vault; the re-dispatch POSTs only the action value; the
import runs locally and reports only success + object names; the vault is
consumed once and cleared on .blend load.
"""

import importlib
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import (  # noqa: E402
    agent_import,
    import_source,
)


@pytest.fixture(autouse=True)
def _clean_vault():
    import_source.clear_all_sources()
    yield
    import_source.clear_all_sources()


# ---------------------------------------------------------------------------
# the vault (mirror of export_destination's contract)
# ---------------------------------------------------------------------------


def test_source_store_is_process_local_and_consumed_once():
    import_source.set_source("sess-1", "/tmp/chair.obj")
    assert import_source.has_source("sess-1") is True
    assert import_source.pop_source("sess-1") == "/tmp/chair.obj"
    assert import_source.pop_source("sess-1") is None  # consumed once
    assert import_source.has_source("sess-1") is False


def test_source_store_requires_ids():
    with pytest.raises(ValueError):
        import_source.set_source("", "/tmp/x.obj")
    with pytest.raises(ValueError):
        import_source.set_source("sess-1", "")


# ---------------------------------------------------------------------------
# run_import — importer dispatch + honest reporting
# ---------------------------------------------------------------------------


class _FakeBpyData:
    def __init__(self, objects):
        self.objects = objects


class _FakeObj:
    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent


@pytest.fixture
def fake_bpy(monkeypatch):
    holder = MagicMock()
    state = {"objects": [], "import_calls": []}

    def install(objects, op_result=("FINISHED",), importer="obj"):
        state["objects"] = []
        holder.data = _FakeBpyData(state["objects"])
        op = MagicMock(return_value=op_result)

        def _op(**kwargs):
            # The import materializes the objects.
            state["objects"].extend(objects)
            return op_result

        op.side_effect = _op
        state["import_calls"].append(op)
        if importer == "obj":
            holder.ops = MagicMock()
            holder.ops.wm.obj_import = op
        elif importer == "fbx":
            holder.ops = MagicMock()
            holder.ops.import_scene.fbx = op
        elif importer == "gltf":
            holder.ops = MagicMock()
            holder.ops.import_scene.gltf = op
        elif importer == "usd":
            holder.ops = MagicMock()
            holder.ops.wm.usd_import = op
        # no selected objects / active object handling needed
        holder.context.view_layer.objects.active = None
        holder.ops.object.select_all.poll.return_value = False
        monkeypatch.setattr(agent_import, "bpy", holder)
        return op

    install.state = state
    return install


def test_run_import_without_source_fails_cleanly():
    result = agent_import.run_import("sess-x", {})
    assert result["success"] is False
    assert "No file was selected" in result["error"]


def test_run_import_obj_reports_names_only(fake_bpy, monkeypatch):
    op = fake_bpy(
        [_FakeObj("Chair"), _FakeObj("Chair_Leg", parent=None)],
        importer="obj",
    )
    import_source.set_source("sess-1", "/tmp/chair.obj")
    with patch.object(agent_import.os.path, "isfile", return_value=True):
        result = agent_import.run_import("sess-1", {})
    assert result["success"] is True
    assert result["imported_object_names"] == ["Chair", "Chair_Leg"]
    assert result["object_count"] == 2
    # The path NEVER comes back — basename only.
    assert "/tmp/" not in str(result)
    assert result["file_basename"] == "chair.obj"
    op.assert_called_once()


def test_run_import_fbx_glb_usd_dispatch(fake_bpy):
    for importer, ext in (("fbx", ".fbx"), ("gltf", ".glb"), ("usd", ".usd")):
        import_source.set_source("sess-d", f"/tmp/model{ext}")
        fake_bpy([_FakeObj("M")], importer=importer)
        with patch.object(agent_import.os.path, "isfile", return_value=True):
            result = agent_import.run_import("sess-d", {})
        assert result["success"] is True, (importer, result)


def test_run_import_unsupported_extension(fake_bpy):
    import_source.set_source("sess-u", "/tmp/model.step")
    with patch.object(agent_import.os.path, "isfile", return_value=True):
        result = agent_import.run_import("sess-u", {})
    assert result["success"] is False
    assert "No importer" in result["error"]


def test_run_import_missing_file_reports_basename_only(fake_bpy):
    fake_bpy([_FakeObj("M")], importer="obj")
    import_source.set_source("sess-m", "/tmp/gone.obj")
    with patch.object(agent_import.os.path, "isfile", return_value=False):
        result = agent_import.run_import("sess-m", {})
    assert result["success"] is False
    assert "/tmp/" not in result["error"]
    assert "gone.obj" in result["error"]


def test_run_import_failed_operator_consumes_source(fake_bpy):
    fake_bpy([_FakeObj("M")], op_result=("CANCELLED",), importer="obj")
    import_source.set_source("sess-f", "/tmp/broken.obj")
    with patch.object(agent_import.os.path, "isfile", return_value=True):
        result = agent_import.run_import("sess-f", {})
    assert result["success"] is False
    # Consumed once even on failure — same cleanup semantics as success.
    assert import_source.pop_source("sess-f") is None


def test_run_import_count_is_uncapped_while_names_are(fake_bpy):
    # A pack with more roots than the name cap: the names ride the payload
    # bounded, the COUNT tells the truth.
    fake_bpy([_FakeObj(f"Part.{i:03d}") for i in range(25)], importer="obj")
    import_source.set_source("sess-c", "/tmp/pack.obj")
    with patch.object(agent_import.os.path, "isfile", return_value=True):
        result = agent_import.run_import("sess-c", {})
    assert result["success"] is True
    assert len(result["imported_object_names"]) == agent_import._MAX_NAMES
    assert result["object_count"] == 25
    assert "warning" not in result


# ---------------------------------------------------------------------------
# picker filter — derived from the importer map, never from the backend
# ---------------------------------------------------------------------------


def test_picker_filter_glob_lists_every_importable_extension(monkeypatch):
    glob = agent_import.picker_filter_glob()
    patterns = glob.split(";")
    # No empty pattern (a leading ";" used to produce one).
    assert all(p.startswith("*.") for p in patterns), patterns
    assert set(patterns) == {
        "*.obj", "*.fbx", "*.glb", "*.gltf", "*.usd", "*.usdz", "*.usda", "*.usdc",
    }
    # Every offered extension resolves to a native importer — the filter can
    # never offer a file run_import would then refuse.
    fake_ops = SimpleNamespace(
        wm=SimpleNamespace(obj_import=object(), usd_import=object()),
        import_scene=SimpleNamespace(fbx=object(), gltf=object()),
    )
    monkeypatch.setattr(agent_import, "bpy", SimpleNamespace(ops=fake_ops))
    for pattern in patterns:
        assert agent_import._importer_op(pattern[1:]) is not None, pattern
    assert agent_import._importer_op(".step") is None


def test_formats_hint_is_a_label_not_a_filter():
    assert agent_import.formats_hint("fbx,glb,obj,usd") == (
        "Agent expects: FBX, GLB, OBJ, USD"
    )
    assert agent_import.formats_hint("") == ""
    # The hint never feeds the glob.
    assert agent_import.picker_filter_glob() == agent_import.picker_filter_glob()


# ---------------------------------------------------------------------------
# picker operator source hygiene
# ---------------------------------------------------------------------------


def _picker_source() -> str:
    return open(
        os.path.join(
            os.path.dirname(__file__),
            "..", "ui", "operators", "agent_import_ops.py",
        )
    ).read()


def test_picker_operator_never_puts_path_in_the_resume():
    src = _picker_source()
    # The re-dispatch carries ONLY the action value (mirror of the export
    # picker's invariant test).
    assert 'text=self.filepath' not in src
    assert 'action_value="import_source_selected"' in src
    assert "set_source(self.session_id, self.filepath)" in src


def test_picker_operator_filter_comes_from_the_importer_map():
    src = _picker_source()
    assert "default=picker_filter_glob()" in src
    # The backend's `formats` is a hint (side-panel label) — it must never
    # rewrite the filter and hide importable files.
    assert "self.filter_glob =" not in src
    assert "formats_hint(self.formats)" in src


def test_slot_action_clears_stale_import_source_on_failure_paths():
    src = open(
        os.path.join(
            os.path.dirname(__file__),
            "..", "ui", "operators", "chat_special_ops.py",
        )
    ).read()
    # Mirror of the export picker: not-connected and failed-dispatch both
    # drop the vault entry so the next click re-opens the picker.
    assert src.count("from ...core.import_source import clear_source") == 2
