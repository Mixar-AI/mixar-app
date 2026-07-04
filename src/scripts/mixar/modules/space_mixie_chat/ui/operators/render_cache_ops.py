# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Prune the agent render cache — a native (unsandboxed) helper the sandboxed
render scripts call to cap how many temp render PNGs accumulate.

Why this exists: the ScriptExecutor sandbox no longer exposes ``os`` (injecting
the real module was a sandbox escape, so it was removed). The agent's
``render_viewport`` / ``render_multiview`` scripts therefore write their PNGs to
the OS temp dir but can no longer ``os.listdir`` / ``os.unlink`` to enforce a
retention cap. This operator runs as ordinary addon code with full ``os`` access
and does that pruning, invoked from the sandboxed script via::

    bpy.ops.mixie_chat.prune_render_cache(keep=200)

Scope is deliberately narrow: it only touches files in the system temp dir whose
names match the agent render prefixes, and it never raises — pruning is
best-effort cleanup that must never break a render (the OS temp reaper remains
the ultimate backstop). Callers wrap the invocation in try/except, so an older
client without this operator still renders fine, just uncapped.
"""

from mixar.config.logging_config import get_logger
import os
import tempfile

import bpy

logger = get_logger(__name__)

# Filename prefixes written by the agent render scripts. Every artifact lives in
# the OS temp ROOT as "<prefix><ms-timestamp>...png". Keep in sync with the
# backend scripts render_viewport.py / render_multiview.py.
_RENDER_PREFIXES = ("mixar_render_", "mixar_mv_")


class MIXIE_CHAT_OT_prune_render_cache(bpy.types.Operator):
    """Delete old agent render PNGs from the OS temp dir, keeping the newest
    ``keep`` per prefix. Best-effort and silent; called by sandboxed render
    scripts that cannot use ``os`` to clean up after themselves."""

    bl_idname = "mixie_chat.prune_render_cache"
    bl_label = "Prune Agent Render Cache"
    bl_options = {"INTERNAL"}

    keep: bpy.props.IntProperty(default=200, min=1)

    def execute(self, context):
        try:
            tmp = tempfile.gettempdir()
            names = os.listdir(tmp)
        except OSError as e:
            logger.debug("prune_render_cache: cannot list temp dir (%s)", e)
            return {"FINISHED"}

        removed = 0
        for prefix in _RENDER_PREFIXES:
            group = [n for n in names if n.startswith(prefix) and n.endswith(".png")]
            if len(group) <= self.keep:
                continue
            paths = [os.path.join(tmp, n) for n in group]
            # Newest-last by mtime, then unlink everything but the newest `keep`.
            # Fall back to name order (the embedded ms timestamp sorts correctly)
            # if a stat races with the OS reaper deleting a file underneath us.
            try:
                paths.sort(key=os.path.getmtime)
            except OSError:
                paths.sort()
            for p in paths[:-self.keep]:
                try:
                    os.unlink(p)
                    removed += 1
                except OSError:
                    pass

        if removed:
            logger.debug("prune_render_cache: removed %d old render(s)", removed)
        return {"FINISHED"}


classes = (
    MIXIE_CHAT_OT_prune_render_cache,
)
