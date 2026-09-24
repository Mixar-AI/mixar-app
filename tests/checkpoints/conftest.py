# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared harness for the turn-checkpoint suites.

Holds the `tc` fixture, which loads core/turn_checkpoints.py with its lazy
neighbours stubbed, so the capture/restore/rewind cases and the disk-budget
cases can live in separate modules without duplicating any of it."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

_SRC_ROOT = Path(__file__).parents[2] / "src" / "scripts"
_MIXAR_ROOT = _SRC_ROOT / "mixar"
_MODULES_ROOT = _MIXAR_ROOT / "modules"
_CHAT_ROOT = _MODULES_ROOT / "space_mixie_chat"
_CORE_ROOT = _CHAT_ROOT / "core"

if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))


class FakeSession:
    def __init__(self, state="idle", run_open=False, connected=True):
        self.state = SimpleNamespace(value=state)
        self._run_open = run_open
        self._connected = connected
        self.calls = []

    def get_state(self, scene):
        return self.state

    def run_open(self, scene):
        return self._run_open

    def is_connected(self, scene):
        return self._connected

    def set_run(self, scene, run_id, open_):
        self.calls.append(("set_run", run_id, open_))

    def clear_streaming(self):
        self.calls.append(("clear_streaming",))

    def set_connected(self, scene):
        self.calls.append(("set_connected",))

    def get_session_id(self, scene):
        return getattr(scene, "mixie_session_id", "")

    def clear_session_id(self, scene):
        scene.mixie_session_id = ""
        self.calls.append(("clear_session_id",))


@pytest.fixture
def tc(monkeypatch, tmp_path):
    """Load core/turn_checkpoints.py with its lazy neighbours stubbed."""
    for name, path in (
        ("mixar", _MIXAR_ROOT),
        ("mixar.modules", _MODULES_ROOT),
        ("mixar.modules.space_mixie_chat", _CHAT_ROOT),
        ("mixar.modules.space_mixie_chat.core", _CORE_ROOT),
    ):
        package = ModuleType(name)
        package.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, package)

    project_dir = tmp_path / "projects"
    project_dir.mkdir()
    bpy = MagicMock(name="bpy")
    bpy.data.filepath = str(project_dir / "lamp.mixar")
    bpy.data.scenes = []
    monkeypatch.setitem(sys.modules, "bpy", bpy)

    session = FakeSession()
    stub = {
        "mixar.modules.space_mixie_chat.core.session": {"get_session_manager": lambda: session},
        "mixar.modules.space_mixie_chat.core.turn_events": {"drop_scene": MagicMock()},
        "mixar.modules.space_mixie_chat.core.ui_utils": {"bump_layout_epoch": MagicMock(), "redraw_chat_areas": MagicMock()},
        "mixar.modules.space_mixie_chat.core.markdown_parser": {"clear_incremental_cache": MagicMock()},
        "mixar.modules.space_mixie_chat.core.message_helpers": {"add_agent_message": MagicMock()},
        "mixar.modules.agent_bubble": {},
        "mixar.modules.agent_bubble.core": {},
        "mixar.modules.agent_bubble.core.bubble_lifecycle": {"close_restored_agent_bubble_windows": MagicMock()},
        "mixar.modules.common": {},
        "mixar.modules.common.agent_rpc": {},
        "mixar.modules.common.agent_rpc.client": {"request": MagicMock()},
    }
    for name, attrs in stub.items():
        module = ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)

    module_name = "mixar.modules.space_mixie_chat.core.turn_checkpoints"
    spec = importlib.util.spec_from_file_location(module_name, _CORE_ROOT / "turn_checkpoints.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)

    root = lambda: str(tmp_path / "checkpoints")  # noqa: E731
    monkeypatch.setattr(module, "checkpoints_root", root)
    monkeypatch.setattr(module.checkpoint_store, "checkpoints_root", root)   # session_dir & co. live there
    monkeypatch.setattr(module, "DEV_MODE", False)
    module.SessionState = SimpleNamespace(IDLE=session.state)   # can_restore compares by identity
    module._has_cache.clear()

    # save_as_mainfile writes whatever the test says the document holds.
    document = {"bytes": b"scene-v1"}

    def save_as(filepath="", copy=False, **_kw):
        with open(filepath, "wb") as f:
            f.write(document["bytes"])
        return {'FINISHED'}

    bpy.ops.wm.save_as_mainfile.side_effect = save_as
    return SimpleNamespace(m=module, bpy=bpy, session=session, document=document)
