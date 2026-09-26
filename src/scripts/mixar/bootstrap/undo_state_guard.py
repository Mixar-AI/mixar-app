# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Undo/redo guard for transient runtime UI state.

Blender's global undo snapshots undo-tracked datablocks (Scene, Object, ...)
but NOT the WindowManager. Several Mixar runtime/status flags live on the Scene
because the native C++ UI reads them there via RNA (e.g. mixie_chat_is_busy,
mixie_*_is_generating in the chat footer / scene-recon tab) — so they cannot
simply move to the WindowManager without C++ changes + a rebuild.

The symptom: Ctrl+Z reverts these transient flags to an old snapshot value, so
the agent-bubble status pill flips back to "running", generation footers show a
stale spinner, etc.

Fix without moving anything: snapshot the flags' CURRENT (true) values just
before an undo/redo, and restore them right after. The value immediately before
the operation is the live runtime value, so this makes the flags undo-invariant
while leaving them on the Scene (C++ keeps working). Only transient status is
guarded — never document data the user edits.
"""

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Explicit transient flags to guard (chat/bubble state + per-feature status
# strings that don't follow the *_is_generating / *_is_processing pattern).
_EXPLICIT_PROPS = (
    # Agent chat / bubble status (drives the bubble status pill + C++ footer)
    "mixie_chat_state",
    "mixie_chat_is_busy",
    "mixie_chat_user_has_engaged",
    "mixar_bubble_history_lines",
    "mixar_bubble_history_active_index",
    # Per-feature transient error / status strings
    "mixie_imagegen_error",
    "mixie_lookdev_error",
    "mixie_lookdev360_error",
    "mixie_image_to_3d_error",
    "mixie_scene_recon_error",
    "mixie_mesh_segment_status",
    "mixie_mesh_segment_progress",
    "mixie_mesh_segment_current_step",
    "mixie_mesh_segment_job_id",
    "mixie_mesh_segment_error",
)

# Any Scene property with one of these suffixes is treated as a transient
# in-flight flag and guarded automatically (covers all current + future
# mixie_*_is_generating / *_is_processing flags without hardcoding each).
_TRANSIENT_SUFFIXES = ("_is_generating", "_is_processing")

# scene.name -> {prop_name: value} captured just before an undo/redo.
_snapshot: dict = {}


def _guarded_prop_names() -> set:
    """All transient Scene-prop names to guard (explicit + dynamic by suffix)."""
    names = set(_EXPLICIT_PROPS)
    try:
        for prop in bpy.types.Scene.bl_rna.properties:
            ident = prop.identifier
            if ident.startswith("mixie_") and ident.endswith(_TRANSIENT_SUFFIXES):
                names.add(ident)
    except Exception:
        pass
    return names


def _capture() -> None:
    """Snapshot the true (live) value of every guarded flag, per scene."""
    _snapshot.clear()
    names = _guarded_prop_names()
    for scene in bpy.data.scenes:
        vals = {}
        for name in names:
            if hasattr(scene, name):
                try:
                    vals[name] = getattr(scene, name)
                except Exception:
                    pass
        if vals:
            _snapshot[scene.name] = vals


def _restore() -> None:
    """Re-apply the snapshotted values that undo/redo may have reverted."""
    changed = False
    for scene in bpy.data.scenes:
        vals = _snapshot.get(scene.name)
        if not vals:
            continue
        for name, value in vals.items():
            try:
                if getattr(scene, name, None) != value:
                    setattr(scene, name, value)
                    changed = True
            except Exception:
                pass
    if changed:
        _tag_redraw()


def _tag_redraw() -> None:
    """Force a UI refresh so the restored values reach the pill / C++ footer."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


@persistent
def _on_pre(*_args) -> None:
    _capture()


@persistent
def _on_post(*_args) -> None:
    _restore()


def register() -> None:
    h = bpy.app.handlers
    for name in ("undo_pre", "redo_pre"):
        lst = getattr(h, name)
        if _on_pre not in lst:
            lst.append(_on_pre)
    for name in ("undo_post", "redo_post"):
        lst = getattr(h, name)
        if _on_post not in lst:
            lst.append(_on_post)
    logger.debug("undo_state_guard registered")


def unregister() -> None:
    h = bpy.app.handlers
    for name in ("undo_pre", "redo_pre"):
        lst = getattr(h, name)
        if _on_pre in lst:
            lst.remove(_on_pre)
    for name in ("undo_post", "redo_post"):
        lst = getattr(h, name)
        if _on_post in lst:
            lst.remove(_on_post)
    _snapshot.clear()
