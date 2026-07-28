# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for turnaround (model-sheet) multi-view payload assembly.

These cover the frozen backend contract for POST /job-queue/jobs. The vendor
takes ONE frontal image plus up to SEVEN angles: the frontal image is the
Model Gen tab's Input Image (``image_s3_key`` / ``image_bytes_b64``) and the
turnaround group holds the companion angles only (``multi_view_images``).
There is no 'main', 'front' or 'none' label — the input image is simply not a
group member, so it can never leak into ``multi_view_images``.

Detected crops carry an S3 key; views the user added by hand do not and carry
inline base64 pixels instead. The two shapes mix within one payload.
"""

import pytest

from mixar.modules.common.utils.image_compression_config import (
    get_compression_settings,
)
from mixar.modules.moodboard.constants import (
    TURNAROUND_MAX_COMPANIONS,
    TURNAROUND_VIEW_ORDER,
    TURNAROUND_VIEW_TYPES,
)
from mixar.modules.moodboard.core import turnaround_payload
from mixar.modules.moodboard.core.turnaround_detect import _sanitise_panels
from mixar.modules.moodboard.core.turnaround_payload import (
    build_multi_view_payload,
)
from mixar.modules.moodboard.core.turnaround_views import (
    add_images_as_views,
    allowed_view_types,
    attach_image,
    clear_group,
    detach_image,
    eligible_selected_images,
    find_group_for_image,
    get_active_group,
    group_items,
    group_summary,
    next_free_view_type,
    remaining_capacity,
    set_active_group,
    set_tab_input_image,
)


# ---------------------------------------------------------------------------
# View vocabulary — frozen against the vendor's ViewType enum
# ---------------------------------------------------------------------------

def test_view_types_are_exactly_the_seven_vendor_angles():
    # Hunyuan Pro 3.1 takes 1 frontal image + 7 angles, 8 images maximum.
    # 'main' / 'front' / 'none' are NOT vendor angles and must not be offered.
    assert TURNAROUND_VIEW_ORDER == (
        'left', 'right', 'back', 'top', 'bottom', 'left_front', 'right_front',
    )
    assert TURNAROUND_MAX_COMPANIONS == 7
    ids = [item[0] for item in TURNAROUND_VIEW_TYPES]
    assert ids == list(TURNAROUND_VIEW_ORDER)
    assert not {'main', 'front', 'none'} & set(ids)


def test_only_left_right_back_are_valid_on_hunyuan_30():
    # top / bottom / left_front / right_front are 3.1-only.
    assert allowed_view_types("hunyuan_pro_v3") == ('left', 'right', 'back')
    assert allowed_view_types("hunyuan_pro_v2.5") == ('left', 'right', 'back')
    assert allowed_view_types("hunyuan_pro_v3.1") == TURNAROUND_VIEW_ORDER
    # Unknown slugs get all seven — under-restricting a future model is
    # recoverable, over-restricting silently drops the user's panels.
    assert allowed_view_types("") == TURNAROUND_VIEW_ORDER
    assert allowed_view_types("some_future_model") == TURNAROUND_VIEW_ORDER


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


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeImage:
    def __init__(self, name):
        self.name = name


class FakeItem:
    def __init__(self, name, view_type, s3_key, group="", selected=False):
        self.image = FakeImage(name)
        self.view_type = view_type
        self.s3_key = s3_key
        self.turnaround_group = group
        self.selected = selected
        self.position_x = 0.0
        self.position_y = 0.0


class FakeTab:
    """Stand-in for the Model Gen tab PropertyGroup."""

    def __init__(self, group="", use_selected=True):
        self.turnaround_group = group
        self.use_selected_image = use_selected
        self.reference_image = None
        self.model = ""


class FakeSidebar:
    def __init__(self, tab):
        self.tab_image_to_3d = tab


class FakeScene:
    def __init__(self, items, tab=None):
        self.mixie_moodboard_images = items
        if tab is not None:
            self.mixie_moodboard_sidebar = FakeSidebar(tab)


def _scene(*specs, group="g1", tab=None):
    return FakeScene(
        [FakeItem(n, v, k, group) for n, v, k in specs], tab=tab)


def _main(name="orc_main", s3_key="k/main.png", scene=None):
    """An input image that lives on the board (so it can carry an S3 key)."""
    item = FakeItem(name, "left", s3_key, "")
    if scene is not None:
        scene.mixie_moodboard_images.append(item)
    return item.image


@pytest.fixture(autouse=True)
def fake_encoder(monkeypatch):
    """Stand in for the bpy-backed JPEG encoder used by keyless views."""
    monkeypatch.setattr(
        turnaround_payload, "_encode_image", lambda image: f"b64({image.name})")


# ---------------------------------------------------------------------------
# build_multi_view_payload — the main image comes from the Input Image
# ---------------------------------------------------------------------------

def test_main_comes_from_the_input_image_not_the_group():
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
    )
    main_image = _main(scene=scene)

    payload, warnings = build_multi_view_payload(scene, "g1", main_image)

    assert payload["image_s3_key"] == "k/main.png"
    assert payload["multi_view_images"] == [
        {"s3_key": "k/left.png", "view_type": "left"},
        {"s3_key": "k/back.png", "view_type": "back"},
    ]
    assert not warnings


def test_input_image_without_a_key_is_sent_as_inline_bytes():
    # A file-picked reference image never reached the moodboard, so there is
    # no item to read an s3_key from.
    scene = _scene(("orc_left", "left", "k/left.png"))
    payload, _ = build_multi_view_payload(scene, "g1", FakeImage("picked"))

    assert payload["image_bytes_b64"] == "b64(picked)"
    assert payload["image_filename"] == "image.png"
    assert "image_s3_key" not in payload


def test_input_image_on_the_board_without_a_key_uses_inline_bytes():
    scene = _scene(("orc_left", "left", "k/left.png"))
    main_image = _main(s3_key="", scene=scene)

    payload, _ = build_multi_view_payload(scene, "g1", main_image)

    assert payload["image_bytes_b64"] == "b64(orc_main)"
    assert "image_s3_key" not in payload


def test_missing_input_image_is_rejected():
    scene = _scene(("orc_left", "left", "k/left.png"))
    with pytest.raises(ValueError, match="input image"):
        build_multi_view_payload(scene, "g1", None)


def test_empty_group_is_rejected():
    scene = _scene(("orc_left", "left", "k/left.png"), group="other")
    with pytest.raises(ValueError, match="no images"):
        build_multi_view_payload(scene, "g1", _main(scene=scene))


def test_input_image_can_never_leak_into_multi_view_images():
    # Structurally impossible now — but if a stale tag ever put the input
    # image in the group, it must still not be sent twice.
    scene = _scene(("orc_left", "left", "k/left.png"))
    stray = FakeItem("orc_main", "right", "k/main.png", "g1")
    scene.mixie_moodboard_images.append(stray)

    payload, _ = build_multi_view_payload(scene, "g1", stray.image)

    assert payload["multi_view_images"] == [
        {"s3_key": "k/left.png", "view_type": "left"}
    ]


# ---------------------------------------------------------------------------
# build_multi_view_payload — hand-added views (no S3 key)
# ---------------------------------------------------------------------------

def test_keyless_view_is_sent_as_inline_bytes():
    scene = _scene(("orc_left", "left", ""))
    payload, warnings = build_multi_view_payload(
        scene, "g1", _main(scene=scene))

    assert payload["multi_view_images"] == [
        {
            "image_bytes_b64": "b64(orc_left)",
            "filename": "left.png",
            "view_type": "left",
        }
    ]
    assert not warnings


def test_detected_and_hand_added_views_mix_in_one_payload():
    # job_queue/uploads.py stages only the entries carrying image_bytes_b64
    # and passes S3 keys straight through, so a mixed list is legal — locked
    # in backend-side by test_payload_key_ownership.py.
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_top", "top", ""),
    )
    payload, _ = build_multi_view_payload(scene, "g1", _main(scene=scene))

    shapes = [sorted(mv) for mv in payload["multi_view_images"]]
    assert shapes == [
        ["s3_key", "view_type"],
        ["filename", "image_bytes_b64", "view_type"],
    ]


def test_group_built_entirely_by_hand_needs_no_s3_keys_at_all():
    scene = _scene(("side", "right", ""))
    payload, warnings = build_multi_view_payload(
        scene, "g1", FakeImage("hero"))

    assert payload["image_bytes_b64"] == "b64(hero)"
    assert payload["multi_view_images"][0]["image_bytes_b64"] == "b64(side)"
    assert not warnings


# ---------------------------------------------------------------------------
# build_multi_view_payload — model gating and duplicate angles
# ---------------------------------------------------------------------------

def test_31_only_angles_are_dropped_with_a_warning_on_30():
    # Better a warned-about omission than a vendor rejection after the
    # credits have already been held.
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_top", "top", "k/top.png"),
    )
    payload, warnings = build_multi_view_payload(
        scene, "g1", _main(scene=scene), "hunyuan_pro_v3")

    assert payload["multi_view_images"] == [
        {"s3_key": "k/left.png", "view_type": "left"}
    ]
    assert any("top" in w and "orc_top" in w for w in warnings)


def test_the_same_angles_are_all_sent_on_31():
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_top", "top", "k/top.png"),
    )
    payload, warnings = build_multi_view_payload(
        scene, "g1", _main(scene=scene), "hunyuan_pro_v3.1")

    assert len(payload["multi_view_images"]) == 2
    assert not warnings


def test_duplicate_view_types_are_deduped_with_a_warning():
    scene = _scene(
        ("orc_left", "left", "k/left1.png"),
        ("orc_left2", "left", "k/left2.png"),
    )
    payload, warnings = build_multi_view_payload(
        scene, "g1", _main(scene=scene))

    assert payload["multi_view_images"] == [
        {"s3_key": "k/left1.png", "view_type": "left"}
    ]
    assert any("left" in w for w in warnings)


# ---------------------------------------------------------------------------
# Active group lives on the tab, not on the input image
# ---------------------------------------------------------------------------

def test_active_group_is_read_from_the_tab():
    tab = FakeTab(group="g1")
    scene = _scene(("orc_left", "left", "k/left.png"), tab=tab)

    assert get_active_group(scene) == "g1"
    # The input image is NOT a member, so the old image-keyed lookup — the
    # one that dead-ended on file-picked reference images — finds nothing.
    assert find_group_for_image(scene, _main(scene=scene)) == ""


def test_active_group_reports_empty_once_the_set_has_no_members():
    tab = FakeTab(group="g1")
    scene = FakeScene([], tab=tab)
    assert get_active_group(scene) == ""


def test_active_group_survives_a_file_picked_input_image():
    # The regression that forced the old _point_tab_at workaround: a group
    # resolved from the input image could not be found at all when the tab
    # used reference_image instead of the moodboard selection.
    tab = FakeTab(group="g1", use_selected=False)
    tab.reference_image = FakeImage("picked")
    scene = _scene(("orc_left", "left", "k/left.png"), tab=tab)

    assert get_active_group(scene) == "g1"


def test_removing_the_last_view_clears_the_tab():
    tab = FakeTab(group="g1")
    scene = _scene(("orc_left", "left", "k/left.png"), tab=tab)

    detach_image(scene, "g1", scene.mixie_moodboard_images[0].image)

    assert tab.turnaround_group == ""


def test_clearing_the_group_clears_the_tab():
    tab = FakeTab(group="g1")
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
        tab=tab,
    )

    assert clear_group(scene, "g1") == 2
    assert tab.turnaround_group == ""


def test_removing_a_view_leaves_a_non_empty_set_alone():
    tab = FakeTab(group="g1")
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
        tab=tab,
    )

    detach_image(scene, "g1", scene.mixie_moodboard_images[0].image)

    assert tab.turnaround_group == "g1"
    assert [i.image.name for i in group_items(scene, "g1")] == ["orc_back"]


def test_set_active_group_is_a_no_op_without_a_tab():
    scene = _scene(("orc_left", "left", "k/left.png"))
    set_active_group(scene, "g1")  # must not raise
    assert get_active_group(scene) == ""


# ---------------------------------------------------------------------------
# Auto-assignment — what makes Add Selected one click
# ---------------------------------------------------------------------------

def test_next_free_view_type_walks_the_canonical_order():
    scene = _scene(("orc_left", "left", "k/left.png"))
    assert next_free_view_type(scene, "g1") == "right"


def test_next_free_view_type_skips_reserved_angles():
    # Reserving lets one batch assign several angles before any is written.
    scene = _scene(("orc_left", "left", "k/left.png"))
    assert next_free_view_type(scene, "g1", taken=["right"]) == "back"


def test_next_free_view_type_respects_the_model_limit():
    scene = _scene(
        ("a", "left", ""), ("b", "right", ""), ("c", "back", ""),
    )
    assert next_free_view_type(
        scene, "g1", allowed=allowed_view_types("hunyuan_pro_v3")) == ""
    assert next_free_view_type(
        scene, "g1", allowed=allowed_view_types("hunyuan_pro_v3.1")) == "top"


def test_add_images_as_views_assigns_the_next_unused_angles():
    scene = FakeScene([
        FakeItem("a", "left", ""), FakeItem("b", "left", ""),
        FakeItem("c", "left", ""),
    ])
    images = [item.image for item in scene.mixie_moodboard_images]

    attached, skipped = add_images_as_views(scene, "g1", images)

    assert attached == ["left", "right", "back"]
    assert skipped == 0
    assert [i.view_type for i in group_items(scene, "g1")] == [
        "left", "right", "back"]


def test_add_images_as_views_never_assigns_a_31_only_angle_on_30():
    scene = FakeScene([FakeItem(str(i), "left", "") for i in range(5)])
    images = [item.image for item in scene.mixie_moodboard_images]

    attached, skipped = add_images_as_views(
        scene, "g1", images, "hunyuan_pro_v3")

    assert attached == ["left", "right", "back"]
    assert skipped == 2


def test_add_images_as_views_stops_at_the_vendor_cap():
    scene = FakeScene([FakeItem(str(i), "left", "") for i in range(9)])
    images = [item.image for item in scene.mixie_moodboard_images]

    attached, skipped = add_images_as_views(scene, "g1", images)

    assert len(attached) == TURNAROUND_MAX_COMPANIONS
    assert skipped == 2
    assert remaining_capacity(scene, "g1") == 0
    assert group_summary(scene, "g1") == "7 of 7"


def test_add_images_as_views_fills_a_gap_left_by_a_removed_view():
    scene = _scene(
        ("a", "left", ""), ("b", "back", ""),
    )
    spare = FakeItem("c", "left", "", "")
    scene.mixie_moodboard_images.append(spare)

    attached, _ = add_images_as_views(scene, "g1", [spare.image])

    assert attached == ["right"]


def test_attaching_tags_an_existing_moodboard_image_in_place():
    # Never duplicated: Add Selected promotes images already on the board.
    scene = FakeScene([FakeItem("a", "left", "", "")])
    image = scene.mixie_moodboard_images[0].image

    attach_image(scene, "g1", image, "back")

    assert len(scene.mixie_moodboard_images) == 1
    assert scene.mixie_moodboard_images[0].turnaround_group == "g1"
    assert scene.mixie_moodboard_images[0].view_type == "back"


# ---------------------------------------------------------------------------
# Add Selected eligibility
# ---------------------------------------------------------------------------

def test_eligible_images_exclude_the_input_image_and_current_views():
    member = FakeItem("in_set", "left", "", "g1", selected=True)
    main = FakeItem("input", "left", "", "", selected=True)
    fresh = FakeItem("fresh", "left", "", "", selected=True)
    unselected = FakeItem("unselected", "left", "", "", selected=False)
    scene = FakeScene([member, main, fresh, unselected])

    eligible = eligible_selected_images(scene, "g1", main.image)

    assert [i.name for i in eligible] == ["fresh"]


def test_eligible_images_before_a_group_exists():
    main = FakeItem("input", "left", "", "", selected=True)
    other = FakeItem("other", "left", "", "", selected=True)
    scene = FakeScene([main, other])

    assert [i.name for i in eligible_selected_images(scene, "", main.image)] \
        == ["other"]


# ---------------------------------------------------------------------------
# Promote to input image
# ---------------------------------------------------------------------------

def test_promoting_a_view_keeps_its_s3_key():
    # The key is a valid upload of these exact pixels, so a promoted crop
    # still submits by key instead of being re-encoded.
    tab = FakeTab(group="g1")
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
        tab=tab,
    )
    promoted = scene.mixie_moodboard_images[0]

    assert detach_image(scene, "g1", promoted.image, keep_s3_key=True) is True
    set_tab_input_image(scene, promoted.image)

    assert promoted.turnaround_group == ""
    assert promoted.s3_key == "k/left.png"
    assert promoted.selected is True
    assert [i.image.name for i in group_items(scene, "g1")] == ["orc_back"]

    payload, _ = build_multi_view_payload(scene, "g1", promoted.image)
    assert payload["image_s3_key"] == "k/left.png"


def test_promoting_deselects_the_previous_input_image():
    tab = FakeTab(group="g1")
    previous = FakeItem("previous", "left", "", "", selected=True)
    scene = _scene(("orc_left", "left", "k/left.png"), tab=tab)
    scene.mixie_moodboard_images.append(previous)
    promoted = scene.mixie_moodboard_images[0]

    detach_image(scene, "g1", promoted.image, keep_s3_key=True)
    set_tab_input_image(scene, promoted.image)

    # The old input image is an ordinary untagged moodboard image again — it
    # cannot join the set, as no vendor angle describes a front view.
    assert previous.selected is False
    assert previous.turnaround_group == ""


def test_promoting_sets_reference_image_when_the_tab_uses_the_picker():
    tab = FakeTab(group="g1", use_selected=False)
    scene = _scene(("orc_left", "left", "k/left.png"), tab=tab)
    promoted = scene.mixie_moodboard_images[0]

    set_tab_input_image(scene, promoted.image)

    assert tab.reference_image is promoted.image


def test_removing_a_view_still_drops_its_s3_key():
    # Plain removal keeps the old behaviour: the key is scoped to the
    # detected group and a re-detect mints a new one.
    scene = _scene(("orc_left", "left", "k/left.png"))
    dropped = scene.mixie_moodboard_images[0]

    assert detach_image(scene, "g1", dropped.image) is True
    assert dropped.s3_key == ""
    assert dropped.view_type in TURNAROUND_VIEW_ORDER


def test_detach_image_ignores_images_outside_the_group():
    scene = _scene(("orc_left", "left", "k/left.png"))
    assert detach_image(scene, "g1", FakeImage("stranger")) is False
    assert detach_image(scene, "", scene.mixie_moodboard_images[0].image) is False


def test_group_items_are_ordered_by_the_canonical_angle_order():
    scene = _scene(
        ("c", "back", ""), ("a", "left", ""), ("b", "right", ""),
    )
    assert [i.view_type for i in group_items(scene, "g1")] == [
        "left", "right", "back"]


def test_group_summary_is_none_without_a_set():
    assert group_summary(FakeScene([]), "g1") is None


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
# Response sanitising
# ---------------------------------------------------------------------------

def test_sanitise_panels_keeps_valid_panels_main_first():
    panels = _sanitise_panels([
        {"view_type": "left", "s3_key": "k/l", "preview_url": "http://l"},
        {"view_type": "main", "s3_key": "k/m", "preview_url": "http://m"},
    ])
    assert [p["view_type"] for p in panels] == ["main", "left"]


def test_sanitise_panels_orders_hero_right_after_main():
    # A sheet with BOTH a front orthographic and a hero render returns both;
    # hero is an alternative main image, never a companion view.
    panels = _sanitise_panels([
        {"view_type": "left", "s3_key": "k/l", "preview_url": "http://l"},
        {"view_type": "hero", "s3_key": "k/h", "preview_url": "http://h"},
        {"view_type": "main", "s3_key": "k/m", "preview_url": "http://m"},
    ])
    assert [p["view_type"] for p in panels] == ["main", "hero", "left"]


def test_sanitise_panels_drops_unknown_view_types():
    panels = _sanitise_panels([
        {"view_type": "main", "s3_key": "k/m", "preview_url": "http://m"},
        {"view_type": "diagonal", "s3_key": "k/d", "preview_url": "http://d"},
        {"view_type": "front", "s3_key": "k/f", "preview_url": "http://f"},
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
    # Never build a set we cannot submit — no main means no input image.
    assert _sanitise_panels([
        {"view_type": "left", "s3_key": "k/l", "preview_url": "http://l"},
        {"view_type": "hero", "s3_key": "k/h", "preview_url": "http://h"},
    ]) == []


def test_sanitise_panels_keeps_only_the_first_main_and_hero():
    panels = _sanitise_panels([
        {"view_type": "main", "s3_key": "k/m1", "preview_url": "http://m1"},
        {"view_type": "main", "s3_key": "k/m2", "preview_url": "http://m2"},
        {"view_type": "hero", "s3_key": "k/h1", "preview_url": "http://h1"},
        {"view_type": "hero", "s3_key": "k/h2", "preview_url": "http://h2"},
        {"view_type": "right", "s3_key": "k/r", "preview_url": "http://r"},
    ])
    assert [p["view_type"] for p in panels] == ["main", "hero", "right"]
    assert panels[0]["s3_key"] == "k/m1"
    assert panels[1]["s3_key"] == "k/h1"


def test_sanitise_panels_caps_companions_at_the_vendor_limit():
    raw = [{"view_type": "main", "s3_key": "k/m", "preview_url": "http://m"}]
    raw += [
        {"view_type": view, "s3_key": f"k/{view}", "preview_url": f"http://{view}"}
        for view in TURNAROUND_VIEW_ORDER
    ]
    # One more than the vendor accepts, duplicated angle aside.
    raw.append(
        {"view_type": "left", "s3_key": "k/extra", "preview_url": "http://x"})

    panels = _sanitise_panels(raw)

    assert len(panels) == 1 + TURNAROUND_MAX_COMPANIONS
    assert "k/extra" not in [p["s3_key"] for p in panels]
