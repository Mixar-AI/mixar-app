# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where a live add-on shows up in the UI — read from Blender, not guessed.

After an add-on goes live the agent tells the user how to use it. What it
says must match what Blender actually registered, so this reads the running
registrations: the add-on's panels (editor, region, sidebar tab), the menus
its draw functions were appended to, its operators and their shortcuts in the
add-on keyconfig, and its preferences. Names and labels only, never paths.
Main thread only (it reads ``bpy.types`` and the window manager).
"""

import sys

from .checks import package_classes

# Editor names as the UI labels them.
_SPACES = {
    "VIEW_3D": "3D Viewport", "PROPERTIES": "Properties editor", "IMAGE_EDITOR": "Image Editor",
    "NODE_EDITOR": "Node Editor", "SEQUENCE_EDITOR": "Video Sequencer", "TEXT_EDITOR": "Text Editor",
    "GRAPH_EDITOR": "Graph Editor", "DOPESHEET_EDITOR": "Dope Sheet", "NLA_EDITOR": "Nonlinear Animation",
    "OUTLINER": "Outliner", "CLIP_EDITOR": "Movie Clip Editor", "FILE_BROWSER": "File Browser",
    "PREFERENCES": "Preferences", "CONSOLE": "Python Console", "INFO": "Info", "SPREADSHEET": "Spreadsheet",
}
_REGIONS = {"UI": "Sidebar (press N)", "TOOLS": "Toolbar (press T)", "HEADER": "Header",
            "TOOL_HEADER": "Tool Settings bar", "WINDOW": None}
# Menu class prefixes → the editor whose header shows them.
_MENU_PREFIXES = {
    "VIEW3D_": "3D Viewport", "TOPBAR_MT_": "Topbar", "IMAGE_": "Image Editor", "NODE_": "Node Editor",
    "SEQUENCER_": "Video Sequencer", "TEXT_": "Text Editor", "GRAPH_": "Graph Editor",
    "DOPESHEET_": "Dope Sheet", "OUTLINER_": "Outliner", "PROPERTIES_": "Properties editor",
}
# Zen Mode replaces the 3D Viewport's stock header; its menus are reachable in Engine.
ZEN_HEADER_NOTE = ("In Zen Mode the 3D Viewport's stock header menus are hidden; switch the topbar "
                   "Zen/Engine toggle to Engine to reach them. The Sidebar (N) works in both.")


def _owned(fn, entrypoint: str) -> bool:
    module = str(getattr(fn, "__module__", "") or "")
    return module == entrypoint or module.startswith(entrypoint + ".")


def _panel(cls, labels: dict) -> dict:
    space = getattr(cls, "bl_space_type", "")
    region = getattr(cls, "bl_region_type", "")
    context = getattr(cls, "bl_context", "") or ""
    category = getattr(cls, "bl_category", "") or ""
    parent = getattr(cls, "bl_parent_id", "") or ""
    steps = [_SPACES.get(space, space.replace("_", " ").title())]
    if space == "PROPERTIES" and context:
        steps.append(f"{context.replace('_', ' ').title()} tab")
    else:
        region_label = _REGIONS.get(region, region.replace("_", " ").title())
        if region_label:
            steps.append(region_label)
        if region == "UI":
            steps.append(f"{category or 'Misc'} tab")
    if parent:
        steps.append(f"{labels.get(parent, parent)} panel")
    steps.append(f"{getattr(cls, 'bl_label', '') or cls.__name__} panel")
    record = {"label": getattr(cls, "bl_label", "") or cls.__name__, "editor": space,
              "region": region, "location": " > ".join(steps)}
    if category:
        record["tab"] = category
    if context and space != "PROPERTIES":
        record["mode"] = context   # e.g. "objectmode": the panel shows only in that mode
    if parent:
        record["parent"] = labels.get(parent, parent)
    return record


def _key(kmi) -> str:
    mods = [name for flag, name in (("ctrl", "Ctrl"), ("shift", "Shift"), ("alt", "Alt"), ("oskey", "Cmd"))
            if getattr(kmi, flag, False)]
    return "+".join(mods + [str(getattr(kmi, "type", ""))])


def _menu_hooks(bpy, entrypoint: str) -> list:
    """Menus and headers whose draw was ``append``/``prepend``-ed by the add-on."""
    hooks = []
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        funcs = getattr(getattr(cls, "draw", None), "_draw_funcs", None)
        if not funcs or not any(_owned(fn, entrypoint) for fn in funcs):
            continue
        editor = next((label for prefix, label in _MENU_PREFIXES.items() if name.startswith(prefix)), "")
        label = getattr(cls, "bl_label", "") or name
        hooks.append({"menu": name, "label": label,
                      "location": f"{editor} > {label} menu" if editor else f"{label} menu"})
    return hooks


def addon_usage(entrypoint: str) -> dict:
    """How the live add-on is reached in the UI. Best-effort: a probe that
    fails is left out, never an error — the add-on is already live."""
    try:
        import bpy
    except Exception:
        return {}
    module = sys.modules.get(entrypoint)
    info = dict(getattr(module, "bl_info", {}) or {})
    classes = [cls for cls in package_classes(entrypoint)
               if getattr(bpy.types, cls.__name__, None) is cls or getattr(cls, "is_registered", False)]
    usage = {"name": str(info.get("name") or entrypoint)}
    if info.get("location"):
        usage["declared_location"] = str(info["location"])[:200]
    labels = {getattr(cls, "bl_idname", "") or cls.__name__: getattr(cls, "bl_label", "") or cls.__name__
              for cls in classes if issubclass(cls, bpy.types.Panel)}
    panels = [_panel(cls, labels) for cls in classes if issubclass(cls, bpy.types.Panel)]
    operators = {}
    for cls in classes:
        if issubclass(cls, bpy.types.Operator) and getattr(cls, "bl_idname", ""):
            doc = (getattr(cls, "bl_description", "") or cls.__doc__ or "").strip().splitlines()
            operators[cls.bl_idname] = {"idname": cls.bl_idname, "label": getattr(cls, "bl_label", "") or cls.bl_idname,
                                        "description": doc[0][:160] if doc else ""}
    try:
        keyconfig = bpy.context.window_manager.keyconfigs.addon
        for keymap in (keyconfig.keymaps if keyconfig else ()):
            for kmi in keymap.keymap_items:
                if kmi.idname in operators:
                    operators[kmi.idname].setdefault("shortcuts", []).append(
                        {"key": _key(kmi), "keymap": keymap.name})
    except Exception:
        pass
    try:
        menus = _menu_hooks(bpy, entrypoint)
    except Exception:
        menus = []
    menus += [{"menu": getattr(cls, "bl_idname", cls.__name__), "label": getattr(cls, "bl_label", "") or cls.__name__,
               "location": "its own menu (opened by the add-on's panels, menus or shortcuts)"}
              for cls in classes if issubclass(cls, bpy.types.Menu)]
    if panels:
        usage["panels"] = panels
    if menus:
        usage["menus"] = menus
    if operators:
        usage["operators"] = list(operators.values())
    if any(issubclass(cls, bpy.types.AddonPreferences) for cls in classes):
        usage["preferences"] = f"Edit > Preferences > Add-ons > {usage['name']}"
    if any(p["editor"] == "VIEW_3D" and p["region"] in ("HEADER", "TOOL_HEADER") for p in panels) \
            or any(m["menu"].startswith("VIEW3D_") for m in menus):
        usage["mixar_note"] = ZEN_HEADER_NOTE
    if not panels and not menus and not any(o.get("shortcuts") for o in operators.values()):
        usage["no_ui"] = ("No panel, menu entry or shortcut: the add-on is reachable only through its "
                          "operators (F3 search lists an operator only once it is in a menu).")
    return usage
