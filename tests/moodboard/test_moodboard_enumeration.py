# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Standalone coverage for the board enumeration the agent reads.

``list_moodboard_images`` is how the agent answers "what is on the moodboard"
and, above all, "what did that job just produce". Three properties make that
answer usable, and all three were wrong:

* it must be ordered NEWEST FIRST and truncate from the newest end — the
  collection is append-ordered, so cutting the first ``limit`` entries returned
  the oldest images and hid every new one on a busy board;
* it must report the turnaround MAIN image, the only member of a multi-view set
  that a job may be submitted with (``turnaround_main_group``); listing the
  companions alone describes a set nobody can use;
* it must distinguish a movie from a still, because image generation and
  image-to-3D are still-only.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

# Imported through the package (root conftest stubs bpy) rather than loaded from
# a path: both modules use relative imports, and `moodboard_utils` re-exports the
# enumeration API, which is the import path the agent's tool script uses.
from mixar.modules.moodboard.core import moodboard_enumeration, moodboard_utils


@pytest.fixture
def enumeration():
    return moodboard_enumeration


def _image(name, *, movie=False):
    return SimpleNamespace(
        name=name, size=[512, 512], channels=4, has_data=True,
        packed_file=None, is_dirty=False, file_format="PNG", filepath="",
        source="MOVIE" if movie else "FILE",
        colorspace_settings=SimpleNamespace(name="sRGB"),
    )


def _item(name, *, movie=False, prompt="", created="", selected=False,
          view_type="left", group="", main_group="", node=""):
    return SimpleNamespace(
        image=_image(name, movie=movie),
        generation_prompt=prompt, mixar_created_at_iso=created,
        mixar_job_handle="", selected=selected,
        position_x=0.0, position_y=0.0, scale=1.0, rotation=0.0,
        flip_horizontal=False, flip_vertical=False, z_order=0, group_index=-1,
        segments=[], view_type=view_type, turnaround_group=group,
        turnaround_main_group=main_group, embedded_node_id=node,
    )


def _ctx(items):
    return SimpleNamespace(scene=SimpleNamespace(mixie_moodboard_images=items))


def _names(result):
    return [image["image_name"] for image in result["images"]]


# ---------------------------------------------------------------------------
# Ordering and truncation
# ---------------------------------------------------------------------------

def test_lists_newest_first(enumeration):
    items = [_item(f"img_{i}.png") for i in range(4)]

    assert _names(enumeration.list_moodboard_images(_ctx(items))) == [
        "img_3.png", "img_2.png", "img_1.png", "img_0.png",
    ]


def test_limit_keeps_the_newest_not_the_oldest(enumeration):
    """The regression: a job's fresh output is appended LAST, so a head-cut
    listing never showed it once the board outgrew ``limit``."""
    items = [_item(f"img_{i}.png") for i in range(10)]

    result = enumeration.list_moodboard_images(_ctx(items), limit=3)

    assert _names(result) == ["img_9.png", "img_8.png", "img_7.png"]
    assert result["count"] == 3
    assert result["total"] == 10
    assert result["truncated"] is True


def test_untruncated_listing_says_so(enumeration):
    result = enumeration.list_moodboard_images(_ctx([_item("a.png")]), limit=50)

    assert (result["total"], result["truncated"]) == (1, False)


def test_non_positive_limit_returns_everything(enumeration):
    items = [_item(f"img_{i}.png") for i in range(5)]

    assert enumeration.list_moodboard_images(_ctx(items), limit=0)["count"] == 5


# ---------------------------------------------------------------------------
# since_image_name
# ---------------------------------------------------------------------------

def test_since_is_anchored_on_board_position_not_timestamp(enumeration):
    """Most board entries predate the timestamp property or were added by a
    path that never stamped one; a timestamp-ordered filter drops those."""
    items = [_item("old.png"), _item("anchor.png"), _item("new.png")]

    result = enumeration.list_moodboard_images(_ctx(items), since_image_name="anchor.png")

    assert _names(result) == ["new.png"]
    assert result["since_resolved"] is True


def test_unknown_since_image_is_reported_not_silently_ignored(enumeration):
    items = [_item("a.png"), _item("b.png")]

    result = enumeration.list_moodboard_images(_ctx(items), since_image_name="gone.png")

    assert result["count"] == 2
    assert result["since_resolved"] is False


def test_since_is_resolved_by_default_when_unused(enumeration):
    assert enumeration.list_moodboard_images(_ctx([_item("a.png")]))["since_resolved"]


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def test_name_glob_and_prompt_filters_narrow_the_total(enumeration):
    items = [_item("plain.png"), _item("agent_imagegen_chair.png", prompt="A Wooden Chair")]

    by_glob = enumeration.list_moodboard_images(_ctx(items), name_glob="agent_imagegen_*")
    by_prompt = enumeration.list_moodboard_images(_ctx(items), generation_prompt_contains="wooden")

    assert _names(by_glob) == _names(by_prompt) == ["agent_imagegen_chair.png"]
    assert by_glob["total"] == 1


# ---------------------------------------------------------------------------
# Per-item metadata the agent cannot recover any other way
# ---------------------------------------------------------------------------

def test_turnaround_main_image_is_reported(enumeration):
    """``turnaround_group`` means "companion of", so the frontal image never
    carries it — only ``turnaround_main_group``, and only that image may be
    submitted with the set."""
    items = [_item("sheet.png", main_group="grp1"), _item("left.png", group="grp1")]

    by_name = {i["image_name"]: i for i in
               enumeration.list_moodboard_images(_ctx(items))["images"]}

    assert by_name["sheet.png"]["turnaround_main_group"] == "grp1"
    assert by_name["sheet.png"]["turnaround_group"] == ""
    assert by_name["left.png"]["turnaround_group"] == "grp1"
    assert by_name["left.png"]["turnaround_main_group"] == ""


def test_movies_are_distinguishable_from_stills(enumeration):
    items = [_item("still.png"), _item("clip.mp4", movie=True)]

    by_name = {i["image_name"]: i for i in
               enumeration.list_moodboard_images(_ctx(items))["images"]}

    assert by_name["still.png"]["media_type"] == "IMAGE"
    assert by_name["clip.mp4"]["media_type"] == "VIDEO"


def test_node_owned_media_and_selection_are_reported(enumeration):
    items = [_item("free.png", selected=True), _item("result.png", node="node-7")]

    by_name = {i["image_name"]: i for i in
               enumeration.list_moodboard_images(_ctx(items))["images"]}

    assert by_name["free.png"]["selected"] is True
    assert by_name["free.png"]["embedded_node_id"] == ""
    assert by_name["result.png"]["selected"] is False
    assert by_name["result.png"]["embedded_node_id"] == "node-7"


def test_selection_listing_shares_the_same_item_shape(enumeration):
    items = [_item("a.png", selected=True), _item("b.png")]

    result = enumeration.get_selected_moodboard_images(_ctx(items))

    assert result["has_selection"] is True
    assert _names(result) == ["a.png"]
    assert result["images"][0]["media_type"] == "IMAGE"


def test_missing_collection_returns_an_empty_listing(enumeration):
    ctx = SimpleNamespace(scene=SimpleNamespace())

    result = enumeration.list_moodboard_images(ctx)

    assert (result["count"], result["images"], result["total"]) == (0, [], 0)


# ---------------------------------------------------------------------------
# Provenance stamping
# ---------------------------------------------------------------------------

def test_stamp_fills_an_empty_created_at():
    item = _item("a.png")

    moodboard_utils.stamp_moodboard_item_added(item)

    stamped = datetime.fromisoformat(item.mixar_created_at_iso)
    assert stamped.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - stamped).total_seconds()) < 60


def test_stamp_never_overwrites_a_deliberate_timestamp():
    item = _item("a.png", created="2026-01-01T00:00:00+00:00")

    moodboard_utils.stamp_moodboard_item_added(item)

    assert item.mixar_created_at_iso == "2026-01-01T00:00:00+00:00"
