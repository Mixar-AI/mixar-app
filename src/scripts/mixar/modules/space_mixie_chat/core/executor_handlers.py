# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Identity-bound cleanup of script handlers and trusted native job callbacks."""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class HandlerCleanupMixin:
    """Snapshot ``bpy.app.handlers`` before a sandboxed script and strip
    whatever it added afterwards — except the first-party preview-render
    callbacks that must outlive the script that started the job."""

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

        ``mixie_chat.agent_preview_render`` starts a native render job during
        a sandboxed ``render_viewport`` (``quality="final"``) script; its render_complete /
        render_cancel / depsgraph / load_pre callbacks deliver the pixels and
        restore the settings AFTER the script is long gone — stripping them
        orphans the render. Matching is by object IDENTITY, not name/module
        (a script can forge ``__module__`` via ``__name__`` in its globals,
        but it cannot forge ``id()``); at worst a script can re-append these
        exact functions, which self-guard (no-op without an active job).
        """
        try:
            from . import preview_render as preview
            return {id(preview._complete), id(preview._cancelled),
                    id(preview._changed), id(preview._before_load)}
        except Exception:
            return set()

    def _cleanup_handlers(self, snapshot: dict[str, list]) -> None:
        """Remove any handlers that were added since the snapshot.

        Prevents scripts from installing persistent backdoors via handlers.
        """
        exempt = self._exempt_handler_ids()
        for name, before_list in snapshot.items():
            handler_list = getattr(bpy.app.handlers, name, None)
            if handler_list is None:
                continue
            before_set = set(id(h) for h in before_list)
            added = [h for h in handler_list if id(h) not in before_set]
            for handler in added:
                if id(handler) in exempt:
                    logger.debug(
                        "Keeping exempt first-party handler: %s.%s (%s)",
                        "bpy.app.handlers", name,
                        getattr(handler, '__name__', repr(handler)),
                    )
                    continue
                try:
                    handler_list.remove(handler)
                    logger.warning(
                        "Cleaned up handler added by script: %s.%s (%s)",
                        "bpy.app.handlers", name,
                        getattr(handler, '__name__', repr(handler)),
                    )
                except ValueError:
                    pass
