# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drop sidebar Refine state when a different file is loaded.

Thin auto-discovered bridge, mirroring ``splat_lifecycle_sync``: the logic
lives in ``moodboard/core/prompt_refine.py``; this module only owns handler
registration so bootstrap loads it in the UI phase.

The stash is keyed by tab, not by file: without this, opening a second
project would leave the Refine button showing Revert, and pressing it would
overwrite that file's prompt with one from the previous file — a data loss
wearing the costume of an undo. The canvas nodes need no such handler; their
equivalent state is SKIP_SAVE RNA and reloads empty by construction.
"""

import bpy

from mixar.modules.moodboard.core import prompt_refine


@bpy.app.handlers.persistent
def _on_load_post(*_args) -> None:
    prompt_refine.forget_sidebar_state()


def register():
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
