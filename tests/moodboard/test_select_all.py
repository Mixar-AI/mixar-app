# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Select-all must bind A and select every selectable canvas item including nodes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_select_all_operator_covers_graph_nodes_and_skips_embedded_media():
    """The shortcut used to finish without selecting inference cards because
    the operator only walked images/textboxes. Deselect already cleared nodes;
    select-all must mirror that set (and leave node-owned previews alone)."""
    ops = _read(MOODBOARD / "ui/operators/transform_ops.py")
    body = ops.split("class MIXIE_OT_moodboard_select_all")[1].split(
        "class MIXIE_OT_moodboard_deselect_all"
    )[0]

    assert "mixie_moodboard_action_nodes" in body
    assert "mixie_moodboard_asset_nodes" in body
    assert "mixie_moodboard_groups" in body
    assert 'getattr(img, "embedded_node_id", "")' in body
    assert "mixie_moodboard_active_node_id" in body


def test_drawer_tab_keymap_is_bound_in_c_and_addon():
    """Tab toggles the Zen drawer. C defaultconf + addon keyconfig must
    both carry it so a GUI keyconfig preset reload cannot wipe the shortcut.
    The binding lives on Moodboard Drawer Grip (TOOL_PROPS), never Mixie."""
    ops = _read(
        ROOT / "src/source/blender/editors/space_view3d/view3d_moodboard_drawer_ops.cc"
    )
    keymap = _read(MOODBOARD / "ui/keymap.py")

    assert 'WM_keymap_add_item(keymap, "VIEW3D_OT_moodboard_drawer_toggle"' in ops
    assert "EVT_TABKEY" in ops
    keymap_fn = ops.split("void view3d_moodboard_drawer_keymap")[1]
    assert "RGN_TYPE_TOOL_PROPS" in keymap_fn
    assert "SPACE_VIEW3D" in keymap_fn

    assert "'view3d.moodboard_drawer_toggle'" in keymap
    tab_at = keymap.index("'view3d.moodboard_drawer_toggle'")
    item = keymap[tab_at : tab_at + 80]
    assert "type='TAB'" in item
    assert "ctrl=" not in item and "shift=" not in item and "oskey=" not in item
    drawer_map = keymap.index("Moodboard Drawer Grip")
    assert drawer_map < tab_at
    assert "'mixie.moodboard_pie_menu_call'" in keymap
    pie_tab = keymap.index("type='TAB'")
    assert "ctrl=True" in keymap[pie_tab : pie_tab + 80]


def test_select_all_keymap_is_bound_in_c_and_addon():
    """No Mixie A binding meant the shortcut did nothing even when the menu
    operator existed. C defaultconf + addon keyconfig must both carry A /
    Alt+A so a GUI keyconfig preset reload cannot wipe select-all."""
    space = _read(SPACE_MIXIE / "space_mixie.cc")
    keymap = _read(MOODBOARD / "ui/keymap.py")

    assert 'WM_keymap_add_item(keymap, "mixie.moodboard_select_all"' in space
    assert "EVT_AKEY" in space
    assert 'WM_keymap_add_item(keymap, "mixie.moodboard_deselect_all"' in space
    assert "KM_ALT" in space.split("moodboard_deselect_all")[0][-200:]

    assert "'mixie.moodboard_select_all'" in keymap
    assert "type='A'" in keymap
    select_at = keymap.index("'mixie.moodboard_select_all'")
    deselect_at = keymap.index("'mixie.moodboard_deselect_all'")
    assert select_at < deselect_at
    assert "alt=True" in keymap[deselect_at : deselect_at + 120]
