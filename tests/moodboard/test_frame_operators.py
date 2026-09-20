# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Frame operators, menus and registration.

``bpy.types.Operator`` subclasses are mocks under the test suite, so the
operator CONTRACTS are pinned at source level (the repo's standing pattern for
operator logic) plus the registration the auto-discovery relies on.
"""

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"

sys.path.insert(0, str(ROOT / "src/scripts"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _classes(path: Path) -> dict[str, ast.ClassDef]:
    tree = ast.parse(_read(path))
    return {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def test_the_frame_collection_and_its_property_group_are_registered():
    source = _read(MOODBOARD / "ui/moodboard_scene_registration.py")
    assert "MixieMoodboardFrame" in source
    assert "'mixie_moodboard_frames'" in source
    # Unregister must drop it too, or a reload leaks the Scene attribute.
    unregister = source.split("def unregister(")[1]
    assert "'mixie_moodboard_frames'" in unregister


def test_the_frame_props_file_exposes_no_classes_tuple():
    """Like every other moodboard PropertyGroup it is registered by the scene
    registration unit; a `classes` tuple in a `ui/` file would have the UI
    auto-discovery register it a second time."""
    source = _read(MOODBOARD / "ui/moodboard_frame_props.py")
    assert not re.search(r"^classes\s*=", source, re.MULTILINE)


def test_the_legacy_group_collection_stays_registered_but_dormant():
    """A .blend saved before frames must still LOAD, and the one-time
    migration has to be able to read it. Nothing writes it."""
    source = _read(MOODBOARD / "ui/moodboard_scene_registration.py")
    assert "'mixie_moodboard_groups'" in source
    assert "MixieMoodboardGroup" in source
    # The operators that used to write it are gone.
    assert not (MOODBOARD / "ui/operators/group_ops.py").exists()


def test_every_framable_kind_carries_a_frame_id():
    """Frames hold references, notes, inference cards and 3D results alike --
    the index-based grouping this replaces could only ever hold images."""
    core = _read(MOODBOARD / "ui/moodboard_properties.py")
    graph = _read(MOODBOARD / "ui/moodboard_graph_properties.py")
    for cls, source in (
        ("MixieMoodboardImage", core),
        ("MixieMoodboardTextBox", core),
        ("MixieMoodboardActionNode", graph),
        ("MixieMoodboardAssetNode", graph),
    ):
        body = source.split(f"class {cls}(PropertyGroup):")[1].split("\nclass ")[0]
        assert "frame_id: StringProperty(" in body, cls

    # And the membership helper's table lists exactly those four collections.
    from mixar.modules.moodboard.core.frames import FRAME_MEMBER_COLLECTIONS

    assert set(FRAME_MEMBER_COLLECTIONS) == {
        "mixie_moodboard_images",
        "mixie_moodboard_textboxes",
        "mixie_moodboard_action_nodes",
        "mixie_moodboard_asset_nodes",
    }


def test_frame_id_declares_a_maxlen():
    """An RNA string without one is unbounded, and the canvas reads these."""
    for path, cls in (
        ("ui/moodboard_properties.py", "MixieMoodboardImage"),
        ("ui/moodboard_frame_props.py", "MixieMoodboardFrame"),
    ):
        source = _read(MOODBOARD / path)
        body = source.split(f"class {cls}(PropertyGroup):")[1].split("\nclass ")[0]
        # Split on the closing paren at FIELD indentation: a description can
        # contain parentheses of its own.
        field = body.split("frame_id: StringProperty(")[1].split("\n    )")[0]
        assert "maxlen=" in field, cls


# --------------------------------------------------------------------------- #
# Operators
# --------------------------------------------------------------------------- #


def test_creating_a_frame_asks_nothing():
    """Ctrl+G makes the frame immediately and drops into the inline rename.
    The operator this replaced opened a props dialog with a name field and a
    colour picker -- a form for one word, in front of a gesture that should be
    instant."""
    source = _read(MOODBOARD / "ui/operators/frame_ops.py")
    create = source.split("class MIXIE_OT_moodboard_create_frame(")[1].split(
        "\nclass "
    )[0]
    assert "invoke_props_dialog" not in create
    assert "mixie.moodboard_rename_frame" in create
    # And no name/colour properties to fill in.
    assert "name: StringProperty(" not in create
    assert "color:" not in create


def test_an_empty_frame_claims_what_already_sits_inside_it():
    """The user framed that area; refusing to adopt what is visibly in it
    would be the wrong reading of the gesture."""
    create = _read(MOODBOARD / "ui/operators/frame_ops.py").split(
        "class MIXIE_OT_moodboard_create_frame("
    )[1].split("\nclass ")[0]
    assert "resolve_membership(scene)" in create


def test_every_frame_operator_skip_saves_its_target():
    """These are REGISTER operators, so an unset property is refilled from the
    previous run -- a remembered `frame_id` would act on the wrong frame."""
    source = _read(MOODBOARD / "ui/operators/frame_ops.py")
    for cls in (
        "MIXIE_OT_moodboard_delete_frame",
        "MIXIE_OT_moodboard_select_frame_contents",
        "MIXIE_OT_moodboard_add_selection_to_frame",
        "MIXIE_OT_moodboard_fit_frame",
        "MIXIE_OT_moodboard_set_frame_color",
        "MIXIE_OT_moodboard_toggle_frame_flag",
    ):
        body = source.split(f"class {cls}(")[1].split("\nclass ")[0]
        field = body.split("frame_id: StringProperty(")[1].split(")")[0]
        assert "'SKIP_SAVE'" in field, cls


def test_delete_with_contents_routes_through_the_boards_own_delete():
    """Which already owns image lifecycle, link cleanup and cancelling the
    in-flight job of a card that can no longer receive it."""
    body = _read(MOODBOARD / "ui/operators/frame_ops.py").split(
        "class MIXIE_OT_moodboard_delete_frame("
    )[1].split("\nclass ")[0]
    assert "bpy.ops.mixie.moodboard_delete()" in body
    assert "select_frame_contents" in body


def test_the_flag_toggle_uses_an_allowlist_not_a_bare_setattr():
    """`flag` arrives from a menu and must never be able to name an arbitrary
    RNA property."""
    body = _read(MOODBOARD / "ui/operators/frame_ops.py").split(
        "class MIXIE_OT_moodboard_toggle_frame_flag("
    )[1].split("\nclass ")[0]
    assert '_FLAGS = ("locked", "collapsed")' in body
    assert "if self.flag not in self._FLAGS" in body


def test_reframe_pushes_no_undo_step_of_its_own():
    """It runs at the END of a drag whose own operator already pushed one; a
    second step would let Ctrl+Z undo the membership without undoing the move
    that caused it."""
    body = _read(MOODBOARD / "ui/operators/frame_ops.py").split(
        "class MIXIE_OT_moodboard_reframe("
    )[1]
    options = body.split("bl_options = ")[1].split("\n")[0]
    assert "UNDO" not in options
    assert "INTERNAL" in options


def test_reframe_takes_no_stickiness_knob():
    """Membership is always sticky and always grows the frame. The `sticky`
    flag existed for ONE caller -- a frame resize, where shrinking the rect
    past a member released it -- and that gesture is gone, so a flag nobody
    passes is a flag that rots."""
    source = _read(MOODBOARD / "ui/operators/frame_ops.py")
    body = source.split("class MIXIE_OT_moodboard_reframe(")[1]
    assert "sticky" not in body.split("def execute")[0]
    assert "resolve_membership(context.scene)" in body


def test_all_frame_operators_are_in_the_classes_tuple():
    source = _read(MOODBOARD / "ui/operators/frame_ops.py")
    declared = set(_classes(MOODBOARD / "ui/operators/frame_ops.py"))
    registered = set(
        re.findall(r"\n    (MIXIE_OT_\w+),", source.split("classes = (")[1])
    )
    assert declared == registered, declared ^ registered


# --------------------------------------------------------------------------- #
# Menus and shortcuts
# --------------------------------------------------------------------------- #


def test_the_keymap_binds_the_frame_operators_not_the_group_ones():
    keymap = _read(SPACE_MIXIE / "space_mixie.cc")
    assert '"mixie.moodboard_create_frame"' in keymap
    assert '"mixie.moodboard_ungroup"' in keymap
    assert '"mixie.create_group"' not in keymap
    assert '"mixie.ungroup"' not in keymap


def test_the_frame_shortcuts_have_addon_keyconfig_copies():
    """The keyconfig-reload rule: a C-registered binding alone is wiped by a
    GUI keyconfig preset reload, so the addon keyconfig must carry a copy."""
    keymap = _read(MOODBOARD / "ui" / "keymap.py")
    assert "'mixie.moodboard_create_frame'" in keymap
    assert "'mixie.moodboard_ungroup'" in keymap


def test_the_more_menu_offers_every_frame_action():
    menu = _read(MOODBOARD / "ui/moodboard_frame_menus.py")
    for operator in (
        "mixie.moodboard_select_frame_contents",
        "mixie.moodboard_add_selection_to_frame",
        "mixie.moodboard_fit_frame",
        "mixie.moodboard_toggle_frame_flag",
        "mixie.moodboard_rename_frame",
        "mixie.moodboard_ungroup",
        "mixie.moodboard_delete_frame",
    ):
        assert operator in menu, operator
    # The colour swatches come from the palette, never a hardcoded list.
    assert "for index, (name, _rgb) in enumerate(FRAME_PALETTE)" in menu


def test_the_context_menu_shows_the_frame_menu_rather_than_duplicating_it():
    """One definition of a frame's actions, shared with the floating More
    button, so the two can never drift."""
    menus = _read(MOODBOARD / "ui/moodboard_menus.py")
    assert 'layout.menu("MIXIE_MT_moodboard_frame"' in menus
    assert "mixie.create_group" not in menus
    assert "group_index" not in menus


def test_shortcut_labels_spell_out_the_keys_they_cannot_resolve():
    """A keymap item carrying properties is not matched when Blender looks for
    a menu entry's shortcut, so the label has to say it (the same reason
    Frame Selected spells out "Numpad .")."""
    menu = _read(MOODBOARD / "ui/moodboard_frame_menus.py")
    assert "Rename (F2)" in menu
    assert "Ungroup (Alt G)" in menu


def test_f2_reaches_a_selected_frame_when_no_node_is_selected():
    """A frame is selected by its own border, so exactly one selected frame is
    an unambiguous F2 target; the rename operator resolves it itself."""
    source = _read(MOODBOARD / "ui/operators/node_graph_ops.py")
    body = source.split("if not self.node_id:")[1].split("\n\n")[0]
    assert "moodboard_rename_frame" in body
    assert "frame.selected" in body
