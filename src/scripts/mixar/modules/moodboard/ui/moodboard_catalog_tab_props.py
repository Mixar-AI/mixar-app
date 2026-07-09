# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalog-driven moodboard tab property groups.

Mode/Model selections for sidebar tabs converted to the generation
catalog (Stage 2b). Kept in a separate file so
``moodboard_tab_properties.py`` stays under the 500-line budget. These
groups only hold the catalog Mode (service) / Model (slug) enum
selections — the models' schema params live in the generation_params
engine's dynamic WindowManager groups, and any client-side flags that
aren't catalog params (e.g. Tripo "Bake Textures") stay on their
original property groups.

Registered by ``moodboard_scene_registration.py`` (its ``classes`` tuple
must list these before ``MixieMoodboardSidebarProperties``).
"""

from bpy.types import PropertyGroup
from bpy.props import EnumProperty

from .moodboard_enum_callbacks import (
    _on_model_changed,
    _get_ai_render_mode_items,
    _get_ai_render_model_items,
    _get_retopology_mode_items,
    _get_retopology_model_items,
    _get_uv_unwrap_model_items,
)


class MixieMoodboardTabRetopologyProps(PropertyGroup):
    """Properties for the Retopology tab (catalog mode/model selection)"""

    # Generation mode = catalog service of capability "retopology"
    # (Retopology = hunyuan / Retopology (Tripo) = retopology_tripo)
    mode: EnumProperty(
        name="Mode",
        description="Retopology engine",
        items=_get_retopology_mode_items,
        update=_on_model_changed,
    )

    model: EnumProperty(
        name="Model",
        description="AI model for retopology",
        items=_get_retopology_model_items,
        update=_on_model_changed,
    )


class MixieMoodboardTabAIRenderProps(PropertyGroup):
    """Properties for the AI Render tab (catalog mode/model selection).

    ``ai_render`` has a single service today (``depth_to_image``), so
    the Mode dropdown stays hidden; the enum exists so future services
    added to the capability in the DB surface without a client change.
    """

    mode: EnumProperty(
        name="Mode",
        description="AI Render mode",
        items=_get_ai_render_mode_items,
        update=_on_model_changed,
    )

    model: EnumProperty(
        name="Model",
        description="AI model for rendering",
        items=_get_ai_render_model_items,
        update=_on_model_changed,
    )


class MixieMoodboardTabUVUnwrapProps(PropertyGroup):
    """Properties for the UV Unwrap tab (catalog model selection).

    ``uv_unwrapping`` has a single service (``hunyuan_uv``), so there is
    no Mode enum — ``draw_capability_selector`` hides the Mode dropdown
    for single-service capabilities.
    """

    model: EnumProperty(
        name="Model",
        description="AI model for UV unwrapping",
        items=_get_uv_unwrap_model_items,
        update=_on_model_changed,
    )
