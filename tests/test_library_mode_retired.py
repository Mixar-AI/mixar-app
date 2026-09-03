# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Library mode is retired: unlisted in the dropdown and unreachable.

``scene.mixie_chat_mode`` is a static ``EnumProperty`` and every mode
dropdown enumerates it — the C++ chat footer, the agent bubble's footer
panel and the bubble menu all bind that one property — so dropping the item
hides it everywhere at once. ``bpy`` is a MagicMock in this suite, so the
property is never really registered; these are source-level contracts.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"
BUBBLE = ROOT / "src/scripts/mixar/modules/agent_bubble"

CHAT_PROPS = CHAT / "ui/properties/chat_props.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_library_is_not_a_mode_enum_item():
    props = _read(CHAT_PROPS)

    assert "('LIBRARY'," not in props
    # The modes that remain.
    for identifier in ("('AGENT',", "('GENERATE',", "('ADDON_PROJECT',"):
        assert identifier in props


def test_enum_value_4_stays_reserved():
    """Reusing the retired value would silently reopen old .blend files in
    whatever mode inherited it — the same trap the legacy ASK value (2) set."""
    props = _read(CHAT_PROPS)

    # No item may claim 2 or 4; the remaining three are 0, 1 and 3.
    assert ", 4)," not in props.split("mixie_chat_mode")[1].split("]")[0]
    assert ", 2)," not in props.split("mixie_chat_mode")[1].split("]")[0]
    assert "'FILE_SCRIPT', 3)" in props


def test_every_mode_dropdown_binds_the_same_property():
    """Nothing may draw its own hand-rolled mode list, or unlisting the item
    in one place would leave Library on screen in another."""
    footer = _read(
        ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_footer.cc"
    )
    bubble_footer = _read(BUBBLE / "ui/panels/footer_panel.py")
    bubble_menu = _read(BUBBLE / "ui/menus/agent_bubble_menu.py")

    assert 'RNA_struct_find_property(&scene_ptr, "mixie_chat_mode")' in footer
    assert 'prop(scene, "mixie_chat_mode"' in bubble_footer
    assert 'prop(scene, "mixie_chat_mode"' in bubble_menu


def test_no_other_route_can_enter_library_mode():
    """The quick-prompt operators are the only non-dropdown mode writers."""
    special_ops = _read(CHAT / "ui/operators/chat_special_ops.py")
    props = _read(CHAT_PROPS)

    # The agent-driven prompt operator's allowlist.
    assert "in {'AGENT', 'GENERATE'}" in special_ops
    assert "'LIBRARY'" not in special_ops
    # The quick-prompt dialog's own mode enum never offered it either.
    quick_prompt_enum = props.split("mixie_chat_quick_prompt_mode")[1]
    assert "'LIBRARY'" not in quick_prompt_enum.split("]")[0]


def test_files_saved_in_library_mode_load_as_agent():
    """Value 4 is now out of range, so the persisted-enum sanitizer is what
    catches a .blend saved while the mode was still offered."""
    handlers = _read(CHAT / "core/file_handlers.py")

    assert "'AGENT', 'GENERATE', 'ADDON_PROJECT'" in handlers
    assert "scene.mixie_chat_mode = 'AGENT'" in handlers


def test_library_browse_is_left_dormant_not_deleted():
    """Every entry point stays gated on the mode, so re-listing the enum item
    is the whole of bringing the feature back."""
    library_browse = _read(CHAT / "core/library_browse.py")

    assert "def build_library_grid(" in library_browse
    assert "!= 'LIBRARY'" in library_browse
    assert "== 'LIBRARY'" in library_browse
