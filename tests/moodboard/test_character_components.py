# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Contracts for SAM3-guided character-component detail generation."""

import base64
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from mixar.modules.moodboard.constants import CHARACTER_COMPONENT_BACKGROUND_RGB
from mixar.modules.moodboard.core import character_components as COMPONENTS
from mixar.modules.moodboard.core.character_components import (
    ComponentReferences,
    build_component_detail_prompt,
    build_component_payload,
    component_output_name,
    eligible_component_model_slugs,
    ensure_component_id,
    ensure_moodboard_item_id,
    model_reference_limit,
    model_supports_component_details,
    prepare_component_references,
    stamp_component_outputs,
)
from mixar.modules.moodboard.core.mask_guidance import constrain_refined_mask


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (None, False),
        ({"slug": "implicit"}, False),
        ({"slug": "single", "max_reference_images": 1}, False),
        ({"slug": "unadvertised", "max_reference_images": 8}, False),
        ({
            "slug": "two",
            "max_reference_images": "2",
            "supports_mask_guidance": True,
        }, True),
        ({
            "slug": "three",
            "max_reference_images": 3,
            "supports_mask_guidance": True,
        }, True),
        ({
            "slug": "disabled",
            "max_reference_images": 8,
            "supports_mask_guidance": False,
        }, False),
    ],
)
def test_component_models_fail_closed_on_catalog_capability(model, expected):
    assert model_supports_component_details(model) is expected


def test_catalog_filter_and_reference_limit_do_not_guess_model_names():
    models = [
        {
            "slug": "provider-fast",
            "max_reference_images": 1,
            "supports_mask_guidance": True,
        },
        {"slug": "unadvertised", "max_reference_images": 12},
        {
            "slug": "provider-edit",
            "max_reference_images": 2,
            "supports_mask_guidance": True,
        },
        {
            "slug": "provider-pro",
            "max_reference_images": 12,
            "supports_mask_guidance": True,
        },
    ]

    assert eligible_component_model_slugs(models) == {
        "provider-edit",
        "provider-pro",
    }
    assert model_reference_limit({"max_reference_images": "bad"}) == 0


def test_payload_preserves_reference_roles_and_supports_multiple_outputs():
    references = ComponentReferences(
        full_source=b"full-character",
        component_cutout=b"armor-cutout",
        binary_mask=b"binary-mask",
        crop_box=(1, 2, 3, 4),
        source_size=(10, 20),
    )

    payload = build_component_payload(
        references,
        component_name="Torso Armor",
        extra_instructions="Show rear fasteners",
        params={"number_of_images": 4, "resolution": "2K"},
        image_name="hero_torso_detail",
        views_per_component=3,
    )

    decoded = [
        base64.b64decode(value) for value in payload["reference_images_b64"]
    ]
    assert decoded == [b"full-character", b"armor-cutout", b"binary-mask"]
    assert payload["reference_image_roles"] == [
        "full_context",
        "component_cutout",
        "selection_mask",
    ]
    assert payload["params"] == {"number_of_images": 3, "resolution": "2K"}
    assert payload["image_name"] == "hero_torso_detail"
    assert "Reference image 1 is the full character" in payload["prompt"]
    assert "Do not redesign" in payload["prompt"]
    assert "Show rear fasteners" in payload["prompt"]


def test_two_reference_prompt_never_claims_full_character_context():
    references = ComponentReferences(
        component_cutout=b"shoe",
        binary_mask=b"mask",
        crop_box=(0, 0, 1, 1),
        source_size=(1, 1),
    )
    payload = build_component_payload(
        references,
        component_name="Shoe",
        extra_instructions="",
        params=None,
        image_name="shoe_detail",
        views_per_component=2,
    )

    assert len(payload["reference_images_b64"]) == 2
    assert payload["params"]["number_of_images"] == 2
    assert payload["reference_image_roles"] == [
        "component_cutout",
        "selection_mask",
    ]
    assert "Reference image 1 is the only target appearance" in payload["prompt"]
    assert "hard spatial constraint" in payload["prompt"]
    assert "Never render the mask" in payload["prompt"]
    assert "full character" not in payload["prompt"]


def test_component_names_are_safe_and_prompt_text_is_normalised():
    assert component_output_name("Hero Sheet.PNG", "Left / Hand Armor") == (
        "Hero_Sheet_Left_Hand_Armor_detail"
    )
    prompt = build_component_detail_prompt(
        "  Left\nGauntlet ",
        "  retain   scratches ",
        include_full_context=False,
    )
    assert "Left Gauntlet" in prompt
    assert "retain scratches" in prompt


def test_generation_defaults_to_strict_cutout_only_guidance():
    operator = (
        MOODBOARD / "ui/operators/character_component_ops.py"
    ).read_text(encoding="utf-8")
    properties = (
        MOODBOARD / "ui/moodboard_character_component_props.py"
    ).read_text(encoding="utf-8")

    assert 'getattr(settings, "include_full_context", False)' in operator
    assert "include_full_context: BoolProperty" in properties
    assert "default=False" in properties


def test_persistent_ids_are_lazy_stable_and_distinct():
    item = SimpleNamespace(moodboard_item_id="")
    segment = SimpleNamespace(component_id="")

    item_id = ensure_moodboard_item_id(item)
    component_id = ensure_component_id(segment)

    assert len(item_id) == 32
    assert len(component_id) == 32
    assert item_id != component_id
    assert ensure_moodboard_item_id(item) == item_id
    assert ensure_component_id(segment) == component_id


def test_result_provenance_uses_job_handle_not_collection_order(monkeypatch):
    source = SimpleNamespace(moodboard_item_id="source-1")
    unrelated = SimpleNamespace(mixar_job_handle="other")
    output = SimpleNamespace(
        moodboard_item_id="",
        mixar_job_handle="job-7",
        component_role="REFERENCE",
        component_source_item_id="",
        component_source_segment_id="",
        component_name="",
    )
    scene = SimpleNamespace(mixie_moodboard_images=[unrelated, output, source])
    placed = []
    monkeypatch.setattr(
        COMPONENTS,
        "_place_component_outputs",
        lambda actual_scene, actual_source, entries: placed.append(
            (actual_scene, actual_source, entries)
        ),
    )

    count = stamp_component_outputs(
        scene,
        job_id="job-7",
        source_item_id="source-1",
        source_component_id="component-2",
        component_name="  Torso   Armor ",
    )

    assert count == 1
    assert output.component_role == "COMPONENT_DETAIL"
    assert output.component_source_item_id == "source-1"
    assert output.component_source_segment_id == "component-2"
    assert output.component_name == "Torso Armor"
    assert len(output.moodboard_item_id) == 32
    assert placed == [(scene, source, [(1, output)])]


try:
    from PIL import Image as _PIL_IMAGE
except ImportError:
    _PIL_IMAGE = None
PIL_AVAILABLE = isinstance(_PIL_IMAGE, ModuleType)


@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow is supplied by Blender")
def test_mask_crop_is_padded_aligned_and_lossless():
    from PIL import Image, ImageDraw

    source = Image.new("RGB", (100, 80), (10, 20, 30))
    mask = Image.new("L", (100, 80), 0)
    ImageDraw.Draw(mask).rectangle((30, 20, 49, 39), fill=255)
    source_data = BytesIO()
    mask_data = BytesIO()
    source.save(source_data, format="PNG")
    mask.save(mask_data, format="PNG")

    references = prepare_component_references(
        source_data.getvalue(),
        mask_data.getvalue(),
    )

    assert references.source_size == (100, 80)
    assert references.crop_box == (14, 4, 66, 56)
    assert references.full_source is not None
    with Image.open(BytesIO(references.binary_mask)) as decoded:
        assert decoded.size == (52, 52)
        assert set(decoded.getdata()) == {0, 255}
    with Image.open(BytesIO(references.component_cutout)) as decoded:
        assert decoded.size == (52, 52)
        assert decoded.getpixel((0, 0)) == CHARACTER_COMPONENT_BACKGROUND_RGB
        assert decoded.getpixel((20, 20)) == (10, 20, 30)


@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow is supplied by Blender")
def test_unselected_pixels_are_white_not_gray():
    """The cutout background is white everywhere the mask excludes.

    Both the node-card preview and the component_cutout reference sent to
    image gen come from this composite, so a non-white backdrop shows up in
    the UI and in every generated view.
    """
    from PIL import Image, ImageDraw

    source = Image.new("RGB", (100, 80), (10, 20, 30))
    mask = Image.new("L", (100, 80), 0)
    ImageDraw.Draw(mask).rectangle((30, 20, 49, 39), fill=255)
    source_data = BytesIO()
    mask_data = BytesIO()
    source.save(source_data, format="PNG")
    mask.save(mask_data, format="PNG")

    references = prepare_component_references(
        source_data.getvalue(),
        mask_data.getvalue(),
    )

    assert CHARACTER_COMPONENT_BACKGROUND_RGB == (255, 255, 255)
    with Image.open(BytesIO(references.component_cutout)) as decoded:
        # Every corner sits outside the selected rectangle.
        width, height = decoded.size
        corners = (
            (0, 0),
            (width - 1, 0),
            (0, height - 1),
            (width - 1, height - 1),
        )
        for corner in corners:
            assert decoded.getpixel(corner) == (255, 255, 255)


@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow is supplied by Blender")
def test_low_resolution_mask_crops_from_original_source_detail():
    from PIL import Image, ImageDraw

    source = Image.new("RGB", (800, 400), (40, 50, 60))
    mask = Image.new("L", (100, 50), 0)
    ImageDraw.Draw(mask).rectangle((40, 20, 49, 29), fill=255)
    source_data = BytesIO()
    mask_data = BytesIO()
    source.save(source_data, format="PNG")
    mask.save(mask_data, format="PNG")

    references = prepare_component_references(
        source_data.getvalue(),
        mask_data.getvalue(),
        include_full_context=False,
    )

    with Image.open(BytesIO(references.component_cutout)) as decoded:
        # The 42px mask crop maps back to 336 source pixels before capping.
        assert decoded.size == (336, 336)
    assert references.source_size == (800, 400)


@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow is supplied by Blender")
def test_stale_or_empty_masks_are_rejected():
    from PIL import Image

    def encoded(size, value):
        output = BytesIO()
        Image.new("L", size, value).save(output, format="PNG")
        return output.getvalue()

    source = encoded((100, 50), 50)
    with pytest.raises(ValueError, match="no longer aligns"):
        prepare_component_references(source, encoded((100, 100), 255))
    with pytest.raises(ValueError, match="contains no selected pixels"):
        prepare_component_references(source, encoded((100, 50), 0))


@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow is supplied by Blender")
def test_sam3_result_is_hard_clipped_to_original_lasso():
    from PIL import Image, ImageDraw

    refined = Image.new("L", (20, 20), 0)
    ImageDraw.Draw(refined).rectangle((2, 2, 17, 17), fill=255)
    guide = Image.new("L", (20, 20), 0)
    ImageDraw.Draw(guide).rectangle((8, 8, 12, 12), fill=255)
    refined_data = BytesIO()
    guide_data = BytesIO()
    refined.save(refined_data, format="PNG")
    guide.save(guide_data, format="PNG")

    constrained = constrain_refined_mask(
        refined_data.getvalue(), guide_data.getvalue()
    )

    with Image.open(BytesIO(constrained)) as decoded:
        assert decoded.getpixel((3, 3)) == 0
        assert decoded.getpixel((10, 10)) == 255
        assert decoded.getbbox() == (8, 8, 13, 13)


def test_operator_uses_raw_mask_catalog_and_result_hook():
    source = (MOODBOARD / "ui/operators/character_component_ops.py").read_text(encoding="utf-8")

    for contract in (
        "segment.mask_image",
        "prepare_component_references",
        'job_type="image_gen"',
        "model_supports_component_details",
        "on_images_added=make_component_result_hook",
    ):
        assert contract in source
    assert "display_image" not in source
    assert "source_item.compressed_image" not in source
    assert "nano banana" not in source.lower()
    assert "gemini" not in source.lower()


def test_component_ui_exposes_names_independent_batching_and_lasso():
    drawer = (MOODBOARD / "ui/character_components_drawer.py").read_text(encoding="utf-8")
    toolbar = (MOODBOARD / "ui/moodboard_toolbar.py").read_text(encoding="utf-8")

    assert 'row.prop(segment, "name", text="")' in drawer
    assert 'row.prop(segment, "include_for_detail", text="")' in drawer
    assert drawer.count('"mixie.generate_character_components"') == 2
    assert 'excluded_params={"number_of_images"}' in drawer
    assert '"mixie.moodboard_lasso_tool"' in toolbar


def test_component_property_group_registers_before_its_owner():
    registration = (
        MOODBOARD / "ui/moodboard_scene_registration.py"
    ).read_text(encoding="utf-8")
    classes = registration[registration.index("classes = ("):]
    assert classes.index("MixieCharacterComponentSettings") < classes.index(
        "MixieMoodboardTabSegmentTo3DProps"
    )


def test_duplicate_keeps_component_provenance_but_not_identity():
    duplicate = (MOODBOARD / "ui/operators/transform_ops.py").read_text(encoding="utf-8")
    clipboard = (MOODBOARD / "core/moodboard_clipboard.py").read_text(encoding="utf-8")

    assert "new_img.component_role = orig_img.component_role" in duplicate
    assert "new_img.component_source_item_id" in duplicate
    assert "new_img.component_source_segment_id" in duplicate
    assert "new_img.moodboard_item_id =" not in duplicate
    for field in (
        '"component_role"',
        '"component_source_item_id"',
        '"component_source_segment_id"',
        '"component_name"',
    ):
        assert field in clipboard
    assert '"moodboard_item_id"' not in clipboard
