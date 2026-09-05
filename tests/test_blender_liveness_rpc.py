# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""blender.liveness: WS-thread liveness probe for the backend timeout breaker.

The backend counts consecutive script timeouts toward a "Blender stopped
responding" breaker. Long-but-healthy scripts (dense GLB export, texture
apply) used to trip it because the client could not prove it was busy rather
than frozen. blender.liveness is answered on the WebSocket receive thread
(never queued to the main thread, never touching bpy), so a busy instance
answers it and takes no strike.
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "src/scripts/mixar/modules/space_mixie_chat/core/jsonrpc_client.py"
HANDLERS = ROOT / "src/scripts/mixar/modules/space_mixie_chat/core/main_thread_executor.py"
CONSTANTS = ROOT / "src/scripts/mixar/modules/space_mixie_chat/constants.py"


def test_liveness_method_and_capability_declared():
    constants = CONSTANTS.read_text()
    assert 'BLENDER_LIVENESS = "blender.liveness"' in constants
    client = CLIENT.read_text()
    assert '"liveness",' in client  # handshake capability


def test_liveness_is_dispatched_and_answers_without_bpy_or_main_thread():
    client = CLIENT.read_text()
    assert "elif method == JSONRPCMethod.BLENDER_LIVENESS:" in client
    assert "self._handle_liveness(request_id)" in client
    offset = client.index("def _handle_liveness")
    block = client[offset : client.index("def _handle_execute_script", offset)]
    # The probe path must stay off the main thread and off bpy — it is the
    # ONLY thing that can answer while a script hogs the main thread.
    assert "queue_response(request_id" in block
    assert "bpy." not in block
    assert "run_on_main_thread" not in block


def test_inflight_tracker_is_set_and_cleared_around_execute():
    handlers = HANDLERS.read_text()
    assert "def get_inflight_script" in handlers
    offset = handlers.index("def _process_one_request")
    block = handlers[offset:]
    assert "_set_inflight(tool_name, request_id, session_id)" in block
    assert "_clear_inflight()" in block
    # set happens before execute, clear before the response leaves.
    assert block.index("_set_inflight(") < block.index("executor.execute(script)")
    assert block.index("_clear_inflight()") < block.index("client.queue_response(request_id, result_dict)")


def _load_handlers_module(monkeypatch):
    for name in ("bpy", "bmesh", "mathutils", "bpy_extras", "imbuf"):
        monkeypatch.setitem(sys.modules, name, MagicMock(name=name))
    chat_root = ROOT / "src/scripts/mixar/modules/space_mixie_chat"
    for name, path in (
        ("mixar", ROOT / "src/scripts/mixar"),
        ("mixar.modules", ROOT / "src/scripts/mixar/modules"),
        ("mixar.modules.space_mixie_chat", chat_root),
        ("mixar.modules.space_mixie_chat.core", chat_root / "core"),
    ):
        package = ModuleType(name)
        package.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, package)
    module_name = "mixar.modules.space_mixie_chat.core.main_thread_executor"
    spec = importlib.util.spec_from_file_location(module_name, chat_root / "core" / "main_thread_executor.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def test_inflight_getter_reports_elapsed_and_idle(monkeypatch):
    module = _load_handlers_module(monkeypatch)
    assert module.get_inflight_script() is None
    module._set_inflight("rigging.export", "req-1", "sess-1")
    info = module.get_inflight_script()
    assert info is not None
    assert info["tool_name"] == "rigging.export"
    assert info["request_id"] == "req-1"
    assert "elapsed_s" in info
    assert "_started" not in info  # internal clock never crosses the wire
    module._clear_inflight()
    assert module.get_inflight_script() is None
