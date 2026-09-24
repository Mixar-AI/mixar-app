# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export to Moodboard reads as one send, in plain words.

It was two unrelated actions under jargon headings — "Render Guides",
"Beauty Preview", "T1", "Capture at least two camera beats" — and a
percentage slider whose meaning was a caption away. Now it is one flow: the
keyframe images, which videos, how big, what that comes to, and a single
action named for exactly what it sends (`core/board_export.export_plan`,
mirrored natively by `send_plan`).
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from mixar.modules.director import constants
from mixar.modules.director.core import board_export

ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
POPUP = (
    ROOT / "src/source/blender/editors/space_view3d/view3d_director_popup_render.cc"
).read_text(encoding="utf-8")
OPS = (DIRECTOR / "ui/operators/render_ops.py").read_text(encoding="utf-8")
SHOT_API = (DIRECTOR / "core/shot_api.py").read_text(encoding="utf-8")


def _shot(frames=(1, 25), stills=(True, True), kinds=("CLAY",), images=True):
    beats = [
        SimpleNamespace(frame=frame, image=object() if still else None)
        for frame, still in zip(frames, stills)
    ]
    return SimpleNamespace(beats=beats, render_output_types=set(kinds), export_images=images)


# -------------------------------------------------------------------------
# What a Send sends.


def test_images_count_only_keyframes_that_have_one():
    plan = board_export.export_plan(_shot(frames=(1, 25, 49), stills=(True, False, True)))
    assert plan.images == 2
    assert plan.videos == 1


def test_switching_images_off_sends_videos_alone():
    plan = board_export.export_plan(_shot(kinds=("BEAUTY", "DEPTH"), images=False))
    assert (plan.images, plan.videos) == (0, 2)
    assert board_export.plan_label(plan) == "Send 2 Videos"


def test_videos_need_two_keyframes_and_say_so():
    plan = board_export.export_plan(_shot(frames=(10,), stills=(True,)))
    assert (plan.images, plan.videos) == (1, 0)
    assert plan.video_blocker == "Videos need two or more keyframes"
    assert board_export.plan_label(plan) == "Send 1 Image"


def test_a_running_render_holds_the_videos_back():
    plan = board_export.export_plan(_shot(), rendering=True)
    assert plan.videos == 0
    assert plan.video_blocker == "Videos are already rendering"


def test_the_label_names_both_and_nothing_is_disabled():
    assert board_export.plan_label(board_export.export_plan(_shot())) == "Send 2 Images + 1 Video"
    empty = board_export.export_plan(_shot(kinds=(), images=False))
    assert not empty.anything
    assert board_export.plan_label(empty) == "Nothing to Send"


# -------------------------------------------------------------------------
# The native popup says the same thing.


def test_the_native_label_mirrors_the_python_one():
    label = POPUP[POPUP.index("void send_label(") :]
    label = label[: label.index("\n}\n")]
    assert '"Send %d Image%s + %d Video%s"' in label
    assert '"Send %d Image%s"' in label
    assert '"Send %d Video%s"' in label
    assert '"Nothing to Send"' in label


def test_the_native_plan_mirrors_the_python_one():
    plan = POPUP[POPUP.index("SendPlan send_plan(") :]
    plan = plan[: plan.index("\n}\n")]
    assert "plan.images += int(beat.has_still);" in plan
    assert "if (!running && distinct >= 2) {" in plan
    assert board_export.MIN_VIDEO_KEYFRAMES == 2


def test_the_size_cells_match_the_presets():
    native = re.findall(r'\{(\d+), "(\w+)", "([^"]+)"\}', POPUP)
    assert [(int(p), n, t) for p, n, t in native] == list(constants.VIDEO_SIZE_PRESETS)


def test_one_action_and_no_jargon():
    render = POPUP[POPUP.index("ui::Block *render_popup_create(") :]
    assert render.count("director_overlay_operator_button(") == 1
    assert '"MIXAR_OT_director_export_to_moodboard"' in render
    for jargon in ("Render Guides", "Beauty", "camera beats", "T%d", "On Moodboard"):
        assert jargon not in render, jargon
    assert "Take %d" in render
    assert '"Videos"' in render
    assert "Keyframe Images (%d)" in render


def test_both_three_up_rows_are_one_segmented_group_each():
    """They were Option rows with a leading icon that fit in "Clay" and not
    in "Color" or "Depth", each label left-aligned in its own third — a chip
    with loose words beside it. Cells now run edge to edge, carry a resting
    track and centre their labels."""
    kinds = POPUP[POPUP.index("int draw_kind_toggles(") :]
    kinds = kinds[: kinds.index("\n}\n")]
    assert "ui::UI_mixar_cinema_row_tag(toggle, ui::MixarCinemaRowKind::Segment);" in kinds
    assert "(width * index) / cells" in kinds
    # No icons in a cell: one that fits in one label and not the next is what
    # made the row look broken.
    assert "render_kind_icon" not in POPUP
    assert "uiDefIconTextButR_prop" not in POPUP
    # The size cells are the other group.
    assert POPUP.count("ui::MixarCinemaRowKind::Segment") == 2


def test_the_videos_are_named_for_what_they_look_like():
    names = [item[1] for item in constants.SHOT_RENDER_OUTPUT_ITEMS]
    assert names == ["Color", "Clay", "Depth"]
    labels = (DIRECTOR / "core/render_outputs.py").read_text(encoding="utf-8")
    assert '"BEAUTY": "Color",' in labels


# -------------------------------------------------------------------------
# The operator and the setting.


def test_images_still_go_when_the_videos_cannot_start():
    execute = OPS.split("class MIXAR_OT_director_export_to_moodboard", 1)[1]
    execute = execute.split("\nclass ", 1)[0]
    assert "send_keyframes_to_board(context.scene, shot)" in execute
    assert "start_shot_render(context, shot)" in execute
    assert execute.index("send_keyframes_to_board(") < execute.index("start_shot_render(")
    assert "return {'FINISHED'} if plan.images else {'CANCELLED'}" in execute
    # Chosen but impossible is reported, never silently dropped.
    assert "plan.video_blocker.lower()" in execute


def test_a_new_take_keeps_the_choice():
    assert '"export_images",' in SHOT_API
    assert "shot.export_images = parent.export_images" in SHOT_API
    assert "new_shot.export_images = carried.export_images" in SHOT_API
