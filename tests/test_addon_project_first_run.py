# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression coverage for Add-on Project Mode's unlinked first send."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "src/scripts/mixar/modules/agent_bubble/ui/header.py"
LINK_OPERATORS = ROOT / "src/scripts/mixar/modules/addon_project/ui/operators.py"
CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/chat_ops.py"
QUICK_PROMPT = (
    ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/quick_prompt_ops.py"
)


def test_floating_agent_bubble_keeps_drag_handle_without_project_controls():
    source = HEADER.read_text(encoding="utf-8")

    assert "draw_project_controls" not in source
    centered_block = source.split("handle_row.alignment = 'CENTER'", 1)[1].split(
        "layout.separator_spacer()",
        1,
    )[0]
    assert 'handle_row.label(text="▬▬▬▬")' in centered_block


def test_send_paths_proceed_after_ensuring_project():
    link_source = LINK_OPERATORS.read_text(encoding="utf-8")
    chat_source = CHAT.read_text(encoding="utf-8")
    quick_source = QUICK_PROMPT.read_text(encoding="utf-8")

    # Zero-question first Send: the helper links the Preference root
    # (created on first use by link_workspace_root), and the SAME send
    # falls through to build_project_context — no picker, no "press Send
    # again", and the one first-time notice points at Preferences.
    assert "def ensure_addon_project_ready(" in link_source
    assert "link_workspace_root()" in link_source
    assert "choose_root" not in link_source
    assert "under Mixar Preferences" in link_source
    assert "bpy.ops.mixie_chat.send_message(message_override=message_text)" in quick_source
    for source in (chat_source,):
        assert "if not ensure_addon_project_ready(self):" in source
        assert source.index("ensure_addon_project_ready(self)") < source.index(
            "build_project_context(scene)"
        )

    invoke_source = quick_source.split("def invoke", 1)[1].split("def draw", 1)[0]
    assert 'mixie_chat_quick_prompt_input = ""' not in invoke_source
