# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene-state half of ``ScriptExecutor``: the before/after snapshot that
reports created / modified / deleted objects, and the Object-mode restore
that undoes an interaction-mode change a script left behind.
"""

from mixar.config.logging_config import get_logger

import bpy

from .animation_effects import animation_fingerprint, snapshot_properties_changed

logger = get_logger(__name__)


class SceneStateMixin:
    """Mixed into ``ScriptExecutor``; reads ``self._current_session``."""

    _current_session: str = ""

    @staticmethod
    def _interaction_mode() -> str:
        try:
            return str(bpy.context.mode or "")
        except Exception:  # noqa: BLE001
            return ""

    def _restore_object_mode(self, mode_before: str) -> bool:
        """Return to Object mode when a script changed the interaction mode.

        Only a script that STARTED in Object mode is undone this way: a user
        who was sculpting keeps their mode. Returns True when a mode_set ran.
        """
        if mode_before != "OBJECT":
            return False
        mode_after = self._interaction_mode()
        if not mode_after or mode_after == "OBJECT":
            return False
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Object mode restore skipped: %s", exc)
            return False
        try:
            from mixar.modules.common.scenes_log import slog
            slog("mode.restored", None, session_id=self._current_session, left_in=mode_after)
        except Exception:  # noqa: BLE001
            pass
        return True

    def _capture_scene_state(self) -> dict:
        """Capture current scene state for change detection."""
        state = {
            "objects": {},
            "materials": set(),
        }

        try:
            action_cache = {}
            for obj in bpy.data.objects:
                try:
                    animation = animation_fingerprint(obj, action_cache)
                except Exception as exc:
                    logger.warning("Animation snapshot unavailable for %s: %s", obj.name, exc)
                    animation = None
                state["objects"][obj.name] = {
                    "type": obj.type,
                    "location": tuple(obj.location),
                    "rotation": tuple(obj.rotation_euler),
                    "scale": tuple(obj.scale),
                    "material_count": (
                        len(obj.material_slots) if hasattr(obj, "material_slots") else 0
                    ),
                    "animation": animation,
                }
            state["materials"] = set(mat.name for mat in bpy.data.materials)

        except (AttributeError, RuntimeError) as e:
            logger.debug(f"Warning: Could not capture scene state: {e}")

        return state

    def _detect_changes(self, before: dict, after: dict) -> dict:
        """Detect what changed between two scene states."""
        before_objects = set(before.get("objects", {}).keys())
        after_objects = set(after.get("objects", {}).keys())

        created = list(after_objects - before_objects)
        deleted = list(before_objects - after_objects)

        modified = []
        for obj_name in before_objects & after_objects:
            before_props = before["objects"].get(obj_name, {})
            after_props = after["objects"].get(obj_name, {})
            if snapshot_properties_changed(before_props, after_props):
                modified.append(obj_name)

        return {
            "created": created,
            "modified": modified,
            "deleted": deleted,
        }
