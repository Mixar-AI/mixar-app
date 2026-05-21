# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

# bl_info = {
# 	"name": "Texel Density Checker",
# 	"description": "Toolset for working with Texel Density",
# 	"author": "Ivan 'mrven' Vostrikov, Toomas Laik, Oxicid, johnwildauer, lfod1997",
# 	"wiki_url": "https://github.com/mrven/Blender-Texel-Density-Checker#readme",
# 	"tracker_url": "https://github.com/mrven/Blender-Texel-Density-Checker/issues",
# 	"doc_url": "https://github.com/mrven/Blender-Texel-Density-Checker#readme",
# 	"version": (2025, 1, 0),
# 	"blender": (3, 0, 0),
# 	"location": "3D View > Toolbox",
# 	"category": "Object",
# }

import importlib
import sys

import bpy
from bpy.app import timers
from bpy.app.handlers import persistent

# config_json imported locally to avoid circular imports

modules_names = [
    "props",
    "preferences",
    "utils",
    "core_td_operators",
    "add_td_operators",
    "viz_operators",
    "ui",
]

modules_full_names = {}
for current_module_name in modules_names:
    modules_full_names[current_module_name] = "{}.{}".format(
        __package__, current_module_name
    )

for current_module_full_name in modules_full_names.values():
    if current_module_full_name in sys.modules:
        importlib.reload(sys.modules[current_module_full_name])
    else:
        globals()[current_module_full_name] = importlib.import_module(
            current_module_full_name
        )
        setattr(globals()[current_module_full_name], "modulesNames", modules_full_names)


def deferred_initialize():
    from . import config_json

    config_json.load_or_initialize_prefs()
    config_json.saving_enabled = True
    config_json.copy_prefs_to_props()

    return None


@persistent
def on_load_post(_):
    from . import config_json

    config_json.load_or_initialize_prefs()
    config_json.copy_prefs_to_props()


def register():
    from . import config_json

    config_json.saving_enabled = False
    for module_name in modules_full_names.values():
        if module_name in sys.modules:
            if hasattr(sys.modules[module_name], "register"):
                sys.modules[module_name].register()

    timers.register(deferred_initialize, first_interval=0.1)

    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)


def unregister():
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)

    # Remove the texel-density viewport gradient draw handler if it is
    # currently installed. Without this the closure stays attached to
    # SpaceView3D and Blender will call it after the addon is gone, which
    # typically crashes on the next viewport repaint.
    try:
        props_mod = sys.modules.get(modules_full_names.get("props"))
        if props_mod is not None:
            handle = props_mod.draw_info.get("handler")
            if handle is not None:
                bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
                props_mod.draw_info["handler"] = None
    except Exception:
        pass

    if bpy.app.timers.is_registered(deferred_initialize):
        bpy.app.timers.unregister(deferred_initialize)

    for module_name in modules_full_names.values():
        if module_name in sys.modules:
            if hasattr(sys.modules[module_name], "unregister"):
                sys.modules[module_name].unregister()
