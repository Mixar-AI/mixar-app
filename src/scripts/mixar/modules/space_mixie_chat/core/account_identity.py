# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Process-local email behind the legacy Scene account property.

SKIP_SAVE excludes operator reuse/presets, not Scene IDProperties from
blend files. Custom RNA accessors keep identity out of project data and
make every scene read the same account, including during an async refresh.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import StringProperty

_email = ""
_PROPERTY = "mixie_chat_user_id"


def get_email(_scene, _stored_value, _is_set):
    return _email


def set_email(_scene, value, _stored_value, _is_set):
    global _email
    _email = value
    return ""  # RNA may store this value; never return the account email.


@persistent
def remove_saved_identity(_unused=None):
    """Discard legacy values without ever adopting the file's account."""
    for scene in bpy.data.scenes:
        # Blender 5.2 separates RNA system properties from scene[key].
        # Transform callbacks retain property_unset support for migration.
        scene.property_unset(_PROPERTY)
        if _PROPERTY in scene:
            del scene[_PROPERTY]


def register():
    bpy.types.Scene.mixie_chat_user_id = StringProperty(
        name="User ID",
        description="User ID for Mixie Chat login",
        maxlen=256,
        options={'SKIP_SAVE'},
        get_transform=get_email,
        set_transform=set_email,
    )
    remove_saved_identity()
    for handlers in (bpy.app.handlers.load_post, bpy.app.handlers.save_pre):
        if remove_saved_identity not in handlers:
            handlers.append(remove_saved_identity)


def unregister():
    for handlers in (bpy.app.handlers.load_post, bpy.app.handlers.save_pre):
        if remove_saved_identity in handlers:
            handlers.remove(remove_saved_identity)
    if hasattr(bpy.types.Scene, _PROPERTY):
        delattr(bpy.types.Scene, _PROPERTY)
    set_email(None, "", "", False)
