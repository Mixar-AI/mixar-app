# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the Refine button is refining FOR.

A prompt box does not say what it is a prompt for, and the backend keys its
refinement instructions on exactly that: what makes a good image prompt
(lens, lighting, composition) is not what makes a good video prompt (motion,
camera movement) or a good mesh prompt (silhouette, material, scale). So
every Refine click has to arrive carrying the GENERATION service key and
model slug of the field it came from.

There are two kinds of prompt field and they resolve differently:

- a canvas inference node already stores its own ``service_key_id`` and
  ``model_slug`` — the node IS the target;
- a sidebar tab stores a mode enum and a model enum, which resolve to a
  service and a slug through the SAME catalog helpers the tab's own Mode and
  Model dropdowns draw from (``resolve_service_key``/``resolve_model_slug``).
  Resolving them any other way would let Refine refine for one model while
  the Generate button below it submits to another.

``SIDEBAR_PROMPT_TARGETS`` is keyed on the owner PropertyGroup's RNA
identifier, the same handle ``prompt_submit.PROMPT_TAB_DISPATCH`` uses for
Enter-to-generate, because each tab's prompt lives on its own PropertyGroup.
A tab that is missing from the table simply gets no Refine button — the
feature never guesses a target, since refining an image prompt as if it were
a video prompt is worse than not refining at all. Pinned by
``tests/moodboard/test_prompt_refine.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SidebarPromptTarget:
    """Where one sidebar prompt lives and what it generates."""

    # Data path from the Scene to the PropertyGroup owning ``prompt``.
    path: str
    # Catalog capability whose mode/model dropdowns this tab draws, or "" for
    # a tab with no catalog selector.
    capability: str = ""
    # Service used when the catalog cannot answer (not loaded, capability
    # disabled) and for tabs with no mode dropdown at all. "" is legal: the
    # backend refines through its default profile.
    fallback_service: str = ""
    mode_prop: str = "mode"
    model_prop: str = "model"


SIDEBAR_PROMPT_TARGETS: dict[str, SidebarPromptTarget] = {
    "MixieMoodboardTabImageGenProps": SidebarPromptTarget(
        "mixie_moodboard_sidebar.tab_imagegen",
        capability="image_gen",
        fallback_service="image_gen",
    ),
    # AI Render / From Blockout. One service, no mode dropdown — the depth
    # pass fixes the composition, so its refinement guidance is unlike any
    # other image prompt's.
    "MixieMoodboardTabLookdevProps": SidebarPromptTarget(
        "mixie_moodboard_sidebar.tab_lookdev",
        capability="ai_render",
        fallback_service="depth_to_image",
    ),
    "MixieMoodboardTabLookdev360Props": SidebarPromptTarget(
        "mixie_moodboard_sidebar.tab_lookdev360",
        capability="texture_gen",
        fallback_service="pbr_gen",
    ),
    "MixieMoodboardTabPBRGenProps": SidebarPromptTarget(
        "mixie_moodboard_sidebar.tab_pbr_gen",
        capability="pbr_generation",
        fallback_service="tripo_texture",
    ),
    "MixieMoodboardTabImageTo3DProps": SidebarPromptTarget(
        "mixie_moodboard_sidebar.tab_image_to_3d",
        capability="model_gen",
        fallback_service="model_3d",
    ),
    "MixieMoodboardTabMeshSegmentProps": SidebarPromptTarget(
        "mixie_moodboard_sidebar.tab_mesh_segment",
        capability="mesh_segment",
        fallback_service="mesh_segment",
    ),
    "MixieMoodboardTabVideoGenProps": SidebarPromptTarget(
        "mixie_moodboard_sidebar.tab_video_gen",
        capability="video_gen",
        fallback_service="video_gen",
    ),
    # Video Upscale. Its prompt steers the upscaler's guidance the same way
    # Video Gen's steers generation, so Enter-to-submit and Refine must both
    # reach it -- test_every_enter_dispatchable_tab_can_also_refine pins that
    # the two tables stay in step.
    "MixieMoodboardTabVideoUpscaleProps": SidebarPromptTarget(
        "mixie_moodboard_sidebar.tab_video_upscale",
        capability="video_upscale",
        fallback_service="video_upscale",
    ),
    "MixieMoodboardTabWorldLabsProps": SidebarPromptTarget(
        "mixie_moodboard_sidebar.tab_world_labs",
        capability="world_labs",
        fallback_service="world_labs",
    ),
    "MixieMoodboardTabSceneReconProps": SidebarPromptTarget(
        "mixie_moodboard_sidebar.tab_scene_recon",
        fallback_service="scene_reconstruction",
    ),
    # Hunyuan Pro's prompt, drawn by the shared Hunyuan input drawer. It
    # submits as job_type "image_to_3d" (see generation_enqueue.enqueue_pro_job),
    # so it refines as one.
    "MixieHunyuanProProps": SidebarPromptTarget(
        "hunyuan.pro",
        fallback_service="image_to_3d",
    ),
}


def owner_type_of(prop_owner) -> str:
    """RNA identifier of a PropertyGroup, or "" when it cannot be read."""
    try:
        return prop_owner.bl_rna.identifier or ""
    except Exception:
        return ""


def resolve_owner(scene, target: SidebarPromptTarget):
    """Walk ``target.path`` from *scene*, or None if any hop is missing."""
    owner = scene
    for part in target.path.split("."):
        owner = getattr(owner, part, None)
        if owner is None:
            return None
    return owner


def sidebar_generation_target(
    scene, owner_type: str
) -> Optional[tuple[str, str]]:
    """``(service_key, model_slug)`` for a sidebar prompt, or None.

    None means this owner is not a refinable prompt field. An empty
    *model_slug* is normal — many tabs have no model dropdown, and the
    backend resolves the service's profile in that case.
    """
    target = SIDEBAR_PROMPT_TARGETS.get(owner_type or "")
    if target is None:
        return None

    owner = resolve_owner(scene, target)
    if owner is None:
        return None

    service_key = target.fallback_service
    model_slug = ""
    if target.capability:
        try:
            from mixar.modules.common.generation_params import (
                resolve_model_slug,
                resolve_service_key,
            )

            resolved = resolve_service_key(
                target.capability, getattr(owner, target.mode_prop, "")
            )
            if resolved:
                service_key = resolved
                model_slug = resolve_model_slug(
                    resolved, getattr(owner, target.model_prop, "")
                )
        except Exception:
            # Catalog not loaded or the tab has no such enum — the fallback
            # service still refines, through that service's own profile.
            pass

    return service_key, model_slug
