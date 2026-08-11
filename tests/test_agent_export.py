# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Standalone contracts for the export agent's client privacy boundary."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load_store():
    path = ROOT / "src/scripts/mixar/modules/space_mixie_chat/core/export_destination.py"
    spec = importlib.util.spec_from_file_location("export_destination_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_destination_is_process_local_and_consumed_once():
    store = _load_store()
    store.set_destination("session-a", "C:/private/model.glb")
    assert store.has_destination("session-a")
    assert store.pop_destination("session-a") == "C:/private/model.glb"
    assert store.pop_destination("session-a") is None


def test_agent_input_resume_never_contains_local_path():
    operator_source = (ROOT / (
        "src/scripts/mixar/modules/space_mixie_chat/ui/operators/agent_export_ops.py"
    )).read_text(encoding="utf-8")
    sse_source = (ROOT / (
        "src/scripts/mixar/modules/space_mixie_chat/core/sse_handler.py"
    )).read_text(encoding="utf-8")
    assert 'action_value="export_destination_selected"' in operator_source
    assert 'text=self.filepath' not in operator_source
    assert '"action": action' in sse_source
    assert '"text": text' in sse_source
