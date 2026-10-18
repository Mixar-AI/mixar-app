# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Process-local sign-in identity behind the Scene / WindowManager properties.

SKIP_SAVE excludes operator reuse/presets, not Scene IDProperties from
blend files. Custom RNA accessors keep identity out of project data and
make every scene read the same account, including during an async refresh.

The WindowManager sign-in flags, account name and usage mirror need the
same: opening a file (or File > New) adopts that file's WindowManager, so
stored values would replace the live session's until the next refresh — a
guest then read as signed in to an account and the top bar showed its
placeholder address.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import StringProperty

_email = ""
_PROPERTY = "mixie_chat_user_id"
# WindowManager session state: property name -> this session's value.
_values = {}
# Every property reading through `session_value`; their stored copies are stripped.
_session_props = set()


def get_email(_scene, _stored_value, _is_set):
    return _email


def set_email(_scene, value, _stored_value, _is_set):
    global _email
    _email = value
    return ""  # RNA may store this value; never return the account email.


def session_value(name, default=False):
    """``get_transform`` / ``set_transform`` keywords keeping WindowManager
    property ``name`` in this process: a file's stored value is never read."""
    _session_props.add(name)

    def get_value(_wm, _stored_value, _is_set):
        return _values.get(name, default)

    def set_value(_wm, value, _stored_value, _is_set):
        _values[name] = value
        return default  # What RNA stores (and a save writes) is never the session's.

    return {"get_transform": get_value, "set_transform": set_value}


@persistent
def remove_saved_identity(_unused=None):
    """Discard legacy values without ever adopting the file's account."""
    for scene in bpy.data.scenes:
        # Blender 5.2 separates RNA system properties from scene[key].
        # Transform callbacks retain property_unset support for migration.
        scene.property_unset(_PROPERTY)
        if _PROPERTY in scene:
            del scene[_PROPERTY]
    for wm in bpy.data.window_managers:
        for name in _session_props:
            # Registered after this module, so absent at its own register().
            if name in wm.bl_rna.properties:
                wm.property_unset(name)
            if name in wm:
                del wm[name]


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
    _values.clear()
