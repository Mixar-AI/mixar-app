# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

RETRY_INTERVAL = 0.25


#: Custom property on the private scene an agent preview renders
#: (``space_mixie_chat/core/render_scene.py``). Such a scene is never a tab, never
#: adopted as a chat, never the agent document's "first scene" and never a window's
#: fallback; scene scans skip it through ``is_internal_scene``.
INTERNAL_RENDER_SCENE_PROP = "mixar_internal_render_scene"


def is_internal_scene(scene) -> bool:
    """True for a private render scene that must stay invisible to the user."""
    try:
        return bool(scene.get(INTERNAL_RENDER_SCENE_PROP))
    except (AttributeError, ReferenceError, TypeError):
        return False
