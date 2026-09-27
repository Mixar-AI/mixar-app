# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Include Mixar's native theme structs in Blender's restricted XML importer."""

_added_types = set()
_original_post_cb = None
_post_cb_installed = False
_original_generic = None


def _draw_editor_theme(layout, data):
    """Mixar-specific controls live once, in the Mixar panel."""
    prefixes = {
        "ThemeSpaceMixie": ("mixar_", "moodboard_"),
        "ThemeAgentBubble": ("agent_",),
        "ThemeMixieChat": ("chat_",),
    }.get(data.bl_rna.identifier)
    if prefixes is None:
        return _original_generic.__get__(None, object)(layout, data)
    layout.use_property_split = True
    flow = layout.grid_flow(row_major=False, columns=0, even_columns=True, even_rows=False)
    for prop in data.bl_rna.properties:
        if (prop.identifier != "rna_type" and prop.type != 'POINTER'
                and not prop.is_hidden and not prop.identifier.startswith(prefixes)):
            flow.prop(data, prop.identifier)


def _post_import(cls, context, filepath):
    if _original_post_cb is not None:
        _original_post_cb.__get__(None, cls)(context, filepath)
    import bpy
    from mixar.modules.common.core.theme_backgrounds import use_theme_backgrounds

    use_theme_backgrounds(bpy.data.screens)


def register():
    global _original_post_cb, _post_cb_installed, _original_generic
    from bl_ui.space_userpref import USERPREF_MT_interface_theme_presets, PreferenceThemeSpacePanel

    allowed = USERPREF_MT_interface_theme_presets.preset_xml_secure_types
    for name in ("ThemeMixieChat", "ThemeSpaceMixie", "ThemeAgentBubble"):
        if name not in allowed:
            allowed.add(name)
            _added_types.add(name)
    if not _post_cb_installed:
        _original_post_cb = USERPREF_MT_interface_theme_presets.__dict__.get("post_cb")
        USERPREF_MT_interface_theme_presets.post_cb = classmethod(_post_import)
        _post_cb_installed = True
        _original_generic = PreferenceThemeSpacePanel.__dict__["_theme_generic"]
        PreferenceThemeSpacePanel._theme_generic = staticmethod(_draw_editor_theme)


def unregister():
    global _original_post_cb, _post_cb_installed, _original_generic
    from bl_ui.space_userpref import USERPREF_MT_interface_theme_presets, PreferenceThemeSpacePanel

    USERPREF_MT_interface_theme_presets.preset_xml_secure_types.difference_update(_added_types)
    _added_types.clear()
    if _post_cb_installed:
        if _original_post_cb is None:
            del USERPREF_MT_interface_theme_presets.post_cb
        else:
            USERPREF_MT_interface_theme_presets.post_cb = _original_post_cb
        _original_post_cb = None
        _post_cb_installed = False
        PreferenceThemeSpacePanel._theme_generic = _original_generic
        _original_generic = None
