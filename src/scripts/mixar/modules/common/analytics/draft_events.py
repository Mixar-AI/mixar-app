# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Structure-only moodboard draft telemetry.

``moodboard.draft_abandoned`` reports that a user configured a generation
panel and left it without submitting. Snapshots are STRUCTURE ONLY by
design: enum values, booleans, counts and length buckets — never prompt
text, names, paths, or any string the user typed.

This module also owns the non-emitting ``note_generation_submitted()``
marker that replaced the client-side ``generation.submitted`` event (the
backend now emits that event at the job-queue submit endpoint).
"""

from __future__ import annotations

import time

from .capture import capture
from .constants import EVENT_DRAFT_ABANDONED

# capability -> monotonic timestamp of the last submit attempt.
_submitted_at: dict[str, float] = {}
# capability -> monotonic timestamp of when its panel became active.
_entered_at: dict[str, float] = {}
# capability -> frozen snapshot of the last draft_abandoned we emitted.
_last_emitted: dict[str, tuple] = {}

# Queue feature keys / service keys -> catalog capability. Unknown keys
# pass through unchanged so the marker still suppresses same-key checks.
_CAPABILITY_BY_FEATURE = {
    "imagegen": "image_gen",
    "model_3d": "model_gen",
    "image_to_3d_pro": "model_gen",
    "hunyuan_rapid": "model_gen",
    "lookdev360": "texture_gen",
    "lookdev": "texture_gen",
    "matgen": "texture_gen",
    "scene_gen": "scene_gen",
    "scene_gen_hp": "scene_gen",
    "scene_gen_lp": "scene_gen",
    "scene_recon": "scene_gen",
    "scene_gen_exp_labels": "scene_gen",
    "mesh_segment": "mesh_segmentation",
    "tripo_segment": "mesh_segmentation",
    "smart_segment": "mesh_segmentation",
    "hunyuan_part": "mesh_segmentation",
    "retopology": "retopology",
    "hunyuan_uv": "uv_unwrapping",
    "animate": "animate",
}

# Sidebar panel category (bl_category) -> catalog capability. Static
# fallback; ``capability_for_panel`` prefers the moodboard module's own
# label mapping when a catalog-driven build provides one.
_CAPABILITY_BY_PANEL = {
    "Image Gen": "image_gen",
    "AI Render": "ai_render",
    "Model Gen": "model_gen",
    "Texture Gen": "texture_gen",
    "Scene Gen": "scene_gen",
    "Character Parts": "character_parts",
    "PBR Generation": "pbr_generation",
    "Retopology": "retopology",
    "UV Unwrapping": "uv_unwrapping",
    "Mesh Segmentation": "mesh_segmentation",
    "Auto Rig": "animate",
    "Video Gen": "video_gen",
}

_KNOWN_CAPABILITIES = tuple(sorted(set(_CAPABILITY_BY_PANEL.values())))


def reset_draft_state() -> None:
    """Test hook."""
    _submitted_at.clear()
    _entered_at.clear()
    _last_emitted.clear()


def normalized_capability(key: str) -> str:
    return _CAPABILITY_BY_FEATURE.get(key, key)


def note_generation_submitted(feature_key_or_service: str) -> None:
    """Non-emitting marker: the user actually submitted a generation.

    The backend emits ``generation.submitted`` itself; this only feeds
    the "configured but never submitted" suppression for draft events.
    """
    try:
        now = time.monotonic()
        key = str(feature_key_or_service or "")
        if not key:
            return
        _submitted_at[key] = now
        _submitted_at[normalized_capability(key)] = now
    except Exception:
        pass


def note_panel_entered(capability: str) -> None:
    """Record entry into a generation panel (submitted-marker baseline)."""
    try:
        if capability:
            _entered_at[str(capability)] = time.monotonic()
    except Exception:
        pass


def capability_for_panel(category: str):
    """Map a sidebar panel category to its catalog capability, defensively."""
    if not category:
        return None
    try:
        # Catalog-driven builds expose the authoritative label mapping;
        # build the reverse map from it when available.
        from mixar.modules.moodboard.ui.moodboard_tab_labels import (
            get_tab_category,
        )
        for capability in _KNOWN_CAPABILITIES:
            if get_tab_category(capability, "") == category:
                return capability
    except Exception:
        pass
    return _CAPABILITY_BY_PANEL.get(category)


def _prompt_bucket(text) -> str:
    length = len(text) if isinstance(text, str) else 0
    if length == 0:
        return "0"
    if length <= 20:
        return "1-20"
    if length <= 100:
        return "21-100"
    return "100+"


def _common(capability: str, prompt) -> dict:
    return {
        "capability": capability,
        "has_prompt": bool(prompt),
        "prompt_length_bucket": _prompt_bucket(prompt or ""),
    }


def _snapshot_image_gen(sidebar, _scene) -> dict | None:
    tab = getattr(sidebar, "tab_imagegen", None)
    if tab is None:
        return None
    prompt = getattr(tab, "prompt", "") or ""
    reference_count = len(getattr(tab, "reference_images", ()) or ())
    if not prompt and reference_count == 0:
        return None
    props = _common("image_gen", prompt)
    props.update({
        "mode": str(getattr(tab, "mode", "") or ""),
        "model": str(getattr(tab, "model", "") or ""),
        "style": str(getattr(tab, "style", "") or ""),
        "aspect_ratio": str(getattr(tab, "aspect_ratio", "") or ""),
        "resolution": str(getattr(tab, "resolution", "") or ""),
        "use_reference_images": bool(getattr(tab, "use_reference_images", False)),
        "reference_image_count": reference_count,
    })
    return props


def _snapshot_model_gen(sidebar, scene) -> dict | None:
    tab = getattr(sidebar, "tab_image_to_3d", None)
    if tab is None:
        return None
    subtab = str(getattr(sidebar, "image_to_3d_subtab", "") or "")
    hunyuan = getattr(scene, "hunyuan", None)
    group = None
    if subtab == "PRO":
        group = getattr(hunyuan, "pro", None)
    elif subtab == "RAPID":
        group = getattr(hunyuan, "rapid", None)
    source = group if group is not None else tab
    prompt = getattr(source, "prompt", "") or ""
    reference = getattr(source, "image", None) if group is not None else (
        getattr(tab, "reference_image", None))
    if not prompt and reference is None:
        return None
    props = _common("model_gen", prompt)
    props.update({
        "mode": str(getattr(tab, "mode", "") or ""),
        "model": str(getattr(tab, "model", "") or ""),
        "subtab": subtab,
        "use_selected_image": bool(getattr(source, "use_selected_image", False)),
        "reference_image_attached": reference is not None,
    })
    if subtab == "PRO" and group is not None:
        props.update({
            "enable_pbr": bool(getattr(group, "enable_pbr", False)),
            "polygon_type": str(getattr(group, "polygon_type", "") or ""),
            "generate_type": str(getattr(group, "generate_type", "") or ""),
        })
    elif subtab == "RAPID" and group is not None:
        props.update({
            "enable_pbr": bool(getattr(group, "enable_pbr", False)),
            "result_format": str(getattr(group, "result_format", "") or ""),
        })
    return props


def _snapshot_texture_gen(sidebar, _scene) -> dict | None:
    tab = getattr(sidebar, "tab_lookdev360", None)
    if tab is None:
        return None
    prompt = getattr(tab, "prompt", "") or ""
    reference = getattr(tab, "reference_image", None)
    if not prompt and reference is None:
        return None
    props = _common("texture_gen", prompt)
    props.update({
        "mode": str(getattr(tab, "mode", "") or ""),
        "model": str(getattr(tab, "model", "") or ""),
        "image_type": str(getattr(tab, "image_type", "") or ""),
        "style_only": bool(getattr(tab, "style_only", False)),
        "resolution": str(getattr(tab, "resolution", "") or ""),
        "use_selected_image": bool(getattr(tab, "use_selected_image", False)),
        "reference_image_attached": reference is not None,
    })
    return props


def _snapshot_scene_gen(sidebar, _scene) -> dict | None:
    tab = getattr(sidebar, "tab_scene_recon", None)
    if tab is None:
        return None
    prompt = getattr(tab, "prompt", "") or ""
    if not prompt:
        return None
    props = _common("scene_gen", prompt)
    props.update({
        "mode": str(getattr(tab, "mode", "") or ""),
        "use_selected_image": bool(getattr(tab, "use_selected_image", False)),
        "generate_mesh": bool(getattr(tab, "generate_mesh", False)),
        "mesh_postprocess": bool(getattr(tab, "mesh_postprocess", False)),
        "texture_baking": bool(getattr(tab, "texture_baking", False)),
        "vertex_color": bool(getattr(tab, "vertex_color", False)),
        "save_to_library": bool(getattr(tab, "save_to_library", False)),
    })
    return props


def _snapshot_mesh_segmentation(sidebar, _scene) -> dict | None:
    tab = getattr(sidebar, "tab_mesh_segment", None)
    if tab is None:
        return None
    prompt = getattr(tab, "prompt", "") or ""
    expected_parts = getattr(tab, "expected_parts", "") or ""
    reference = getattr(tab, "ref_image", None)
    if not prompt and not expected_parts and reference is None:
        return None
    props = _common("mesh_segmentation", prompt)
    props.update({
        "mode": str(getattr(tab, "mode", "") or ""),
        "model": str(getattr(tab, "model", "") or ""),
        # Free-text field: only its presence is reported, never its value.
        "has_expected_parts": bool(expected_parts),
        "reference_image_attached": reference is not None,
    })
    return props


def _snapshot_pbr_generation(sidebar, _scene) -> dict | None:
    tab = getattr(sidebar, "tab_pbr_gen", None)
    if tab is None:
        return None
    prompt = getattr(tab, "prompt", "") or ""
    reference = getattr(tab, "reference_image", None)
    view_count = sum(
        1 for name in ("front_image", "left_image", "back_image", "right_image")
        if getattr(tab, name, None) is not None
    )
    if not prompt and reference is None and view_count == 0:
        return None
    props = _common("pbr_generation", prompt)
    props.update({
        "mode": str(getattr(tab, "mode", "") or ""),
        "model": str(getattr(tab, "model", "") or ""),
        "multi_view": bool(getattr(tab, "multi_view", False)),
        "style_only": bool(getattr(tab, "style_only", False)),
        "use_selected_image": bool(getattr(tab, "use_selected_image", False)),
        "reference_image_attached": reference is not None,
        "view_image_count": view_count,
    })
    return props


def _snapshot_video_gen(sidebar, _scene) -> dict | None:
    tab = getattr(sidebar, "tab_video_gen", None)
    if tab is None:
        return None
    prompt = getattr(tab, "prompt", "") or ""
    if not prompt:
        return None
    props = _common("video_gen", prompt)
    props.update({
        "mode": str(getattr(tab, "mode", "") or ""),
        "model": str(getattr(tab, "model", "") or ""),
    })
    return props


_SNAPSHOTTERS = {
    "image_gen": _snapshot_image_gen,
    "model_gen": _snapshot_model_gen,
    "texture_gen": _snapshot_texture_gen,
    "scene_gen": _snapshot_scene_gen,
    "mesh_segmentation": _snapshot_mesh_segmentation,
    "pbr_generation": _snapshot_pbr_generation,
    "video_gen": _snapshot_video_gen,
    # retopology / ai_render / uv_unwrapping / animate hold only catalog
    # mode+model enums (no user-entered content), so their drafts are
    # always "default" and never produce an abandonment snapshot.
    # character_parts is operator/list-driven (segmentation results → per-part
    # 3D) with no free-form draft state, so it is mapped for panel/dwell
    # tracking but deliberately has no snapshotter.
}


def snapshot_draft(context, capability: str) -> dict | None:
    """Structure-only draft snapshot; None when default/empty."""
    try:
        scene = getattr(context, "scene", None)
        sidebar = getattr(scene, "mixie_moodboard_sidebar", None)
        if sidebar is None:
            return None
        snapshotter = _SNAPSHOTTERS.get(capability)
        if snapshotter is None:
            return None
        return snapshotter(sidebar, scene)
    except Exception:
        return None


def capture_draft_abandoned(context, capability: str, dwell_seconds) -> None:
    """Emit ``moodboard.draft_abandoned`` for a panel the user just left.

    Suppressed when the draft is empty, when a generation was submitted
    since the panel was entered, or when it would repeat the immediately
    preceding snapshot for the same capability.
    """
    try:
        if not capability:
            return
        snapshot = snapshot_draft(context, capability)
        if snapshot is None:
            return
        entered = _entered_at.get(capability, 0.0)
        if _submitted_at.get(capability, -1.0) >= entered:
            return
        frozen = tuple(sorted(snapshot.items()))
        if _last_emitted.get(capability) == frozen:
            return
        _last_emitted[capability] = frozen
        properties = dict(snapshot)
        properties["dwell_seconds"] = int(max(0.0, float(dwell_seconds or 0.0)))
        capture(EVENT_DRAFT_ABANDONED, properties, context=context)
    except Exception:
        pass
