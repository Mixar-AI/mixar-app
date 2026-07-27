# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for turnaround (model-sheet) view detection payload assembly.

These cover the frozen backend contract for POST /job-queue/jobs:
the front panel goes in ``image_s3_key``, every other panel goes in
``multi_view_images``, and ``front`` must NEVER appear in
``multi_view_images`` (the vendor enum has no such member).
"""

import pytest

from mixar.modules.common.utils.image_compression_config import (
    get_compression_settings,
)
from mixar.modules.moodboard.core.turnaround_views import (
    _sanitise_panels,
    build_multi_view_payload,
    find_group_for_image,
    group_items,
)


# ---------------------------------------------------------------------------
# Upload resolution
# ---------------------------------------------------------------------------

def test_turnaround_upload_profile_is_higher_res_than_single_image():
    # The sheet gets SPLIT, so upload resolution divides down into the actual
    # per-view 3D input. Reusing the image_to_3d profile (2048) silently caps
    # a four-panel sheet at ~500 px crops.
    turnaround = get_compression_settings("turnaround_detect")
    single = get_compression_settings("image_to_3d")

    assert turnaround.max_dimension == 4096
    assert turnaround.max_dimension > single.max_dimension
    assert single.max_dimension == 2048, "single-image path must stay at 2048"


def test_turnaround_upload_profile_respects_backend_ceiling():
    # Backend core/validators.py rejects anything over 4096x4096 outright.
    assert get_compression_settings("turnaround_detect").max_dimension <= 4096


class FakeImage:
    def __init__(self, name):
        self.name = name


class FakeItem:
    def __init__(self, name, view_type, s3_key, group=""):
        self.image = FakeImage(name)
        self.view_type = view_type
        self.s3_key = s3_key
        self.turnaround_group = group


class FakeScene:
    def __init__(self, items):
        self.mixie_moodboard_images = items


def _scene(*specs, group="g1"):
    return FakeScene([FakeItem(n, v, k, group) for n, v, k in specs])


# ---------------------------------------------------------------------------
# build_multi_view_payload
# ---------------------------------------------------------------------------

def test_front_becomes_image_s3_key_and_is_never_a_multi_view():
    scene = _scene(
        ("orc_front", "front", "k/front.png"),
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
    )
    payload, warnings = build_multi_view_payload(scene, "g1")

    assert payload["image_s3_key"] == "k/front.png"
    assert payload["multi_view_images"] == [
        {"s3_key": "k/left.png", "view_type": "left"},
        {"s3_key": "k/back.png", "view_type": "back"},
    ]
    assert not warnings
    assert all(
        mv["view_type"] != "front" for mv in payload["multi_view_images"]
    )


def test_front_only_group_sends_no_multi_view_key():
    scene = _scene(("orc_front", "front", "k/front.png"))
    payload, warnings = build_multi_view_payload(scene, "g1")

    assert payload == {"image_s3_key": "k/front.png"}
    assert "multi_view_images" not in payload
    assert not warnings


def test_missing_front_is_rejected():
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
    )
    with pytest.raises(ValueError, match="Front"):
        build_multi_view_payload(scene, "g1")


def test_multiple_fronts_are_refused_not_silently_dropped():
    # A user relabelling a crop can produce two fronts. Refuse: the next step
    # is a multi-minute, ~50-credit job, and quietly dropping a panel would
    # build the model from less data than the user believes they supplied.
    scene = _scene(
        ("a_front", "front", "k/a.png"),
        ("b_front", "front", "k/b.png"),
        ("c_left", "left", "k/c.png"),
    )
    with pytest.raises(ValueError, match="only one can be the main image"):
        build_multi_view_payload(scene, "g1")


def test_multiple_fronts_message_names_the_count():
    scene = _scene(
        ("a_front", "front", "k/a.png"),
        ("b_front", "front", "k/b.png"),
    )
    with pytest.raises(ValueError, match="Two views are labelled Front"):
        build_multi_view_payload(scene, "g1")


def test_duplicate_view_types_are_deduped_with_a_warning():
    scene = _scene(
        ("orc_front", "front", "k/front.png"),
        ("orc_left", "left", "k/left1.png"),
        ("orc_left2", "left", "k/left2.png"),
    )
    payload, warnings = build_multi_view_payload(scene, "g1")

    assert payload["multi_view_images"] == [
        {"s3_key": "k/left1.png", "view_type": "left"}
    ]
    assert any("left" in w for w in warnings)


def test_unlabelled_panel_is_skipped_with_a_warning():
    scene = _scene(
        ("orc_front", "front", "k/front.png"),
        ("orc_mystery", "none", "k/x.png"),
    )
    payload, warnings = build_multi_view_payload(scene, "g1")

    assert "multi_view_images" not in payload
    assert any("no view label" in w for w in warnings)


def test_missing_s3_key_is_rejected():
    scene = _scene(
        ("orc_front", "front", "k/front.png"),
        ("orc_left", "left", ""),
    )
    with pytest.raises(ValueError, match="backend key"):
        build_multi_view_payload(scene, "g1")


def test_empty_group_is_rejected():
    scene = _scene(("orc_front", "front", "k/front.png"), group="other")
    with pytest.raises(ValueError, match="no images"):
        build_multi_view_payload(scene, "g1")


# ---------------------------------------------------------------------------
# Pro job payload wiring (mixie.hunyuan_generate multi_view=True)
# ---------------------------------------------------------------------------

# Imported inside the tests: generation_enqueue pulls in the HTTP stack, which
# is only present inside Blender.

_SHARED = {"generate_type": "Normal", "enable_pbr": False, "model_version": "3.1"}
_TURNAROUND = {
    "image_s3_key": "k/front.png",
    "multi_view_images": [{"s3_key": "k/left.png", "view_type": "left"}],
}


def test_pro_payload_forwards_s3_keys_without_uploading_pixels():
    from mixar.modules.moodboard.core.generation_enqueue import (
        _build_pro_payload,
    )
    payload, _ = _build_pro_payload(b"", _SHARED, None, _TURNAROUND)

    assert payload["image_s3_key"] == "k/front.png"
    assert payload["multi_view_images"] == _TURNAROUND["multi_view_images"]
    assert "image_bytes_b64" not in payload


def test_pro_payload_turnaround_overrides_inline_bytes():
    # A turnaround submit must never also carry base64 pixels.
    from mixar.modules.moodboard.core.generation_enqueue import (
        _build_pro_payload,
    )
    payload, _ = _build_pro_payload(
        b"rawbytes", _SHARED, [(b"mv", "mv.png", "left")], _TURNAROUND)

    assert "image_bytes_b64" not in payload
    assert payload["multi_view_images"] == _TURNAROUND["multi_view_images"]


def test_pro_payload_without_turnaround_is_unchanged():
    # Regression guard: every existing caller passes turnaround=None and must
    # keep producing the legacy inline-bytes shape.
    from mixar.modules.moodboard.core.generation_enqueue import (
        _build_pro_payload,
    )
    payload, model_key = _build_pro_payload(
        b"rawbytes", _SHARED, [(b"mv", "mv.png", "left")])

    assert "image_bytes_b64" in payload
    assert "image_s3_key" not in payload
    assert "image_bytes_b64" in payload["multi_view_images"][0]
    assert payload["multi_view_images"][0]["view_type"] == "left"
    assert model_key == "hunyuan_pro_v3.1"


# ---------------------------------------------------------------------------
# Group lookup
# ---------------------------------------------------------------------------

def test_find_group_for_image_only_matches_grouped_items():
    scene = _scene(("orc_front", "front", "k/front.png"))
    scene.mixie_moodboard_images.append(
        FakeItem("loose", "none", "", "")
    )
    assert find_group_for_image(scene, scene.mixie_moodboard_images[0].image) == "g1"
    assert find_group_for_image(scene, scene.mixie_moodboard_images[1].image) == ""
    assert find_group_for_image(scene, None) == ""


def test_group_items_puts_front_first():
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_front", "front", "k/front.png"),
    )
    assert [i.view_type for i in group_items(scene, "g1")] == ["front", "left"]


# ---------------------------------------------------------------------------
# Response sanitising
# ---------------------------------------------------------------------------

def test_sanitise_panels_keeps_valid_panels_front_first():
    panels = _sanitise_panels([
        {"view_type": "left", "s3_key": "k/l", "preview_url": "http://l"},
        {"view_type": "front", "s3_key": "k/f", "preview_url": "http://f"},
    ])
    assert [p["view_type"] for p in panels] == ["front", "left"]


def test_sanitise_panels_drops_unknown_view_types():
    panels = _sanitise_panels([
        {"view_type": "front", "s3_key": "k/f", "preview_url": "http://f"},
        {"view_type": "diagonal", "s3_key": "k/d", "preview_url": "http://d"},
    ])
    assert [p["view_type"] for p in panels] == ["front"]


def test_sanitise_panels_drops_entries_missing_key_or_url():
    panels = _sanitise_panels([
        {"view_type": "front", "s3_key": "k/f", "preview_url": "http://f"},
        {"view_type": "left", "preview_url": "http://l"},
        {"view_type": "back", "s3_key": "k/b"},
    ])
    assert [p["view_type"] for p in panels] == ["front"]


def test_sanitise_panels_without_front_yields_nothing():
    # Never build a group we cannot submit — no front means no image_s3_key.
    assert _sanitise_panels([
        {"view_type": "left", "s3_key": "k/l", "preview_url": "http://l"},
    ]) == []


def test_sanitise_panels_keeps_only_the_first_front():
    panels = _sanitise_panels([
        {"view_type": "front", "s3_key": "k/f1", "preview_url": "http://f1"},
        {"view_type": "front", "s3_key": "k/f2", "preview_url": "http://f2"},
        {"view_type": "right", "s3_key": "k/r", "preview_url": "http://r"},
    ])
    assert [p["view_type"] for p in panels] == ["front", "right"]
    assert panels[0]["s3_key"] == "k/f1"
