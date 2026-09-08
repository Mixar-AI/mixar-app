# SPDX-License-Identifier: GPL-3.0-or-later
"""Preserve first-party handlers and remove transient script-installed handlers."""

import bpy
from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class ScriptHandlers:
    # Handler list names on bpy.app.handlers to snapshot/restore
    _HANDLER_NAMES = (
        "depsgraph_update_post",
        "depsgraph_update_pre",
        "frame_change_post",
        "frame_change_pre",
        "load_factory_preferences_post",
        "load_factory_startup_post",
        "load_post",
        "load_pre",
        "object_bake_cancel",
        "object_bake_complete",
        "object_bake_pre",
        "redo_post",
        "redo_pre",
        "render_cancel",
        "render_complete",
        "render_init",
        "render_post",
        "render_pre",
        "render_stats",
        "render_write",
        "save_post",
        "save_pre",
        "undo_post",
        "undo_pre",
        "version_update",
    )

    def _snapshot_handlers(self) -> dict[str, list]:
        """Snapshot all bpy.app.handlers lists before script execution."""
        snapshot = {}
        for name in self._HANDLER_NAMES:
            handler_list = getattr(bpy.app.handlers, name, None)
            if handler_list is not None:
                snapshot[name] = list(handler_list)
        return snapshot

    @staticmethod
    def _exempt_handler_ids() -> set:
        """Identities of first-party handlers that scripts install INDIRECTLY
        via addon operators and that must OUTLIVE the script.

        mixie_chat.agent_final_render starts a background render job during a
        sandboxed render_scene script; its render_complete/render_cancel
        handlers do the moodboard import + settings restore AFTER the script
        is long gone — stripping them orphans the render (settings never
        restored, image never imported). Matching is by object IDENTITY, not
        name/module (a script can forge ``__module__`` via ``__name__`` in
        its globals, but it cannot forge ``id()``); at worst a script can
        re-append these exact functions, which self-guard (no-op without an
        active job).
        """
        try:
            from mixar.modules.space_mixie_chat.ui.operators import (
                agent_final_render_ops as _afr,
            )

            return {id(_afr._on_render_complete), id(_afr._on_render_cancel)}
        except Exception:  # noqa: BLE001 — optional first-party operator module may be unavailable
            return set()

    def _cleanup_handlers(self, snapshot: dict[str, list]) -> None:
        """Remove any handlers that were added since the snapshot.

        Prevents scripts from installing persistent backdoors via handlers.
        """
        for name, before_list in snapshot.items():
            handler_list = getattr(bpy.app.handlers, name, None)
            if handler_list is None:
                continue
            before_set = {id(h) for h in before_list}
            added = [h for h in handler_list if id(h) not in before_set]
            exempt = self._exempt_handler_ids()
            for handler in added:
                if id(handler) in exempt:
                    logger.debug(
                        "Keeping exempt first-party handler: %s.%s (%s)",
                        "bpy.app.handlers",
                        name,
                        getattr(handler, "__name__", repr(handler)),
                    )
                    continue
                try:
                    handler_list.remove(handler)
                    logger.warning(
                        "Cleaned up handler added by script: %s.%s (%s)",
                        "bpy.app.handlers",
                        name,
                        getattr(handler, "__name__", repr(handler)),
                    )
                except ValueError:
                    pass
