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
HEADER = ROOT / "src/scripts/mixar/modules/agent_bubble/ui/header.py"
CHAT_HEADER = ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/header.py"
LINK_OPERATORS = ROOT / "src/scripts/mixar/modules/addon_project/ui/operators.py"
PROJECT_MENU = ROOT / "src/scripts/mixar/modules/addon_project/ui/menus.py"
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
        self.labels = []
        self.menus = []
        self.enabled = True

    def row(self, **_kwargs):
        self.row_calls += 1
        return self

    def operator(self, operator_id, **kwargs):
        self.operators.append((operator_id, kwargs))
        return SimpleNamespace()

    def label(self, **kwargs):
        self.labels.append(kwargs)

    def menu(self, menu_id, **kwargs):
        self.menus.append((menu_id, kwargs))
        return SimpleNamespace()


def test_unlinked_compact_control_can_render_in_existing_composer_row():
    controls = _load_controls()
    layout = _RecordingLayout()
    scene = SimpleNamespace(
        mixie_chat_mode="ADDON_PROJECT",
        mixie_addon_project_id="",
    )

    controls.draw_project_controls(layout, scene, compact=True, inline=True)

    # The fixed-height Agent Bubble composer row holds at most two small
    # controls: New Add-on plus the workspace menu (icon-only in compact).
    assert layout.row_calls == 0
    assert layout.operators == [(
        "mixar.addon_project_new",
        {"text": "New Add-on", "icon": "FILE_NEW"},
    )]
    assert layout.menus == [(
        "MIXAR_MT_addon_project_workspace",
        {"text": "", "icon": "DOWNARROW_HLT"},
    )]


def test_agent_bubble_composer_keeps_only_first_run_project_setup():
    source = FOOTER.read_text(encoding="utf-8")

    assert "setup_only=True" in source


def test_linked_project_controls_use_clear_primary_actions_and_more_menu():
    controls = _load_controls()
    layout = _RecordingLayout()
    scene = SimpleNamespace(
        mixie_chat_mode="ADDON_PROJECT",
        mixie_addon_project_id="project-id",
        mixie_addon_project_name="studio_addon",
        mixie_chat_state="IDLE",
    )

    controls.draw_project_controls(layout, scene)

    assert layout.labels == [{"text": "studio_addon", "icon": "FILE_SCRIPT"}]
    assert layout.operators == [
        (
            "mixar.addon_project_open_entrypoint",
            {"text": "Open Source", "icon": "TEXT"},
        ),
        (
            "mixar.addon_project_run_checks",
            {"text": "Test & Reload", "icon": "CHECKMARK"},
        ),
    ]
    # The workspace menu (set active add-on, enable/disable, change root)
    # sits beside the labelled More menu (entrypoint / undo-last / unlink).
    assert layout.menus == [
        (
            "MIXAR_MT_addon_project_workspace",
            {"text": "", "icon": "DOWNARROW_HLT"},
        ),
        (
            "MIXAR_MT_addon_project_more",
            {"text": "More", "icon": "DOWNARROW_HLT"},
        ),
    ]


def test_floating_agent_bubble_keeps_drag_handle_without_project_controls():
    source = HEADER.read_text(encoding="utf-8")

    assert "draw_project_controls" not in source
    centered_block = source.split("handle_row.alignment = 'CENTER'", 1)[1].split(
        "layout.separator_spacer()",
        1,
    )[0]
    assert 'handle_row.label(text="▬▬▬▬")' in centered_block


def test_linked_project_controls_remain_in_full_mixie_chat_header():
    source = CHAT_HEADER.read_text(encoding="utf-8")

    assert "draw_project_controls(layout, scene)" in source


def test_linked_project_is_not_duplicated_in_the_composer():
    controls = _load_controls()
    layout = _RecordingLayout()
    scene = SimpleNamespace(
        mixie_chat_mode="ADDON_PROJECT",
        mixie_addon_project_id="project-id",
    )

    controls.draw_project_controls(
        layout,
        scene,
        compact=True,
        inline=True,
        setup_only=True,
    )

    assert layout.operators == []
    assert layout.labels == []
    assert layout.menus == []


def test_secondary_project_actions_are_explicitly_named():
    source = PROJECT_MENU.read_text(encoding="utf-8")

    assert 'text="Choose Entrypoint..."' in source
    assert 'text="Undo Last AI Change"' in source
    assert 'text="Unlink Project"' in source


def test_send_paths_proceed_after_ensuring_project():
    link_source = LINK_OPERATORS.read_text(encoding="utf-8")
    chat_source = CHAT.read_text(encoding="utf-8")
    quick_source = QUICK_PROMPT.read_text(encoding="utf-8")

    # Zero-question first Send: the helper auto-creates the default root,
    # links it, and the SAME send falls through to build_project_context —
    # no picker, no "press Send again".
    assert "def ensure_addon_project_ready(" in link_source
    assert "ensure_workspace_root()" in link_source
    assert "link_workspace_root()" in link_source
    for source in (chat_source, quick_source):
        assert "if not ensure_addon_project_ready(self):" in source
        assert source.index("ensure_addon_project_ready(self)") < source.index(
            "build_project_context(scene)"
        )

    invoke_source = quick_source.split("def invoke", 1)[1].split("def draw", 1)[0]
    assert 'mixie_chat_quick_prompt_input = ""' not in invoke_source
