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

    Sources the unified generation catalog first; falls back to the legacy
    imagegen cache, then to hardcoded items (offline / pre-auth).
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_model_enum_items as get_catalog_model_items,
            is_loaded,
        )
        if is_loaded():
            items = get_catalog_model_items("image_gen")
            if items:
                return items
    except Exception:
        pass
    try:
        from mixar.bootstrap.imagegen_cache import get_model_enum_items
        items = get_model_enum_items(self, context)
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

    Sources the unified generation catalog first; falls back to the legacy
    imagegen cache, then to hardcoded items (offline / pre-auth).
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
    try:
        from mixar.bootstrap.imagegen_cache import get_style_enum_items
        items = get_style_enum_items(self, context)
        if items:
            return items
    except Exception:
        pass
    return [
        ("photorealistic", "Photorealistic", "Realistic style"),
        ("digital_art", "Digital Art", "Digital art style"),
    ]


def _get_imagegen_aspect_ratio_items(self, context):
    """Dynamic callback for aspect ratio enum items from cache."""
    try:
        from mixar.bootstrap.imagegen_cache import get_aspect_ratio_enum_items
        items = get_aspect_ratio_enum_items(self, context)
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
    """Dynamic callback for resolution enum items from cache."""
    try:
        from mixar.bootstrap.imagegen_cache import get_resolution_enum_items
        items = get_resolution_enum_items(self, context)
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
    """Dynamic callback for 3D model enum items from cache."""
    try:
        from mixar.bootstrap.model_3d_cache import get_model_enum_items
        return get_model_enum_items(self, context)
    except ImportError:
        return [
            ("trellis-1", "Trellis 1.0", "Trellis generation model"),
            ("meshy-6", "Meshy 6", "Meshy v6 generation model"),
        ]


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
