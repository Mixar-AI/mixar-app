# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression coverage for Add-on Project Mode's unlinked first send."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
CONTROLS = ROOT / "src/scripts/mixar/modules/addon_project/ui/controls.py"
FOOTER = ROOT / "src/scripts/mixar/modules/agent_bubble/ui/panels/footer_panel.py"
LINK_OPERATORS = ROOT / "src/scripts/mixar/modules/addon_project/ui/operators.py"
CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/chat_ops.py"
QUICK_PROMPT = (
    ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/quick_prompt_ops.py"
)


def _load_controls():
    spec = importlib.util.spec_from_file_location("addon_project_controls_test", CONTROLS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingLayout:
    def __init__(self):
        self.row_calls = 0
        self.operators = []

    def row(self, **_kwargs):
        self.row_calls += 1
        return self

    def operator(self, operator_id, **kwargs):
        self.operators.append((operator_id, kwargs))
        return SimpleNamespace()


def test_unlinked_compact_control_can_render_in_existing_composer_row():
    controls = _load_controls()
    layout = _RecordingLayout()
    scene = SimpleNamespace(
        mixie_chat_mode="ADDON_PROJECT",
        mixie_addon_project_id="",
    )

    controls.draw_project_controls(layout, scene, compact=True, inline=True)

    assert layout.row_calls == 0
    assert layout.operators == [(
        "mixar.addon_project_link",
        {"text": "Create / Link", "icon": "FILE_FOLDER"},
    )]


def test_agent_bubble_places_project_setup_in_its_visible_action_row():
    source = FOOTER.read_text(encoding="utf-8")

    assert "draw_project_controls(action_row, scene, compact=True, inline=True)" in source
    assert "draw_project_controls(layout, scene, compact=True)" not in source


def test_send_paths_open_native_picker_before_building_project_context():
    link_source = LINK_OPERATORS.read_text(encoding="utf-8")
    chat_source = CHAT.read_text(encoding="utf-8")
    quick_source = QUICK_PROMPT.read_text(encoding="utf-8")

    assert "bpy.ops.mixar.addon_project_link('INVOKE_DEFAULT')" in link_source
    assert chat_source.index("prompt_for_addon_project_link(self)") < chat_source.index(
        "build_project_context(scene)"
    )
    assert quick_source.index("prompt_for_addon_project_link(self)") < quick_source.index(
        "build_project_context(scene)"
    )

    invoke_source = quick_source.split("def invoke", 1)[1].split("def draw", 1)[0]
    assert 'mixie_chat_quick_prompt_input = ""' not in invoke_source
