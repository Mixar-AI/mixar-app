# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every consumer of canvas selection reads FRAMES, not the legacy groups.

Canvas frames replaced the index-based ``mixie_moodboard_groups`` +
``group_index`` pair, and ``frames.migrate_legacy_groups`` empties that
collection permanently on load. Anything still walking it therefore walks an
always-empty list and silently does nothing -- which is how Select All came
to spare every frame, Deselect All left one selected under the user's next
Delete, and Shift+D dragged the originals along with the copies.

The same "does the frame get the event at all" question covers the
keyconfig side: every C-registered frame binding has to exist in the ADDON
keyconfig too, or a GUI keyconfig preset reload leaves frames unclickable
while images and cards keep working.

The operators are executed out of their own source (``bpy`` is a MagicMock in
this suite, so a registered Operator subclass asserts nothing).
"""

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
TRANSFORM_OPS = ROOT / "src/scripts/mixar/modules/moodboard/ui/operators/transform_ops.py"
HEADER = ROOT / "src/scripts/mixar/modules/space_mixie/ui/header.py"
CANVAS = ROOT / "src/scripts/mixar/modules/moodboard/core/canvas_context.py"
KEYMAP = ROOT / "src/scripts/mixar/modules/moodboard/ui/keymap.py"
SPACE_MIXIE_CC = ROOT / "src/source/blender/editors/space_mixie/space_mixie.cc"

COLLECTIONS = ("images", "textboxes", "frames", "groups", "action_nodes",
               "asset_nodes", "links", "annotations")


def _load_transform_ops():
    """The module's classes and helpers, with its bpy-side imports stubbed."""
    tree = ast.parse(TRANSFORM_OPS.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body
                 if not isinstance(node, (ast.Import, ast.ImportFrom))]
    scope = {
        "Operator": object,
        "FloatProperty": lambda **kwargs: None,
        "bpy": SimpleNamespace(ops=SimpleNamespace(
            mixie=SimpleNamespace(moodboard_grab=Mock()))),
        "redraw_moodboard_canvases": Mock(),
        "release_all_moodboard_images": Mock(),
        "stamp_moodboard_item_added": Mock(),
    }
    exec(compile(tree, str(TRANSFORM_OPS), "exec"), scope)
    return scope


@pytest.fixture(scope="module")
def ops():
    return _load_transform_ops()


def _frame(frame_id="frame-1", selected=False):
    return SimpleNamespace(frame_id=frame_id, selected=selected)


def _media(name="a", selected=False, frame_id="", **extra):
    item = SimpleNamespace(
        image=SimpleNamespace(name=name),
        selected=selected,
        frame_id=frame_id,
        embedded_node_id="",
        position_x=0.0,
        position_y=0.0,
    )
    for key, value in extra.items():
        setattr(item, key, value)
    return item


def _scene(**overrides):
    scene = SimpleNamespace(
        **{f"mixie_moodboard_{name}": [] for name in COLLECTIONS},
        mixie_moodboard_active_node_id="",
    )
    for key, value in overrides.items():
        setattr(scene, f"mixie_moodboard_{key}", value)
    return scene


def _run(cls, scene, method="execute"):
    op = cls()
    op.report = Mock()
    # `tag_mixie_redraw` tries context.area, then walks context.screen.areas.
    context = SimpleNamespace(scene=scene, area=None,
                              screen=SimpleNamespace(areas=[]))
    args = (context,) if method == "execute" else (context, SimpleNamespace())
    return getattr(op, method)(*args), op


# --------------------------------------------------------------------------- #
# Select All / Deselect All
# --------------------------------------------------------------------------- #

def test_select_all_selects_frames(ops):
    scene = _scene(frames=[_frame()])
    _run(ops["MIXIE_OT_moodboard_select_all"], scene)
    assert scene.mixie_moodboard_frames[0].selected is True


def test_deselect_all_clears_frames(ops):
    """Delete reads ``frame.selected`` directly, so a frame the user was told
    was deselected is a frame their next X silently removes."""
    scene = _scene(frames=[_frame(selected=True)])
    _run(ops["MIXIE_OT_moodboard_deselect_all"], scene)
    assert scene.mixie_moodboard_frames[0].selected is False


# --------------------------------------------------------------------------- #
# Clear Moodboard
# --------------------------------------------------------------------------- #

def test_clear_moodboard_removes_frames(ops):
    scene = _scene(frames=[_frame()], images=[_media()])
    result, _ = _run(ops["MIXIE_OT_clear_moodboard"], scene)
    assert result == {"FINISHED"}
    assert scene.mixie_moodboard_frames == []


def test_a_frames_only_board_is_not_already_empty(ops):
    """The emptiness guard counted the legacy collection, which is always 0
    after migration -- so frames drawn on an otherwise bare canvas could
    never be cleared."""
    scene = _scene(frames=[_frame(), _frame("frame-2")])
    result, op = _run(ops["MIXIE_OT_clear_moodboard"], scene)
    assert result == {"FINISHED"}
    assert scene.mixie_moodboard_frames == []
    assert "2 frame(s)" in op.report.call_args[0][1]


# --------------------------------------------------------------------------- #
# Duplicate
# --------------------------------------------------------------------------- #

def test_duplicate_deselects_the_source_frame(ops):
    """`get_all_items_to_transform` expands a selected frame back into every
    ORIGINAL member, so a frame left selected makes the grab that follows
    drag the sources along with the copies."""
    member = _media(frame_id="frame-1", scale=1.0, rotation=0.0,
                    flip_horizontal=False, flip_vertical=False, z_order=0,
                    generation_prompt="", component_role="",
                    component_source_item_id="", component_source_segment_id="",
                    component_name="", show_annotations=False, annotations=[])
    frame = _frame(selected=True)
    scene = _scene(frames=[frame], images=_Collection([member]))

    _run(ops["MIXIE_OT_moodboard_duplicate"], scene, method="invoke")

    assert frame.selected is False
    assert member.selected is False
    assert scene.mixie_moodboard_images[-1].selected is True


class _Collection(list):
    """A bpy collection property: the duplicate path calls ``add()``."""

    def add(self):
        item = _media(scale=1.0, rotation=0.0, flip_horizontal=False,
                      flip_vertical=False, z_order=0, generation_prompt="",
                      component_role="", component_source_item_id="",
                      component_source_segment_id="", component_name="",
                      show_annotations=False, annotations=_Collection())
        self.append(item)
        return item


# --------------------------------------------------------------------------- #
# Everything else that asks "is there anything on this board?"
# --------------------------------------------------------------------------- #

def test_header_content_check_counts_frames():
    source = CANVAS.read_text(encoding="utf-8")
    body = source.split("MOODBOARD_CONTENT_COLLECTIONS")[1].split("def has_moodboard_content")[0]
    assert '"mixie_moodboard_frames"' in body
    header = HEADER.read_text(encoding="utf-8")
    assert "has_moodboard_content as _has_moodboard_content" in header


def test_no_consumer_still_resolves_selection_through_group_index():
    """One grep is the whole fix: `group_index` survives only on the property
    itself and inside the one-way migration that clears it."""
    allowed = {
        # The one-way migration itself, and nothing else.
        "src/scripts/mixar/modules/moodboard/core/frames.py",
        # The one-way conversion moved here (500-line rule); reading
        # `group_index` is its whole job.
        "src/scripts/mixar/modules/moodboard/core/frame_migration.py",
    }
    # Reading membership means WALKING the legacy collection or comparing a
    # `group_index`. Writing `group_index = -1` on a fresh copy, or clearing
    # the legacy collection on a board that has not ticked the migration
    # yet, are both fine and deliberately not matched.
    reads = re.compile(
        r"for\s+\w+\s+in\s+[\w.]*mixie_moodboard_groups"
        r"|group_index\s*(?:[<>=!]=|[<>])"
        r"|getattr\([^,]+,\s*[\'\"]group_index"
    )
    offenders = []
    for path in (ROOT / "src/scripts/mixar/modules").rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel in allowed or "/testing/" in rel:
            continue
        if reads.search(path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert offenders == [], f"still resolving frames through legacy groups: {offenders}"


# --------------------------------------------------------------------------- #
# The keyconfig-reload rule
# --------------------------------------------------------------------------- #

def test_every_c_registered_frame_binding_is_mirrored_in_the_addon_keyconfig():
    """CLAUDE.md's keyconfig-reload rule. A GUI keyconfig preset reload wipes
    C-registered items, and `WM_keymap_active` then prefers the user Mixie
    map, which never received them. With the frame operators bound only in C,
    that reload left images and cards clickable and frames completely
    unselectable, undraggable and unrenamable."""
    space = SPACE_MIXIE_CC.read_text(encoding="utf-8")
    keymap = KEYMAP.read_text(encoding="utf-8")

    for operator in ("MIXIE_OT_moodboard_frame_select", "MIXIE_OT_moodboard_frame"):
        assert f'"{operator}", &' in space, (
            f"{operator} is not C-registered any more; drop it from this test"
        )
        idname = "mixie." + operator[len("MIXIE_OT_"):]
        assert f"'{idname}'" in keymap, (
            f"{idname} is bound in C but not in the addon keyconfig"
        )

    # Home / Numpad-Period, with the selection variant carrying its property.
    assert "type='HOME'" in keymap
    assert "type='NUMPAD_PERIOD'" in keymap
    assert "selected_only = True" in keymap
