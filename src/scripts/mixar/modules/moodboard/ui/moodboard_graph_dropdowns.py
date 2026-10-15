# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mode / Model dropdown callbacks of a moodboard inference card.

Split out of ``moodboard_graph_properties.py`` (500-line rule). The dropdowns
are dynamic enums whose persisted INDEX is fragile, so these callbacks keep
the saved slugs (``service_key_id`` / ``model_slug``) and the cached human
labels the C++ overlay draws in step with them. ``capability_for_action`` is
imported lazily: the properties module imports this one for its callbacks.
"""

from mixar.modules.common.i18n import iface_


def _capability_for_action(action_type):
    from .moodboard_graph_properties import capability_for_action

    return capability_for_action(action_type)


def _service_items(self, _context):
    try:
        from mixar.modules.common.generation_params import get_service_enum_items
        from mixar.modules.moodboard.core.node_schema import services_for_action

        items = get_service_enum_items(_capability_for_action(self.action_type))
        if self.action_type == 'MODEL_3D':
            keyed = [{"key": item[0], "item": item} for item in items]
            filtered = services_for_action(self.action_type, keyed)
            return [service["item"] for service in filtered] or [
                ('NONE', "Unavailable", "No supported 3D service is available")
            ]
        if self.action_type == 'MASK_DETAIL':
            # Detail generation runs on the plain image_gen service only.
            filtered = [item for item in items if item[0] == 'image_gen']
            return filtered or items
        if self.action_type == 'MESH_SEGMENT':
            # The mesh node imports segmented part meshes (Part decomposition),
            # not the vertex-group segmenter.
            filtered = [item for item in items if item[0] == 'hunyuan_part']
            return filtered or items
        return items
    except Exception:
        return [('LOADING', "Loading...", "Fetching generation catalog")]


def _model_items(self, _context):
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model_enum_items

        items = get_model_enum_items(self.service_key)
        if self.action_type == 'MASK_DETAIL':
            # Only models advertising mask guidance + two references can detail
            # a cutout/mask pair; fail closed rather than offer an invalid model.
            from mixar.bootstrap.generation_catalog_cache import get_models
            from mixar.modules.moodboard.core.character_components import (
                eligible_component_model_slugs,
            )

            eligible = eligible_component_model_slugs(get_models(self.service_key))
            filtered = [item for item in items if item[0] in eligible]
            return filtered or [(
                'NONE',
                "No compatible models",
                "Image models must advertise mask guidance and two references",
            )]
        return items
    except Exception:
        return [('LOADING', "Loading...", "Fetching generation catalog")]


# The Mode/Model/enum dropdowns are dynamic enums that persist a fragile INDEX,
# so Blender cannot reliably resolve them back to a name at draw time and blanks
# the menu. The C++ node overlay therefore shows a Python-cached human label
# instead, derived from the saved slug (service/model) or choices (params).
def _service_label_for_slug(action_type, service_key) -> str:
    if not service_key:
        return ""
    try:
        from mixar.modules.common.generation_params import get_service_enum_items

        for item in get_service_enum_items(_capability_for_action(action_type)):
            if item and item[0] == service_key:
                return str(item[1])
    except Exception:
        pass
    return str(service_key)


def _model_label_for_slug(service_key, model_slug) -> str:
    if not model_slug:
        return ""
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model_enum_items

        for item in get_model_enum_items(service_key):
            if item and item[0] == model_slug:
                return str(item[1])
    except Exception:
        pass
    return str(model_slug)


def refresh_node_dropdown_labels(node) -> None:
    """Cache the Mode/Model dropdown labels (read by the C++ node overlay)."""
    node.service_label = _service_label_for_slug(node.action_type, node.service_key_id)
    node.model_label = _model_label_for_slug(node.service_key_id, node.model_slug)
    if node.action_type == 'ASSEMBLE':  # local: the settings button opens its part rows
        node.service_label, node.model_label = "", iface_("Attachment settings")


_SUPPRESS_ENUM_MIRROR = False


def suppress_enum_mirror(enabled: bool) -> None:
    """Let restore paths write the dropdowns without clobbering saved slugs.

    Assigning ``service_key`` normally means "the user picked a new mode", which
    resets the model to that service's default. Replaying a *saved* selection
    back into the transient enums must not trigger that reset.
    """
    global _SUPPRESS_ENUM_MIRROR
    _SUPPRESS_ENUM_MIRROR = enabled


def _service_changed(self, _context):
    """A model identifier only has meaning within its selected service."""
    if _SUPPRESS_ENUM_MIRROR:
        return
    self.service_key_id = str(self.service_key or "")
    self.service_label = _service_label_for_slug(self.action_type, self.service_key)
    try:
        from mixar.bootstrap.generation_catalog_cache import get_default_model_slug

        self.model = get_default_model_slug(self.service_key) or ""
    except Exception:
        self.model = ""


def _model_changed(self, context):
    if _SUPPRESS_ENUM_MIRROR:
        return
    self.model_slug = str(self.model or "")
    self.model_label = _model_label_for_slug(self.service_key_id, self.model)
    if context is None or getattr(context, "scene", None) is None:
        return
    try:
        from mixar.modules.moodboard.core.node_schema import sync_node_schema

        sync_node_schema(context.scene, self)
    except Exception:
        pass
