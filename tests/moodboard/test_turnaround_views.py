# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for turnaround (model-sheet) multi-view payload assembly.

These cover the frozen backend contract for POST /job-queue/jobs:
the ``main`` view goes in ``image_s3_key`` / ``image_bytes_b64``, every other
view goes in ``multi_view_images``, and neither ``main`` nor ``front`` may
ever appear in ``multi_view_images`` (the vendor enum has no such members).

Detected crops carry an S3 key; views the user added by hand do not and carry
inline base64 pixels instead. The two shapes mix within one payload.
"""

import pytest

from mixar.modules.common.utils.image_compression_config import (
    get_compression_settings,
)
from mixar.modules.moodboard.core import turnaround_views
from mixar.modules.moodboard.core.turnaround_detect import _sanitise_panels
from mixar.modules.moodboard.core.turnaround_views import (
    build_multi_view_payload,
    detach_image,
    find_group_for_image,
    group_items,
    main_item,
    set_main_image,
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
        self.position_x = 0.0
        self.position_y = 0.0


class FakeScene:
    def __init__(self, items):
        self.mixie_moodboard_images = items


def _scene(*specs, group="g1"):
    return FakeScene([FakeItem(n, v, k, group) for n, v, k in specs])


@pytest.fixture(autouse=True)
def fake_encoder(monkeypatch):
    """Stand in for the bpy-backed JPEG encoder used by keyless views."""
    monkeypatch.setattr(
        turnaround_views, "_encode_image", lambda image: f"b64({image.name})")


# ---------------------------------------------------------------------------
# build_multi_view_payload — main image
# ---------------------------------------------------------------------------

def test_main_becomes_image_s3_key_and_is_never_a_multi_view():
    scene = _scene(
        ("orc_main", "main", "k/main.png"),
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
    )
    payload, warnings = build_multi_view_payload(scene, "g1")

    assert payload["image_s3_key"] == "k/main.png"
    assert payload["multi_view_images"] == [
        {"s3_key": "k/left.png", "view_type": "left"},
        {"s3_key": "k/back.png", "view_type": "back"},
    ]
    assert not warnings
    assert all(
        mv["view_type"] not in ("main", "front")
        for mv in payload["multi_view_images"]
    )


def test_main_only_group_sends_no_multi_view_key():
    scene = _scene(("orc_main", "main", "k/main.png"))
    payload, warnings = build_multi_view_payload(scene, "g1")

    assert payload == {"image_s3_key": "k/main.png"}
    assert "multi_view_images" not in payload
    assert not warnings


def test_missing_main_is_rejected():
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
    )
    with pytest.raises(ValueError, match="Main Image"):
        build_multi_view_payload(scene, "g1")


def test_a_lone_front_does_not_count_as_a_main():
    # 'front' is a separate front orthographic, not the hero. It has no slot
    # in the vendor payload at all, so a group holding only fronts cannot be
    # submitted until the user relabels one Main Image.
    scene = _scene(("orc_front", "front", "k/front.png"))
    with pytest.raises(ValueError, match="Main Image"):
        build_multi_view_payload(scene, "g1")


def test_multiple_mains_are_refused_not_silently_dropped():
    # A user relabelling a view can produce two mains. Refuse: the next step
    # is a multi-minute, ~50-credit job, and quietly dropping a panel would
    # build the model from less data than the user believes they supplied.
    scene = _scene(
        ("a_main", "main", "k/a.png"),
        ("b_main", "main", "k/b.png"),
        ("c_left", "left", "k/c.png"),
    )
    with pytest.raises(ValueError, match="only one can be the main image"):
        build_multi_view_payload(scene, "g1")


def test_multiple_mains_message_names_the_count():
    scene = _scene(
        ("a_main", "main", "k/a.png"),
        ("b_main", "main", "k/b.png"),
    )
    with pytest.raises(ValueError, match="Two views are labelled Main Image"):
        build_multi_view_payload(scene, "g1")


# ---------------------------------------------------------------------------
# build_multi_view_payload — front views are shown but never sent
# ---------------------------------------------------------------------------

def test_front_view_is_skipped_with_a_warning():
    # Hunyuan's ViewType enum has no 'front' member, so a sheet that has BOTH
    # a hero pose and a front orthographic cannot send the latter.
    scene = _scene(
        ("orc_hero", "main", "k/hero.png"),
        ("orc_front", "front", "k/front.png"),
        ("orc_left", "left", "k/left.png"),
    )
    payload, warnings = build_multi_view_payload(scene, "g1")

    assert payload["multi_view_images"] == [
        {"s3_key": "k/left.png", "view_type": "left"}
    ]
    assert any("no front slot" in w and "orc_front" in w for w in warnings)


def test_front_relabelled_main_becomes_the_submitted_image():
    # The documented escape hatch: switch the front view to Main Image.
    scene = _scene(
        ("orc_hero", "none", "k/hero.png"),
        ("orc_front", "main", "k/front.png"),
    )
    payload, _ = build_multi_view_payload(scene, "g1")

    assert payload["image_s3_key"] == "k/front.png"


# ---------------------------------------------------------------------------
# build_multi_view_payload — hand-added views (no S3 key)
# ---------------------------------------------------------------------------

def test_keyless_view_is_sent_as_inline_bytes():
    scene = _scene(
        ("orc_main", "main", "k/main.png"),
        ("orc_left", "left", ""),
    )
    payload, warnings = build_multi_view_payload(scene, "g1")

    assert payload["image_s3_key"] == "k/main.png"
    assert payload["multi_view_images"] == [
        {
            "image_bytes_b64": "b64(orc_left)",
            "filename": "left.png",
            "view_type": "left",
        }
    ]
    assert not warnings


def test_keyless_main_is_sent_as_inline_bytes():
    scene = _scene(
        ("orc_main", "main", ""),
        ("orc_left", "left", "k/left.png"),
    )
    payload, _ = build_multi_view_payload(scene, "g1")

    assert payload["image_bytes_b64"] == "b64(orc_main)"
    assert payload["image_filename"] == "image.png"
    assert "image_s3_key" not in payload


def test_detected_and_hand_added_views_mix_in_one_payload():
    # job_queue/uploads.py stages only the entries carrying image_bytes_b64
    # and passes S3 keys straight through, so a mixed list is legal.
    scene = _scene(
        ("orc_main", "main", "k/main.png"),
        ("orc_left", "left", "k/left.png"),
        ("orc_top", "top", ""),
    )
    payload, _ = build_multi_view_payload(scene, "g1")

    shapes = [sorted(mv) for mv in payload["multi_view_images"]]
    assert shapes == [
        ["s3_key", "view_type"],
        ["filename", "image_bytes_b64", "view_type"],
    ]


def test_group_built_entirely_by_hand_needs_no_s3_keys_at_all():
    scene = _scene(
        ("hero", "main", ""),
        ("side", "right", ""),
    )
    payload, warnings = build_multi_view_payload(scene, "g1")

    assert payload["image_bytes_b64"] == "b64(hero)"
    assert payload["multi_view_images"][0]["image_bytes_b64"] == "b64(side)"
    assert not warnings


# ---------------------------------------------------------------------------
# build_multi_view_payload — labelling warnings
# ---------------------------------------------------------------------------

def test_duplicate_view_types_are_deduped_with_a_warning():
    scene = _scene(
        ("orc_main", "main", "k/main.png"),
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
        ("orc_main", "main", "k/main.png"),
        ("orc_mystery", "none", "k/x.png"),
    )
    payload, warnings = build_multi_view_payload(scene, "g1")

    assert "multi_view_images" not in payload
    assert any("no view label" in w for w in warnings)


def test_empty_group_is_rejected():
    scene = _scene(("orc_main", "main", "k/main.png"), group="other")
    with pytest.raises(ValueError, match="no images"):
        build_multi_view_payload(scene, "g1")


# ---------------------------------------------------------------------------
# Pro job payload wiring (mixie.hunyuan_generate multi_view=True)
# ---------------------------------------------------------------------------

# Imported inside the tests: generation_enqueue pulls in the HTTP stack, which
# is only present inside Blender.

_SHARED = {"generate_type": "Normal", "enable_pbr": False, "model_version": "3.1"}
_TURNAROUND = {
    "image_s3_key": "k/main.png",
    "multi_view_images": [{"s3_key": "k/left.png", "view_type": "left"}],
}


def test_pro_payload_forwards_s3_keys_without_uploading_pixels():
    from mixar.modules.moodboard.core.generation_enqueue import (
        _build_pro_payload,
    )
    payload, _ = _build_pro_payload(b"", _SHARED, None, _TURNAROUND)

    assert payload["image_s3_key"] == "k/main.png"
    assert payload["multi_view_images"] == _TURNAROUND["multi_view_images"]
    assert "image_bytes_b64" not in payload


def test_pro_payload_turnaround_overrides_inline_bytes():
    # A turnaround submit must never also carry the whole sheet's base64.
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
# Group lookup and editing
# ---------------------------------------------------------------------------

def test_find_group_for_image_only_matches_grouped_items():
    scene = _scene(("orc_main", "main", "k/main.png"))
    scene.mixie_moodboard_images.append(
        FakeItem("loose", "none", "", "")
    )
    assert find_group_for_image(scene, scene.mixie_moodboard_images[0].image) == "g1"
    assert find_group_for_image(scene, scene.mixie_moodboard_images[1].image) == ""
    assert find_group_for_image(scene, None) == ""


def test_group_items_puts_main_first():
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_main", "main", "k/main.png"),
    )
    assert [i.view_type for i in group_items(scene, "g1")] == ["main", "left"]


def test_main_item_is_none_unless_exactly_one_is_labelled():
    assert main_item(_scene(("a", "left", "k/a.png")), "g1") is None
    assert main_item(
        _scene(("a", "main", "k/a.png"), ("b", "main", "k/b.png")), "g1"
    ) is None
    assert main_item(_scene(("a", "main", "k/a.png")), "g1").image.name == "a"


def test_detach_image_removes_one_view_and_leaves_the_rest():
    scene = _scene(
        ("orc_main", "main", "k/main.png"),
        ("orc_left", "left", "k/left.png"),
    )
    dropped = scene.mixie_moodboard_images[1]

    assert detach_image(scene, "g1", dropped.image) is True
    assert dropped.turnaround_group == ""
    assert dropped.view_type == "none"
    # The S3 key is scoped to the group and must not survive the detach.
    assert dropped.s3_key == ""
    assert [i.image.name for i in group_items(scene, "g1")] == ["orc_main"]


def test_detach_image_ignores_images_outside_the_group():
    scene = _scene(("orc_main", "main", "k/main.png"))
    assert detach_image(scene, "g1", FakeImage("stranger")) is False
    assert detach_image(scene, "", scene.mixie_moodboard_images[0].image) is False


def test_set_main_image_demotes_the_previous_main():
    scene = _scene(
        ("hero", "main", "k/hero.png"),
        ("front", "front", "k/front.png"),
    )
    new_main = scene.mixie_moodboard_images[1].image

    set_main_image(scene, "g1", new_main)

    assert scene.mixie_moodboard_images[0].view_type == "none"
    assert scene.mixie_moodboard_images[1].view_type == "main"
    # And the group is submittable again straight away.
    payload, _ = build_multi_view_payload(scene, "g1")
    assert payload["image_s3_key"] == "k/front.png"


# ---------------------------------------------------------------------------
# Response sanitising
# ---------------------------------------------------------------------------

def test_sanitise_panels_keeps_valid_panels_main_first():
    panels = _sanitise_panels([
        {"view_type": "left", "s3_key": "k/l", "preview_url": "http://l"},
        {"view_type": "main", "s3_key": "k/m", "preview_url": "http://m"},
    ])
    assert [p["view_type"] for p in panels] == ["main", "left"]


def test_sanitise_panels_keeps_a_front_alongside_the_main():
    # A sheet with BOTH a hero and a front orthographic returns both.
    panels = _sanitise_panels([
        {"view_type": "main", "s3_key": "k/m", "preview_url": "http://m"},
        {"view_type": "front", "s3_key": "k/f", "preview_url": "http://f"},
    ])
    assert [p["view_type"] for p in panels] == ["main", "front"]


def test_sanitise_panels_drops_unknown_view_types():
    panels = _sanitise_panels([
        {"view_type": "main", "s3_key": "k/m", "preview_url": "http://m"},
        {"view_type": "diagonal", "s3_key": "k/d", "preview_url": "http://d"},
    ])
    assert [p["view_type"] for p in panels] == ["main"]


def test_sanitise_panels_drops_entries_missing_key_or_url():
    panels = _sanitise_panels([
        {"view_type": "main", "s3_key": "k/m", "preview_url": "http://m"},
        {"view_type": "left", "preview_url": "http://l"},
        {"view_type": "back", "s3_key": "k/b"},
    ])
    assert [p["view_type"] for p in panels] == ["main"]


def test_sanitise_panels_without_main_yields_nothing():
    # Never build a group we cannot submit — no main means no primary image.
    assert _sanitise_panels([
        {"view_type": "left", "s3_key": "k/l", "preview_url": "http://l"},
        {"view_type": "front", "s3_key": "k/f", "preview_url": "http://f"},
    ]) == []


def test_sanitise_panels_keeps_only_the_first_main():
    panels = _sanitise_panels([
        {"view_type": "main", "s3_key": "k/m1", "preview_url": "http://m1"},
        {"view_type": "main", "s3_key": "k/m2", "preview_url": "http://m2"},
        {"view_type": "right", "s3_key": "k/r", "preview_url": "http://r"},
    ])
    assert [p["view_type"] for p in panels] == ["main", "right"]
    assert panels[0]["s3_key"] == "k/m1"
