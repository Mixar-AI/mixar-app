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
    build_active_group_payload,
    clear_group,
    clear_group_main,
    detach_image,
    eligible_selected_images,
    find_group_for_image,
    get_active_group,
    group_id_for_main_image,
    group_items,
    group_summary,
    main_image_item,
    next_free_view_type,
    remaining_capacity,
    set_active_group,
    set_group_main_image,
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


def test_allowed_view_types_never_narrows_by_slug():
    # Angle capability is catalog data. This used to narrow to left/right/back
    # for a hardcoded list of "3.0" slugs — rows that are disabled in the
    # catalog, so the gate never fired while still encoding a vendor-version
    # assumption on the client. Every slug now gets the vendor's seven.
    for slug in ("hunyuan_pro_v3", "hunyuan_pro_v2.5", "hunyuan_pro_v3.1",
                 "hunyuan-pro-fal", "", "some_future_model"):
        assert allowed_view_types(slug) == TURNAROUND_VIEW_ORDER


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
    def __init__(self, name, view_type, s3_key, group="", selected=False,
                 main_of=""):
        self.image = FakeImage(name)
        self.view_type = view_type
        self.s3_key = s3_key
        self.turnaround_group = group
        # The ONLY link between a set and an image. Companions and ordinary
        # images leave it empty; exactly one item per group carries it.
        self.turnaround_main_group = main_of
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


def _main(name="orc_main", s3_key="k/main.png", scene=None, main_of=""):
    """An input image that lives on the board (so it can carry an S3 key).

    Pass ``main_of="g1"`` to BIND it to that set — without the marker the set
    does not apply to it, which is the whole point of the binding.
    """
    item = FakeItem(name, "left", s3_key, "", main_of=main_of)
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

def test_every_angle_is_sent_regardless_of_slug():
    # No client-side angle gate: the catalog carries no per-model view-type
    # capability, so the client must not invent one from a slug.
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_top", "top", "k/top.png"),
    )
    payload, warnings = build_multi_view_payload(
        scene, "g1", _main(scene=scene), "hunyuan_pro_v3")

    assert payload["multi_view_images"] == [
        {"s3_key": "k/left.png", "view_type": "left"},
        {"s3_key": "k/top.png", "view_type": "top"},
    ]
    assert not warnings


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


# ---------------------------------------------------------------------------
# A set is bound to its frontal image, and applies only to that image
# ---------------------------------------------------------------------------

@pytest.fixture
def accepts_mv(monkeypatch):
    """Only 'hunyuan-pro-fal' takes multi-view input."""
    monkeypatch.setattr(
        "mixar.modules.moodboard.core.turnaround_views."
        "model_accepts_multi_view",
        lambda service, model: (
            service == "model_3d" and model == "hunyuan-pro-fal"
        ),
    )


def test_agent_model_3d_payload_includes_the_active_companion_set(accepts_mv):
    """The direct agent operator uses this helper before encoding one image."""
    tab = FakeTab(group="g1")
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
        tab=tab,
    )
    main_image = _main(scene=scene, main_of="g1")

    result = build_active_group_payload(
        scene, main_image, "model_3d", "hunyuan-pro-fal")

    payload, warnings = result
    assert payload == {
        "image_s3_key": "k/main.png",
        "multi_view_images": [
            {"s3_key": "k/left.png", "view_type": "left"},
            {"s3_key": "k/back.png", "view_type": "back"},
        ],
    }
    assert warnings == []


def test_an_unrelated_image_never_inherits_a_set_active_elsewhere(accepts_mv):
    """The production regression: turn 1 detects a Ganesha turnaround, turn 2
    converts an unrelated dragon image. The dragon is not the set's frontal
    image, so it must take the plain single-image path — previously the group
    was read off the TAB and Ganesha's left/back views were attached to the
    dragon, producing a morph of the two."""
    tab = FakeTab(group="turnaround_ganesha")
    scene = _scene(
        ("ganesha_left", "left", "k/left.png"),
        ("ganesha_back", "back", "k/back.png"),
        group="turnaround_ganesha",
        tab=tab,
    )
    _main("ganesha_main", "k/ganesha.png", scene, main_of="turnaround_ganesha")
    dragon = _main("dragon_front_001", "k/dragon.png", scene)

    # The set is still active on the tab — it is simply not the dragon's.
    assert get_active_group(scene) == "turnaround_ganesha"
    assert group_id_for_main_image(scene, dragon) == ""
    assert build_active_group_payload(
        scene, dragon, "model_3d", "hunyuan-pro-fal") is None


def test_an_incapable_model_on_an_unrelated_image_is_not_an_error(accepts_mv):
    """The second half of the same regression: 'tripo-low' was refused
    outright because the tab still held a set, so the agent retried and then
    switched engines. With no set bound to this image there is nothing to
    refuse."""
    tab = FakeTab(group="turnaround_ganesha")
    scene = _scene(
        ("ganesha_left", "left", "k/left.png"),
        group="turnaround_ganesha",
        tab=tab,
    )
    _main("ganesha_main", "k/ganesha.png", scene, main_of="turnaround_ganesha")
    dragon = _main("dragon_front_001", "k/dragon.png", scene)

    assert build_active_group_payload(
        scene, dragon, "model_3d", "tripo-low") is None


def test_a_companion_is_not_its_own_sets_main(accepts_mv):
    scene = _scene(("orc_left", "left", "k/left.png"))
    _main(scene=scene, main_of="g1")
    companion = scene.mixie_moodboard_images[0].image

    assert group_id_for_main_image(scene, companion) == ""
    assert build_active_group_payload(
        scene, companion, "model_3d", "hunyuan-pro-fal") is None


def test_a_set_whose_companions_all_vanished_reports_as_absent(accepts_mv):
    # Same self-healing get_active_group does: a dangling marker left by a
    # deleted/undone companion must not make the frontal image unusable.
    scene = FakeScene([])
    orphan = _main(scene=scene, main_of="g1")

    assert group_id_for_main_image(scene, orphan) == ""
    assert build_active_group_payload(
        scene, orphan, "model_3d", "tripo-low") is None


def test_bound_set_never_degrades_to_one_image_when_catalog_rejects_model(
    accepts_mv,
):
    tab = FakeTab(group="g1")
    scene = _scene(("orc_left", "left", "k/left.png"), tab=tab)
    main_image = _main(scene=scene, main_of="g1")

    # Terminal, and worded so the agent has no reason to try another engine:
    # substituting a multi-view model is exactly how the wrong views got
    # attached in production.
    with pytest.raises(ValueError) as excinfo:
        build_active_group_payload(scene, main_image, "model_3d", "tripo-low")

    message = str(excinfo.value)
    assert "'tripo-low' cannot use the 1-view set on 'orc_main'" in message
    assert "do NOT retry with a different model" in message


def test_set_group_main_image_keeps_exactly_one_main(accepts_mv):
    scene = _scene(("orc_left", "left", "k/left.png"))
    first = _main("first", "k/first.png", scene, main_of="g1")
    second = _main("second", "k/second.png", scene)

    assert set_group_main_image(scene, "g1", second) is True

    assert group_id_for_main_image(scene, first) == ""
    assert group_id_for_main_image(scene, second) == "g1"
    assert [i.image.name for i in scene.mixie_moodboard_images
            if i.turnaround_main_group == "g1"] == ["second"]


def test_a_file_picked_input_image_cannot_be_bound(accepts_mv):
    # Not on the board, so there is no item to carry the marker. The set stays
    # unbound (inert) rather than latching onto the wrong image.
    scene = _scene(("orc_left", "left", "k/left.png"))

    assert set_group_main_image(scene, "g1", FakeImage("picked")) is False
    assert build_active_group_payload(
        scene, FakeImage("picked"), "model_3d", "hunyuan-pro-fal") is None


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


def test_clearing_the_group_leaves_no_main_marker_behind():
    # A dangling marker would keep the frontal image claiming a set that no
    # longer exists, and the next incapable model would raise over nothing.
    tab = FakeTab(group="g1")
    scene = _scene(("orc_left", "left", "k/left.png"), tab=tab)
    main_image = _main(scene=scene, main_of="g1")

    clear_group(scene, "g1")

    assert main_image_item(scene, "g1") is None
    assert group_id_for_main_image(scene, main_image) == ""
    assert all(
        i.turnaround_main_group == "" for i in scene.mixie_moodboard_images)


def test_removing_the_last_view_also_unbinds_the_main():
    tab = FakeTab(group="g1")
    scene = _scene(("orc_left", "left", "k/left.png"), tab=tab)
    main_image = _main(scene=scene, main_of="g1")

    detach_image(scene, "g1", scene.mixie_moodboard_images[0].image)

    assert tab.turnaround_group == ""
    assert group_id_for_main_image(scene, main_image) == ""


def test_removing_one_of_several_views_keeps_the_main_bound():
    tab = FakeTab(group="g1")
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
        tab=tab,
    )
    main_image = _main(scene=scene, main_of="g1")

    detach_image(scene, "g1", scene.mixie_moodboard_images[0].image)

    assert group_id_for_main_image(scene, main_image) == "g1"


def test_clear_group_main_is_a_no_op_on_an_unknown_group():
    scene = _scene(("orc_left", "left", "k/left.png"))
    main_image = _main(scene=scene, main_of="g1")

    clear_group_main(scene, "other")

    assert group_id_for_main_image(scene, main_image) == "g1"


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


def test_next_free_view_type_walks_the_full_vendor_order():
    scene = _scene(
        ("a", "left", ""), ("b", "right", ""), ("c", "back", ""),
    )
    # No slug narrows the set any more, so the next free angle is simply the
    # next one in TURNAROUND_VIEW_ORDER. An explicit `allowed` still restricts.
    assert next_free_view_type(
        scene, "g1", allowed=allowed_view_types()) == "top"
    assert next_free_view_type(
        scene, "g1", allowed=('left', 'right', 'back')) == ""


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


def test_add_images_as_views_uses_every_vendor_angle():
    scene = FakeScene([FakeItem(str(i), "left", "") for i in range(5)])
    images = [item.image for item in scene.mixie_moodboard_images]

    # Formerly capped at left/right/back for "3.0" slugs. The slug no longer
    # narrows anything, so all five land on the first five vendor angles.
    attached, skipped = add_images_as_views(
        scene, "g1", images, "hunyuan_pro_v3")

    assert attached == ["left", "right", "back", "top", "bottom"]
    assert skipped == 0


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


def _promote(scene, group_id, image, model_slug=""):
    """The core half of MIXIE_OT_moodboard_promote_turnaround_view.

    The operator itself cannot be imported outside Blender (its base class is
    a MagicMock), so the sequence it performs is replayed here: remember the
    outgoing main, detach the promoted view, demote the old main into the
    angle just freed, then move the marker. Returns the demoted item's angle,
    or "" when it stayed a plain board image.
    """
    previous_item = main_image_item(scene, group_id)
    detach_image(scene, group_id, image, keep_s3_key=True)

    demoted = ""
    if previous_item is not None and previous_item.image:
        previous_item.turnaround_main_group = ""
        if remaining_capacity(scene, group_id) > 0:
            demoted = next_free_view_type(
                scene, group_id, allowed=allowed_view_types(model_slug))
            if demoted:
                attach_image(scene, group_id, previous_item.image, demoted)

    if group_items(scene, group_id):
        clear_group_main(scene, group_id)
        set_group_main_image(scene, group_id, image)
        set_active_group(scene, group_id)
    set_tab_input_image(scene, image)
    return demoted


def test_promoting_moves_the_main_marker_to_the_promoted_view():
    tab = FakeTab(group="g1")
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
        tab=tab,
    )
    old_main = _main(scene=scene, main_of="g1")
    promoted = scene.mixie_moodboard_images[0].image

    _promote(scene, "g1", promoted)

    assert group_id_for_main_image(scene, promoted) == "g1"
    assert group_id_for_main_image(scene, old_main) == ""
    # Exactly one main survives — the invariant the backend snippet relies on.
    assert [i.image.name for i in scene.mixie_moodboard_images
            if i.turnaround_main_group == "g1"] == ["orc_left"]
    # And the promoted image is no longer one of its own companions.
    assert "orc_left" not in [i.image.name for i in group_items(scene, "g1")]


def test_promoting_demotes_the_old_main_into_the_freed_angle():
    # Promotion frees exactly one angle, and the outgoing input image is a
    # real view of the same subject — dropping it from the job would lose
    # information for no reason.
    tab = FakeTab(group="g1")
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
        tab=tab,
    )
    old_main = _main(scene=scene, main_of="g1")

    demoted = _promote(scene, "g1", scene.mixie_moodboard_images[0].image)

    assert demoted == "left"
    assert [(i.image.name, i.view_type) for i in group_items(scene, "g1")] == [
        ("orc_main", "left"), ("orc_back", "back"),
    ]
    assert group_id_for_main_image(scene, old_main) == ""


def test_promoting_the_only_companion_swaps_the_pair_and_keeps_the_tab():
    # Detaching the last companion self-heals the tab to "" mid-operation;
    # the demotion refills the set, so the panel has to be pointed back at it
    # or a perfectly good 1-view set disappears from the UI.
    tab = FakeTab(group="g1")
    scene = _scene(("orc_left", "left", "k/left.png"), tab=tab)
    old_main = _main(scene=scene, main_of="g1")
    promoted = scene.mixie_moodboard_images[0].image

    demoted = _promote(scene, "g1", promoted)

    assert demoted == "left"
    assert tab.turnaround_group == "g1"
    assert group_id_for_main_image(scene, promoted) == "g1"
    assert group_id_for_main_image(scene, old_main) == ""
    assert [i.image.name for i in group_items(scene, "g1")] == ["orc_main"]


def test_promoting_over_an_unbound_set_demotes_nothing():
    # The old main was a file-picked reference image, so it never carried the
    # marker and there is no board item to demote. The promoted view still
    # becomes the main — that is what makes the set usable at all.
    tab = FakeTab(group="g1", use_selected=False)
    tab.reference_image = FakeImage("picked")
    scene = _scene(
        ("orc_left", "left", "k/left.png"),
        ("orc_back", "back", "k/back.png"),
        tab=tab,
    )
    promoted = scene.mixie_moodboard_images[0].image

    demoted = _promote(scene, "g1", promoted)

    assert demoted == ""
    assert group_id_for_main_image(scene, promoted) == "g1"
    assert [i.image.name for i in group_items(scene, "g1")] == ["orc_back"]


def test_promoting_deselects_the_previous_input_image():
    tab = FakeTab(group="g1")
    previous = FakeItem("previous", "left", "", "", selected=True)
    scene = _scene(("orc_left", "left", "k/left.png"), tab=tab)
    scene.mixie_moodboard_images.append(previous)
    promoted = scene.mixie_moodboard_images[0]

    detach_image(scene, "g1", promoted.image, keep_s3_key=True)
    set_tab_input_image(scene, promoted.image)

    # A previous input image that never owned the set (no main marker) is
    # simply deselected and left untagged — see _promote() above for the
    # bound case, where it swaps into the angle the promotion freed.
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
