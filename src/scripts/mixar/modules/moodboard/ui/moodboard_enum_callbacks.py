# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Dynamic Enum Callbacks for Moodboard Properties

Callback functions used by EnumProperty items in moodboard property groups.
Separated from property definitions to keep moodboard_properties.py focused
on PropertyGroup class definitions.
"""


def _get_imagegen_model_items(self, context):
    """Dynamic callback for model enum items.

    Sources the unified generation catalog — models of the tab's
    currently selected mode (capability ``image_gen`` service, e.g.
    Text to Image = ``image_gen`` / From Blockout = ``depth_to_image``).
    Falls back to hardcoded items (offline / pre-auth).
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_model_enum_items as get_catalog_model_items,
            is_loaded,
        )
        from mixar.modules.common.generation_params import resolve_service_key
        if is_loaded():
            service_key = resolve_service_key(
                "image_gen", getattr(self, "mode", "")
            ) or "image_gen"
            items = get_catalog_model_items(service_key)
            if items:
                return items
    except Exception:
        pass
    return [
        ("flash", "Flash", "Fast generation"),
        ("pro", "Pro", "Higher quality generation"),
    ]


def _get_imagegen_style_items(self, context):
    """Dynamic callback for style enum items.

    Sources the unified generation catalog; falls back to hardcoded items
    (offline / pre-auth).
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_style_enum_items as get_catalog_style_items,
            is_loaded,
        )
        if is_loaded():
            items = get_catalog_style_items("image")
            if items:
                return items
    except Exception:
        pass
    return [
        ("photorealistic", "Photorealistic", "Realistic style"),
        ("digital_art", "Digital Art", "Digital art style"),
    ]


def _get_imagegen_aspect_ratio_items(self, context):
    """Dynamic callback for aspect ratio enum items.

    Sources the selected model's ``aspect_ratio`` schema param from the
    catalog; hardcoded fallback offline / pre-auth. (The dropdown itself
    is only drawn in the catalog-not-loaded fallback UI — when the
    catalog is loaded the param engine renders this param instead.)
    """
    try:
        from mixar.modules.common.generation_params import (
            get_param_enum_items, resolve_model_slug,
        )
        slug = resolve_model_slug("image_gen", getattr(self, "model", ""), "")
        if slug:
            items = get_param_enum_items("image_gen", slug, "aspect_ratio")
            if items:
                return items
    except Exception:
        pass
    return [
        ("1:1", "1:1", "Square"),
        ("16:9", "16:9", "Widescreen"),
        ("9:16", "9:16", "Portrait"),
    ]


def _get_imagegen_resolution_items(self, context):
    """Dynamic callback for resolution enum items.

    Sources the selected model's ``resolution`` schema param from the
    catalog; hardcoded fallback offline / pre-auth.
    """
    try:
        from mixar.modules.common.generation_params import (
            get_param_enum_items, resolve_model_slug,
        )
        slug = resolve_model_slug("image_gen", getattr(self, "model", ""), "")
        if slug:
            items = get_param_enum_items("image_gen", slug, "resolution")
            if items:
                return items
    except Exception:
        pass
    return [
        ("1K", "1K", "1024px"),
        ("2K", "2K", "2048px"),
    ]


def _on_model_changed(self, context):
    """Called when the model selection changes.

    Forces UI redraw so aspect_ratio and resolution dropdowns
    update their available options based on the new model.
    """
    if context and context.screen:
        for area in context.screen.areas:
            if area.type == "MIXIE":
                area.tag_redraw()


def _get_model_3d_items(self, context):
    """Dynamic callback for 3D model enum items.

    Sources the unified generation catalog (service ``model_3d``); falls
    back to hardcoded items (offline / pre-auth).
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_model_enum_items as get_catalog_model_items,
            is_loaded,
        )
        if is_loaded():
            items = get_catalog_model_items("model_3d")
            if items:
                return items
    except Exception:
        pass
    return [
        ("trellis-1", "Trellis 1.0", "Trellis generation model"),
        ("meshy-6", "Meshy 6", "Meshy v6 generation model"),
    ]


# ---------------------------------------------------------------------------
# Generic capability-driven callbacks (catalog-converted tabs)
# ---------------------------------------------------------------------------


def _capability_mode_items(capability_key, fallback):
    """Mode (service) enum items for a catalog capability.

    Sources the unified generation catalog; returns *fallback* when the
    catalog isn't loaded (offline / pre-auth).
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import is_loaded
        from mixar.modules.common.generation_params import (
            get_service_enum_items,
        )
        if is_loaded():
            items = get_service_enum_items(capability_key)
            if items:
                return items
    except Exception:
        pass
    return fallback


def _capability_model_items(capability_key, owner, fallback):
    """Model enum items for *owner*'s currently selected mode (service).

    Sources the unified generation catalog; returns *fallback* when the
    catalog isn't loaded (offline / pre-auth).
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_model_enum_items as get_catalog_model_items,
            is_loaded,
        )
        from mixar.modules.common.generation_params import resolve_service_key
        if is_loaded():
            service_key = resolve_service_key(
                capability_key, getattr(owner, "mode", "")
            )
            if service_key:
                items = get_catalog_model_items(service_key)
                if items:
                    return items
    except Exception:
        pass
    return fallback


def _get_image_gen_mode_items(self, context):
    """Image Gen tab mode items (capability ``image_gen``).

    Moodboard-surfaced services only (Text to Image = ``image_gen`` /
    From Blockout = ``depth_to_image``; the paint-surfaced ``brush_gen``
    never appears here). Falls back to the single Text to Image mode
    when the catalog isn't loaded (offline / pre-auth).
    """
    return _capability_mode_items(
        "image_gen",
        [("image_gen", "Text to Image",
          "Generate images from a text prompt")],
    )


def _get_texture_gen_mode_items(self, context):
    """Texture Gen tab mode items (capability ``texture_gen``)."""
    return _capability_mode_items(
        "texture_gen",
        [("pbr_gen", "PBR Textures",
          "Generate PBR texture maps for the selected mesh")],
    )


def _get_texture_gen_model_items(self, context):
    """Texture Gen tab model items (models of the selected mode)."""
    return _capability_model_items(
        "texture_gen", self,
        [("hunyuan-pbr", "Hunyuan PBR", "Hunyuan PBR texture generation")],
    )


def _get_animate_mode_items(self, context):
    """Animate tab mode items (capability ``animate``).

    Catalog-only tab (no offline fallback UI) — the fallback items only
    keep the enum valid while the catalog loads."""
    return _capability_mode_items(
        "animate",
        [("tripo_rig", "Auto Rig", "Auto-rig the selected mesh (Tripo)")],
    )


def _get_animate_model_items(self, context):
    """Animate tab model items (models of the selected mode)."""
    return _capability_model_items(
        "animate", self,
        [("tripo_rig_v2_5", "Tripo Auto Rig 2.5", "Tripo auto-rigging")],
    )


def _get_video_gen_mode_items(self, context):
    """Video Gen tab services; catalog-only with a loading-safe fallback."""
    return _capability_mode_items(
        "video_gen",
        [("video_gen", "Seedance", "Generate video from text and references")],
    )


def _get_video_gen_model_items(self, context):
    """Enabled Seedance models supplied by the generation catalog."""
    return _capability_model_items(
        "video_gen", self,
        [("seedance-2-0", "Seedance 2.0", "Seevio Seedance 2.0")],
    )


def _get_retopology_mode_items(self, context):
    """Retopology tab mode items (capability ``retopology``)."""
    return _capability_mode_items(
        "retopology",
        [("retopology", "Retopology", "Hunyuan AI retopology")],
    )


def _get_retopology_model_items(self, context):
    """Retopology tab model items (models of the selected mode)."""
    return _capability_model_items(
        "retopology", self,
        [("hunyuan_topology", "Hunyuan Topology", "Hunyuan AI retopology")],
    )


def _get_scene_gen_mode_items(self, context):
    """Scene Gen tab mode items (capability ``scene_gen``).

    Scene Reconstruction = ``scene_reconstruction`` / Segments to 3D =
    ``scene_gen``. Falls back to the single Scene Reconstruction mode
    when the catalog isn't loaded (offline / pre-auth).
    """
    return _capability_mode_items(
        "scene_gen",
        [("scene_reconstruction", "Scene Reconstruction",
          "Reconstruct a 3D scene from an image")],
    )


def _get_mesh_segment_mode_items(self, context):
    """Mesh Segment tab mode items (capability ``mesh_segmentation``)."""
    return _capability_mode_items(
        "mesh_segmentation",
        [("mesh_segment", "Mesh Segmentation",
          "Segment a UV-unwrapped mesh into labeled parts")],
    )


def _get_mesh_segment_model_items(self, context):
    """Mesh Segment tab model items (models of the selected mode)."""
    return _capability_model_items(
        "mesh_segmentation", self,
        [("mesh_segment_v1", "Mesh Segment v1", "UV mesh segmentation")],
    )


def _get_uv_unwrap_model_items(self, context):
    """UV Unwrap tab model items (capability ``uv_unwrapping``)."""
    return _capability_model_items(
        "uv_unwrapping", self,
        [("hunyuan_uv", "Hunyuan UV", "Hunyuan AI UV unwrapping")],
    )


def _get_ai_render_mode_items(self, context):
    """AI Render tab mode items (capability ``ai_render``).

    Catalog-only capability — the fallback is just the expected
    depth_to_image service (the tab's panel is hidden anyway whenever
    the catalog has no ai_render services).
    """
    return _capability_mode_items(
        "ai_render",
        [("depth_to_image", "From Blockout",
          "Render the current blockout scene with AI")],
    )


def _get_ai_render_model_items(self, context):
    """AI Render tab model items (models of the selected mode)."""
    return _capability_model_items(
        "ai_render", self,
        [("flux-depth-dev", "Flux Depth", "Depth-guided image generation")],
    )


def _get_model_gen_mode_items(self, context):
    """Dynamic callback for Model Gen mode (service) enum items.

    Sources the unified generation catalog (capability ``model_gen``);
    falls back to the single legacy model_3d mode (offline / pre-auth).
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import is_loaded
        from mixar.modules.common.generation_params import (
            get_service_enum_items,
        )
        if is_loaded():
            items = get_service_enum_items("model_gen")
            if items:
                return items
    except Exception:
        pass
    return [("model_3d", "Image to 3D", "Convert an image to a 3D model")]


def _get_model_gen_model_items(self, context):
    """Dynamic callback for Model Gen model enum items.

    Models of the currently selected mode (service) from the catalog;
    falls back to the legacy model_3d cache items (offline / pre-auth).
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_model_enum_items as get_catalog_model_items,
            is_loaded,
        )
        from mixar.modules.common.generation_params import resolve_service_key
        if is_loaded():
            service_key = resolve_service_key(
                "model_gen", getattr(self, "mode", "")
            )
            if service_key:
                items = get_catalog_model_items(service_key)
                if items:
                    return items
    except Exception:
        pass
    return _get_model_3d_items(self, context)
