# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Character-component reference preparation and provenance.

SAM3 masks are stored as packed Blender images, but Image Gen currently has
no native mask field.  This module turns one mask into an ordered multimodal
reference set the existing ``image_gen`` service already understands:

* optional full-character context;
* a padded, neutral-background component cutout; and
* the lossless binary mask aligned to that cutout.

The helpers that manipulate encoded bytes are Blender-independent so the wire
contract and crop behavior can be tested in the standalone suite.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
import math
import re
import uuid
from typing import Iterable, Mapping, Optional

from ..constants import (
    CHARACTER_COMPONENT_ASPECT_TOLERANCE,
    CHARACTER_COMPONENT_BACKGROUND_RGB,
    CHARACTER_COMPONENT_CROP_PADDING,
    CHARACTER_COMPONENT_DETAIL_PROMPT,
    CHARACTER_COMPONENT_JPEG_QUALITY,
    CHARACTER_COMPONENT_MASK_THRESHOLD,
    CHARACTER_COMPONENT_MAX_REFERENCE_DIMENSION,
    CHARACTER_COMPONENT_MIN_PADDING_PX,
    CHARACTER_COMPONENT_REFERENCE_GUIDANCE,
    CHARACTER_COMPONENT_REFERENCE_ROLES,
    CHARACTER_COMPONENT_REQUIRED_REFERENCES,
    MOODBOARD_MULTI_IMAGE_GAP,
)


@dataclass(frozen=True)
class ComponentReferences:
    """Encoded references derived from one source/mask pair."""

    component_cutout: bytes
    binary_mask: bytes
    crop_box: tuple[int, int, int, int]
    source_size: tuple[int, int]
    full_source: Optional[bytes] = None

    def ordered(self) -> list[bytes]:
        """Return the exact provider-visible reference ordering."""
        references = []
        if self.full_source:
            references.append(self.full_source)
        references.extend((self.component_cutout, self.binary_mask))
        return references

    @property
    def has_full_context(self) -> bool:
        return self.full_source is not None


def model_reference_limit(model: Optional[Mapping]) -> int:
    """Return a catalog model's explicit reference limit, failing closed."""
    if not model:
        return 0
    value = model.get("max_reference_images")
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 0
    return max(limit, 0)


def model_supports_component_details(model: Optional[Mapping]) -> bool:
    """Whether *model* explicitly supports the required cutout/mask inputs."""
    if not model:
        return False
    if model.get("supports_mask_guidance") is not True:
        return False
    return model_reference_limit(model) >= CHARACTER_COMPONENT_REQUIRED_REFERENCES


def eligible_component_model_slugs(models: Iterable[Mapping]) -> set[str]:
    """Catalog slugs eligible for component-detail generation."""
    return {
        str(model.get("slug") or "")
        for model in models
        if model_supports_component_details(model) and model.get("slug")
    }


def _normalise_text(value: str) -> str:
    return " ".join(str(value or "").split())


def component_output_name(source_name: str, component_name: str) -> str:
    """Create a deterministic user-derived base name for the generated image."""
    source = _normalise_text(source_name) or "character"
    component = _normalise_text(component_name) or "component"
    source = re.sub(r"\.(png|jpe?g|webp|tiff?)$", "", source, flags=re.I)
    raw = f"{source}_{component}_detail"
    safe = re.sub(r"[^\w.-]+", "_", raw, flags=re.UNICODE).strip("._")
    return (safe or "character_component_detail")[:120]


def build_component_detail_prompt(
    component_name: str,
    extra_instructions: str = "",
    *,
    include_full_context: bool,
) -> str:
    """Build the preservation-focused prompt matching reference ordering."""
    name = _normalise_text(component_name) or "selected component"
    prompt = CHARACTER_COMPONENT_DETAIL_PROMPT.format(
        component_name=name,
        reference_guidance=CHARACTER_COMPONENT_REFERENCE_GUIDANCE[
            bool(include_full_context)
        ],
    )
    extra = _normalise_text(extra_instructions)
    if extra:
        prompt = f"{prompt} Additional user direction: {extra}"
    return prompt


def _aspect_ratio_delta(a: tuple[int, int], b: tuple[int, int]) -> float:
    aw, ah = a
    bw, bh = b
    if min(aw, ah, bw, bh) <= 0:
        return float("inf")
    ar_a = aw / ah
    ar_b = bw / bh
    return abs(ar_a - ar_b) / max(ar_a, ar_b)


def _fit_size(size: tuple[int, int], max_dimension: int) -> tuple[int, int]:
    width, height = size
    longest = max(width, height)
    if longest <= max_dimension:
        return width, height
    scale = max_dimension / longest
    return max(1, round(width * scale)), max(1, round(height * scale))


def _source_to_rgb(image):
    """Composite transparent source pixels onto a neutral background."""
    from PIL import Image

    rgba = image.convert("RGBA")
    rgb = Image.new("RGB", rgba.size, CHARACTER_COMPONENT_BACKGROUND_RGB)
    rgb.paste(rgba, mask=rgba.getchannel("A"))
    return rgb


def _encode_png(image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _encode_jpeg(image) -> bytes:
    output = BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=CHARACTER_COMPONENT_JPEG_QUALITY,
        optimize=True,
    )
    return output.getvalue()


def decode_component_source(source_bytes: bytes):
    """Decode one source image for reuse across every mask in a batch."""
    if not source_bytes:
        raise ValueError("The component source image is empty")
    from PIL import Image

    with Image.open(BytesIO(source_bytes)) as opened_source:
        return _source_to_rgb(opened_source)


def prepare_component_references(
    source_bytes: bytes,
    mask_bytes: bytes,
    *,
    include_full_context: bool = True,
    padding: float = CHARACTER_COMPONENT_CROP_PADDING,
    decoded_source=None,
    encoded_full_source: Optional[bytes] = None,
) -> ComponentReferences:
    """Create aligned full/cutout/mask references from encoded images.

    The SAM3 mask may be lower-resolution than the moodboard source. Its crop
    window is mapped onto the original before either crop is capped, preserving
    detail in small components. A changed aspect ratio is rejected because
    applying that stale mask would guide a paid generation toward the wrong
    component.
    """
    if not mask_bytes:
        raise ValueError("The component mask is empty")

    from PIL import Image

    source = (
        decoded_source
        if decoded_source is not None
        else decode_component_source(source_bytes)
    )
    with Image.open(BytesIO(mask_bytes)) as opened_mask:
        mask = opened_mask.convert("RGBA").getchannel("R")
    original_source_size = source.size

    if _aspect_ratio_delta(source.size, mask.size) > CHARACTER_COMPONENT_ASPECT_TOLERANCE:
        raise ValueError(
            "The SAM3 mask no longer aligns with its source image; "
            "create the component selection again"
        )

    binary = mask.point(
        lambda value: 255 if value >= CHARACTER_COMPONENT_MASK_THRESHOLD else 0,
        mode="L",
    )
    selection_box = binary.getbbox()
    if selection_box is None:
        raise ValueError("The SAM3 component mask contains no selected pixels")

    left, top, right, bottom = selection_box
    selected_width = right - left
    selected_height = bottom - top
    pad_x = max(CHARACTER_COMPONENT_MIN_PADDING_PX, round(selected_width * padding))
    pad_y = max(CHARACTER_COMPONENT_MIN_PADDING_PX, round(selected_height * padding))
    mask_crop_box = (
        max(0, left - pad_x),
        max(0, top - pad_y),
        min(mask.size[0], right + pad_x),
        min(mask.size[1], bottom + pad_y),
    )

    # Map only the selected mask window onto the original image. Expanding an
    # entire 2K SAM mask to an 8K character sheet wastes memory, while shrinking
    # the full sheet before cropping can turn a small shoe into a 100px input.
    scale_x = source.size[0] / mask.size[0]
    scale_y = source.size[1] / mask.size[1]
    crop_box = (
        max(0, math.floor(mask_crop_box[0] * scale_x)),
        max(0, math.floor(mask_crop_box[1] * scale_y)),
        min(source.size[0], math.ceil(mask_crop_box[2] * scale_x)),
        min(source.size[1], math.ceil(mask_crop_box[3] * scale_y)),
    )
    source_crop = source.crop(crop_box)
    mask_crop = binary.crop(mask_crop_box)
    if mask_crop.size != source_crop.size:
        mask_crop = mask_crop.resize(source_crop.size, Image.Resampling.NEAREST)

    crop_size = _fit_size(
        source_crop.size,
        CHARACTER_COMPONENT_MAX_REFERENCE_DIMENSION,
    )
    if source_crop.size != crop_size:
        source_crop = source_crop.resize(crop_size, Image.Resampling.LANCZOS)
        mask_crop = mask_crop.resize(crop_size, Image.Resampling.NEAREST)

    cutout = Image.new("RGB", source_crop.size, CHARACTER_COMPONENT_BACKGROUND_RGB)
    cutout.paste(source_crop, mask=mask_crop)

    full_source = encoded_full_source
    if include_full_context:
        if full_source is None:
            full_size = _fit_size(
                source.size,
                CHARACTER_COMPONENT_MAX_REFERENCE_DIMENSION,
            )
            full_image = source
            if source.size != full_size:
                full_image = source.resize(full_size, Image.Resampling.LANCZOS)
            full_source = _encode_jpeg(full_image)
    else:
        full_source = None

    return ComponentReferences(
        full_source=full_source,
        component_cutout=_encode_png(cutout),
        binary_mask=_encode_png(mask_crop),
        crop_box=crop_box,
        source_size=original_source_size,
    )


def build_component_payload(
    references: ComponentReferences,
    *,
    component_name: str,
    extra_instructions: str,
    params: Optional[Mapping],
    image_name: str,
    views_per_component: int = 1,
) -> dict:
    """Build the existing ``image_gen`` wire payload for one component."""
    ordered = references.ordered()
    if len(ordered) < CHARACTER_COMPONENT_REQUIRED_REFERENCES:
        raise ValueError("Component detail generation requires source and mask references")

    resolved_params = dict(params or {})
    try:
        # The image-generation queue currently accepts at most four outputs
        # per job; keep the component workflow within that service contract.
        resolved_views = max(1, min(int(views_per_component), 4))
    except (TypeError, ValueError):
        resolved_views = 1
    resolved_params["number_of_images"] = resolved_views
    prompt = build_component_detail_prompt(
        component_name,
        extra_instructions,
        include_full_context=references.has_full_context,
    )
    return {
        "prompt": prompt,
        "params": resolved_params,
        "reference_images_b64": [
            base64.b64encode(reference).decode("ascii") for reference in ordered
        ],
        "reference_image_roles": list(
            CHARACTER_COMPONENT_REFERENCE_ROLES[references.has_full_context]
        ),
        "image_name": image_name,
    }


def ensure_moodboard_item_id(item) -> str:
    """Return the persistent UUID of a moodboard entry, assigning it lazily."""
    current = str(getattr(item, "moodboard_item_id", "") or "").strip()
    if not current:
        current = uuid.uuid4().hex
        item.moodboard_item_id = current
    return current


def ensure_component_id(segment) -> str:
    """Return the persistent UUID of a SAM3 component, assigning it lazily."""
    current = str(getattr(segment, "component_id", "") or "").strip()
    if not current:
        current = uuid.uuid4().hex
        segment.component_id = current
    return current


def _place_component_outputs(scene, source_item, output_entries) -> None:
    """Place generated cards beside their source without overlapping the board."""
    try:
        from .moodboard_utils import (
            ensure_moodboard_region_visible,
            find_free_moodboard_position,
            get_moodboard_image_display_size,
        )

        source_width, source_height = get_moodboard_image_display_size(
            source_item.image, source_item.scale,
        )
        reveal_in_active_view = False
        try:
            import bpy

            reveal_in_active_view = bpy.context.scene == scene
        except Exception:
            pass
        for output_index, output in output_entries:
            width, height = get_moodboard_image_display_size(
                output.image, output.scale,
            )
            center_x = (
                source_item.position_x + source_width +
                MOODBOARD_MULTI_IMAGE_GAP + width / 2.0
            )
            center_y = source_item.position_y + source_height - height / 2.0
            output.position_x, output.position_y = find_free_moodboard_position(
                width,
                height,
                center_x,
                center_y,
                scene=scene,
                exclude_index=output_index,
            )
            if reveal_in_active_view:
                ensure_moodboard_region_visible(
                    output.position_x, output.position_y, width, height,
                )
    except Exception:
        # Provenance is the durable contract; placement is a best-effort UX.
        return


def stamp_component_outputs(
    scene,
    *,
    job_id: str,
    source_item_id: str,
    source_component_id: str,
    component_name: str,
) -> int:
    """Stamp and place moodboard images downloaded for a component job."""
    items = getattr(scene, "mixie_moodboard_images", ())
    source_item = next(
        (
            item for item in items
            if getattr(item, "moodboard_item_id", "") == source_item_id
        ),
        None,
    )
    output_entries = [
        (index, item)
        for index, item in enumerate(items)
        if getattr(item, "mixar_job_handle", "") == job_id
    ]
    for _index, item in output_entries:
        ensure_moodboard_item_id(item)
        item.component_role = 'COMPONENT_DETAIL'
        item.component_source_item_id = source_item_id
        item.component_source_segment_id = source_component_id
        item.component_name = _normalise_text(component_name)

    if source_item is not None and output_entries:
        _place_component_outputs(scene, source_item, output_entries)
    return len(output_entries)


def make_component_result_hook(
    *,
    source_item_id: str,
    source_component_id: str,
    component_name: str,
):
    """Return a lightweight image-job callback that restores provenance."""
    def _on_images_added(job, _image_names: str) -> None:
        import bpy

        scene = None
        try:
            scene = bpy.data.scenes.get(job.scene_name)
        except Exception:
            pass
        if scene is None:
            raise RuntimeError("Originating scene is unavailable for component result")
        stamped = stamp_component_outputs(
            scene,
            job_id=job.id,
            source_item_id=source_item_id,
            source_component_id=source_component_id,
            component_name=component_name,
        )
        if stamped == 0:
            raise RuntimeError("Component result was added without provenance")

    return _on_images_added
