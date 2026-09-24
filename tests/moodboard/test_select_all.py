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
    # Frames, never `mixie_moodboard_groups`: the load-time migration empties
    # the legacy collection for good, so walking it selects nothing and
    # Select All followed by Delete spared every frame.
    assert "mixie_moodboard_frames" in body
    assert "mixie_moodboard_groups" not in body
    assert 'getattr(img, "embedded_node_id", "")' in body
    assert "mixie_moodboard_active_node_id" in body


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
