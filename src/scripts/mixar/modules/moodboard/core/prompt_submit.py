# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enter-to-generate dispatch for moodboard N-panel prompts.

Pressing plain Enter in a sidebar prompt field runs that tab's Generate, the
same way Enter in a canvas node prompt runs the node. The C++ text handler
(``interface_handlers.cc``) only identifies the situation — a ``prompt``
StringProperty in the MIXIE sidebar whose owner is not a graph node — and
forwards the owner PropertyGroup's RNA identifier here, so the routing lives
beside the drawers it mirrors instead of being frozen into C++.

Mode-routed tabs resolve through the SAME tables their footers draw from
(``_MODEL_GEN_FOOTER`` / ``_TEXTURE_GEN_FOOTER``), so Enter can never submit
through a different operator than the Generate button shows.

Every tab PropertyGroup that declares a ``prompt`` must have an entry in
``PROMPT_TAB_DISPATCH`` — pinned by ``tests/moodboard/test_prompt_enter_generate.py``.
"""

from __future__ import annotations


def _static(operator_id: str):
    def _resolve(_scene):
        return operator_id, None

    return _resolve


def _image_gen_operator(scene):
    """Text to Image submits imagegen; From Blockout routes to the lookdev flow.

    The From Blockout mode draws ``tab_lookdev``'s prompt (its own dispatch
    entry), but the mode is resolved here anyway so a future mode that reuses
    this tab's prompt keeps routing with its footer.
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import get_services, is_loaded
        from mixar.modules.common.generation_params import resolve_service_key

        tab = scene.mixie_moodboard_sidebar.tab_imagegen
        if is_loaded() and get_services("image_gen"):
            service_key = (
                resolve_service_key("image_gen", getattr(tab, "mode", ""))
                or "image_gen"
            )
            if service_key == "depth_to_image":
                return "mixie.lookdev_generate", None
    except Exception:
        pass
    return "mixie.imagegen_generate", None


def _texture_gen_operator(scene):
    """Mirror ``texture_gen_drawer``'s per-mode footer routing."""
    try:
        from mixar.modules.common.generation_params import resolve_service_key
        from mixar.modules.moodboard.ui.texture_gen_drawer import (
            _TEXTURE_GEN_FOOTER,
        )

        tab = scene.mixie_moodboard_sidebar.tab_lookdev360
        service_key = (
            resolve_service_key("texture_gen", getattr(tab, "mode", ""))
            or "pbr_gen"
        )
        operator_id, _feature = _TEXTURE_GEN_FOOTER.get(
            service_key, _TEXTURE_GEN_FOOTER["pbr_gen"]
        )
        return operator_id, None
    except Exception:
        return "mixie.lookdev360_generate", None


def _model_gen_operator(scene):
    """Mirror ``model_gen_drawer``'s per-mode footer routing.

    Catalog not loaded means the tab renders the legacy Basic fallback UI, so
    Enter follows its ``mixie.image_to_3d_generate`` button.
    """
    try:
        from mixar.modules.common.generation_params import resolve_service_key
        from mixar.modules.moodboard.ui.model_gen_drawer import (
            _MODEL_GEN_FOOTER,
            _model_gen_catalog_ready,
        )

        if _model_gen_catalog_ready():
            tab = scene.mixie_moodboard_sidebar.tab_image_to_3d
            service_key = (
                resolve_service_key("model_gen", getattr(tab, "mode", ""))
                or "model_3d"
            )
            _feature, _flag, operator_id = _MODEL_GEN_FOOTER.get(
                service_key, _MODEL_GEN_FOOTER["model_3d"]
            )
            return operator_id, None
    except Exception:
        pass
    return "mixie.image_to_3d_generate", None


# Owner PropertyGroup RNA identifier -> resolver(scene) -> (bl_idname, props).
# The owner identifies the tab because each tab's prompt lives on its own
# PropertyGroup; popup dialogs never reach this table (the C++ handler only
# fires for the sidebar UI region).
PROMPT_TAB_DISPATCH = {
    "MixieMoodboardTabImageGenProps": _image_gen_operator,
    "MixieMoodboardTabLookdevProps": _static("mixie.lookdev_generate"),
    "MixieMoodboardTabLookdev360Props": _texture_gen_operator,
    "MixieMoodboardTabPBRGenProps": _static("mixie.pbr_gen_generate"),
    "MixieMoodboardTabImageTo3DProps": _model_gen_operator,
    "MixieMoodboardTabMeshSegmentProps": _static("mixie.mesh_segment_submit"),
    "MixieMoodboardTabVideoGenProps": _static("mixie.video_gen_generate"),
    "MixieMoodboardTabWorldLabsProps": _static("mixie.world_labs_generate"),
    "MixieMoodboardTabSceneReconProps": _static("mixie.scene_recon_generate"),
}


def resolve_prompt_generate(scene, owner_type: str):
    """Resolve the generate operator behind a tab prompt's Enter press.

    Returns ``(bl_idname, props_dict_or_None)``, or ``(None, None)`` when the
    owner is unknown — Enter then simply confirms the text, never guesses a
    submit target.
    """
    resolver = PROMPT_TAB_DISPATCH.get(str(owner_type or ""))
    if resolver is None:
        return None, None
    try:
        return resolver(scene)
    except Exception:
        return None, None
