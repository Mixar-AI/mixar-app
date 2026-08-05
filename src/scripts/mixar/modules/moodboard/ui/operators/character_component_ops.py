# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generate standalone detail images from named SAM3 moodboard masks."""

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _packed_image_bytes(image):
    """Return original packed bytes when available, without re-encoding pixels."""
    try:
        packed = image.packed_file
        if packed and packed.data:
            data = bytes(packed.data)
            return data or None
    except Exception:
        pass
    return None


def _source_item(scene, requested_index):
    items = scene.mixie_moodboard_images
    if 0 <= requested_index < len(items):
        item = items[requested_index]
        return requested_index, item if item.image else None
    for index, item in enumerate(items):
        if item.selected and item.image:
            return index, item
    return -1, None


class MIXIE_OT_generate_character_components(Operator):
    """Create one catalog-driven detail image for each requested SAM3 mask."""

    bl_idname = "mixie.generate_character_components"
    bl_label = "Generate Component Details"
    bl_description = (
        "Use the source image and SAM3 masks to create standalone component references"
    )
    bl_options = {'REGISTER'}

    image_index: IntProperty(default=-1)
    # A non-negative value generates one row even when its batch checkbox is off.
    segment_index: IntProperty(default=-1)

    def execute(self, context):
        from mixar.bootstrap.generation_catalog_cache import (
            get_model,
            is_loaded,
        )
        from mixar.modules.common.generation_params import collect_params
        from mixar.modules.common.job_queue import enqueue_generation
        from mixar.modules.common.job_queue.constants import FEATURE_IMAGEGEN
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
            mark_enqueued,
        )
        from mixar.modules.common.utils.image_utils import image_to_png_bytes
        from mixar.modules.moodboard.constants import (
            CHARACTER_COMPONENT_FULL_CONTEXT_REFERENCES,
        )
        from mixar.modules.moodboard.core.character_components import (
            build_component_payload,
            component_output_name,
            decode_component_source,
            ensure_component_id,
            ensure_moodboard_item_id,
            make_component_result_hook,
            model_reference_limit,
            model_supports_component_details,
            prepare_component_references,
        )
        from mixar.modules.moodboard.core.imagegen_queue import (
            get_imagegen_listener,
        )

        scene = context.scene
        image_index, source_item = _source_item(scene, self.image_index)
        if source_item is None:
            self.report({'ERROR'}, "Select a moodboard image with SAM3 components")
            return {'CANCELLED'}

        segments = source_item.segments
        if self.segment_index >= 0:
            if self.segment_index >= len(segments):
                self.report({'ERROR'}, "That component no longer exists")
                return {'CANCELLED'}
            targets = [(self.segment_index, segments[self.segment_index])]
        else:
            targets = [
                (index, segment)
                for index, segment in enumerate(segments)
                if segment.include_for_detail and segment.mask_image
            ]
        targets = [entry for entry in targets if entry[1].mask_image]
        if not targets:
            self.report({'ERROR'}, "No included components have a SAM3 mask")
            return {'CANCELLED'}

        settings = (
            scene.mixie_moodboard_sidebar.tab_segment_to_3d.character_components
        )
        views_per_component = getattr(settings, "views_per_component", 1)
        model_slug = str(settings.model or "")
        if not is_loaded():
            self.report({'ERROR'}, "Load the generation catalog before generating details")
            return {'CANCELLED'}
        model = get_model("image_gen", model_slug)
        if not model_supports_component_details(model):
            self.report(
                {'ERROR'},
                "Choose an Image Gen model with mask guidance and two references",
            )
            return {'CANCELLED'}

        reference_limit = model_reference_limit(model)
        include_full_context = (
            bool(getattr(settings, "include_full_context", False))
            and reference_limit >= CHARACTER_COMPONENT_FULL_CONTEXT_REFERENCES
        )
        params = collect_params("image_gen", model_slug)
        # The SAM3 mask may be 2K, but the crop helper maps it onto the
        # original before resizing. Starting from the cached SAM upload would
        # permanently discard detail in small parts of a large character sheet.
        source_image = source_item.image
        try:
            packed_source = _packed_image_bytes(source_image)
            source_bytes = packed_source or image_to_png_bytes(source_image)
        except Exception as exc:
            self.report({'ERROR'}, f"Could not read the component source: {exc}")
            return {'CANCELLED'}

        source_item_id = ensure_moodboard_item_id(source_item)
        if source_item.component_role == 'NONE':
            source_item.component_role = 'REFERENCE'
        source_name = source_item.image.name
        enqueued = 0
        failures = []
        try:
            decoded_source = decode_component_source(source_bytes)
        except Exception as exc:
            if packed_source is not None:
                try:
                    source_bytes = image_to_png_bytes(source_image)
                    decoded_source = decode_component_source(source_bytes)
                except Exception as fallback_exc:
                    self.report(
                        {'ERROR'},
                        f"Could not decode the component source: {fallback_exc}",
                    )
                    return {'CANCELLED'}
            else:
                self.report({'ERROR'}, f"Could not decode the component source: {exc}")
                return {'CANCELLED'}
        encoded_full_source = None
        for _index, segment in targets:
            component_name = str(segment.name or "Component").strip() or "Component"
            try:
                mask_bytes = (
                    _packed_image_bytes(segment.mask_image)
                    or image_to_png_bytes(segment.mask_image)
                )
                references = prepare_component_references(
                    source_bytes,
                    mask_bytes,
                    include_full_context=include_full_context,
                    decoded_source=decoded_source,
                    encoded_full_source=encoded_full_source,
                )
                if encoded_full_source is None:
                    encoded_full_source = references.full_source
                output_name = component_output_name(source_name, component_name)
                payload = build_component_payload(
                    references,
                    component_name=component_name,
                    extra_instructions=settings.instructions,
                    params=params,
                    image_name=output_name,
                    views_per_component=views_per_component,
                )
                component_id = ensure_component_id(segment)
                job = enqueue_generation(
                    kind="image",
                    feature_key=FEATURE_IMAGEGEN,
                    job_type="image_gen",
                    model=model_slug,
                    payload=payload,
                    label=f"CharacterComponent:{source_item_id}:{component_id}",
                    display_label=f"{component_name} detail",
                    # This composite workflow is surfaced by the Scene Gen
                    # N-panel but submits to the Image Gen backend service.
                    origin_capability_key="scene_gen",
                    fail_message=f"Could not generate {component_name} detail",
                    name_prefix="component_detail",
                    prompt_text=payload["prompt"],
                    undo_message="Generate Character Component",
                    base_name=output_name,
                    on_images_added=make_component_result_hook(
                        source_item_id=source_item_id,
                        source_component_id=component_id,
                        component_name=component_name,
                    ),
                    listener=get_imagegen_listener(),
                )
                if job is None:
                    failures.append(f"{component_name} is already queued")
                    continue
                enqueued += 1
            except Exception as exc:
                logger.warning(
                    "Character component enqueue failed image=%s component=%s: %s",
                    image_index,
                    component_name,
                    exc,
                )
                failures.append(f"{component_name}: {exc}")

        if enqueued:
            mark_enqueued(FEATURE_IMAGEGEN)
            if failures:
                self.report(
                    {'WARNING'},
                    f"Queued {enqueued} component(s); {len(failures)} skipped",
                )
            else:
                self.report({'INFO'}, f"Queued {enqueued} component detail image(s)")
            return {'FINISHED'}

        detail = failures[0] if failures else "No component jobs were accepted"
        self.report({'ERROR'}, detail[:240])
        return {'CANCELLED'}


classes = (MIXIE_OT_generate_character_components,)
