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

import bpy
from bpy.types import PropertyGroup
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty

from .moodboard_enum_callbacks import (
    _on_model_changed,
    _get_ai_render_mode_items,
    _get_ai_render_model_items,
    _get_animate_mode_items,
    _get_animate_model_items,
    _get_retopology_mode_items,
    _get_retopology_model_items,
    _get_uv_unwrap_model_items,
    _get_video_gen_mode_items,
    _get_video_gen_model_items,
    _get_world_labs_model_items,
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


class MixieMoodboardTabAnimateProps(PropertyGroup):
    """Properties for the Animate tab (catalog mode/model selection).

    Capability ``animate`` — Auto Rig (``tripo_rig``) / Animate
    (``tripo_retarget``). Catalog-only tab: like AI Render it has no
    offline fallback, so the panel hides when the catalog carries no
    animate services.
    """

    mode: EnumProperty(
        name="Mode",
        description="Animate mode (Auto Rig / Animate)",
        items=_get_animate_mode_items,
        update=_on_model_changed,
    )

    model: EnumProperty(
        name="Model",
        description="AI model for rigging/animation",
        items=_get_animate_model_items,
        update=_on_model_changed,
    )


class MixieMoodboardTabVideoGenProps(PropertyGroup):
    """Catalog-only Seedance video generation settings."""

    mode: EnumProperty(
        name="Mode",
        description="Video generation mode",
        items=_get_video_gen_mode_items,
        update=_on_model_changed,
    )

    model: EnumProperty(
        name="Model",
        description="Video generation model",
        items=_get_video_gen_model_items,
        update=_on_model_changed,
    )

    prompt: StringProperty(
        name="Prompt",
        description="Describe the video and how selected references should be used",
        default="",
        maxlen=4096,
        options={'TEXTEDIT_UPDATE'},
    )


class MixieMoodboardTabWorldLabsProps(PropertyGroup):
    """Catalog-authoritative World Labs world-generation settings."""

    model: EnumProperty(
        name="Model",
        description="World Labs model published by the generation catalog",
        items=_get_world_labs_model_items,
        update=_on_model_changed,
    )

    prompt: StringProperty(
        name="Prompt",
        description="Text description of the world or optional image refinement",
        default="",
        maxlen=2048,
        options={'TEXTEDIT_UPDATE'},
    )

    use_selected_image: BoolProperty(
        name="Use Selected Moodboard Image",
        description="ON: use the selected moodboard image; OFF: use an upload",
        default=True,
    )

    reference_image: PointerProperty(
        type=bpy.types.Image,
        name="Input Image",
        description="Uploaded image for World Labs image mode",
    )
