# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free isolated theme replay: Mixar --background --factory-startup --python this_file.

Writes artifacts to QA_SCENARIO_OUT (default /tmp/mixar-theme-xml-audit).
Never saves preferences. The same script can run through harness qa.eval().
"""
import os
import bpy
import json
import pathlib
import xml.etree.ElementTree as ET
import _rna_xml
from bl_ui.space_userpref import USERPREF_MT_interface_theme_presets as preset

out = pathlib.Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixar-theme-xml-audit'))
out.mkdir(parents=True, exist_ok=True)
required = {'ThemeMixieChat', 'ThemeSpaceMixie', 'ThemeAgentBubble'}
registered_at_start = required <= preset.preset_xml_secure_types
assert registered_at_start, "Theme bootstrap did not register custom XML types"
t = bpy.context.preferences.themes[0]
targets = []
for path, prefixes in [('user_interface', ('mixar_',)), ('agent_bubble', ('agent_',)),
                       ('mixie_chat', ('chat_',)), ('mixie', ('mixar_', 'moodboard_'))]:
    obj = getattr(t, path)
    for prop in obj.bl_rna.properties:
        if not prop.is_skip_save and prop.identifier.startswith(prefixes) and prop.type == 'FLOAT' and prop.subtype in {'COLOR', 'COLOR_GAMMA'}:
            targets.append((path, obj, prop.identifier))
targets += [('view_3d.space.gradients', t.view_3d.space.gradients, p) for p in ['high_gradient', 'gradient']]
targets += [('mixie.space', t.mixie.space, 'back')]
original = {(path, p): tuple(getattr(obj, p)) for path, obj, p in targets}
export = str(out / 'export.xml')
_rna_xml.xml_file_write(bpy.context, export, preset.preset_xml_map)
tree = ET.parse(export)
retired = []
for path in ('user_interface', 'mixie', 'mixie_chat'):
    obj = getattr(t, path)
    for prop in obj.bl_rna.properties:
        if prop.is_hidden and prop.is_skip_save:
            retired.append((obj.bl_rna.identifier, prop.identifier))
            assert all(prop.identifier not in n.attrib for n in tree.iter(obj.bl_rna.identifier))
assert len(retired) == 23, retired

# Saved viewport overrides must not hide the imported palette.
viewports = [s for screen in bpy.data.screens for area in screen.areas
             for s in area.spaces if s.type == 'VIEW_3D']
for space in viewports:
    space.shading.background_type = 'WORLD'
    space.shading.studiolight_background_alpha = 1

from mixar.modules.common.core.theme_colors import sketch_ink_color
# GUI discovery runs in timer batches; background processes have no event loop.
if bpy.app.background and not hasattr(bpy.types.Scene, 'mixie_edit_tool_state'):
    from mixar.modules.moodboard.ui import moodboard_edit_state
    from mixar.modules.moodboard.ui.properties import canvas_annotation_props
    for cls in moodboard_edit_state.classes:
        if not cls.is_registered:
            bpy.utils.register_class(cls)
    bpy.types.Scene.mixie_edit_tool_state = bpy.props.PointerProperty(
        type=moodboard_edit_state.MoodboardEditToolState)
    canvas_annotation_props.register()
brush = bpy.context.scene.mixie_edit_tool_state
brush.property_unset('annotation_color')
saved = bpy.context.scene.mixie_moodboard_annotations.add()
saved.color = (.8, .2, .1, 1)
saved_color = tuple(saved.color)

expected = {}
missing = []
for i, (path, obj, p) in enumerate(targets):
    tag = obj.bl_rna.identifier
    nodes = [n for n in tree.iter(tag) if p in n.attrib]
    if not nodes:
        missing.append(path + '.' + p)
        continue
    rgb = [(31 + i * 7) % 220 + 16, (61 + i * 11) % 220 + 16, (91 + i * 13) % 220 + 16]
    rgba = rgb + ([211] if len(getattr(obj, p)) == 4 else [])
    # Shared ThemeSpace subtypes need an explicit editor path.
    if path == 'mixie.space':
        nodes = tree.findall('.//mixie/ThemeSpaceMixie/space/ThemeSpaceGeneric')
    if path == 'view_3d.space.gradients':
        nodes = tree.findall('.//view_3d/ThemeView3D/space/ThemeSpaceGradient/gradients/ThemeGradientColors')
    assert nodes, (path, tag, p)
    for node in nodes:
        node.set(p, '#' + ''.join(f'{v:02x}' for v in rgba))
    expected[path, p] = rgba
edited = str(out / 'edited.xml')
tree.write(edited, encoding='utf-8', xml_declaration=True)
assert bpy.ops.script.execute_preset(filepath=edited, menu_idname='USERPREF_MT_interface_theme_presets') == {'FINISHED'}
assert all(s.shading.background_type == 'THEME' and
           s.shading.studiolight_background_alpha == 0 for s in viewports)
assert tuple(brush.annotation_color) == sketch_ink_color()
assert tuple(saved.color) == saved_color
brush.annotation_color = (.1, .2, .3, 1)
custom_brush = tuple(brush.annotation_color)
failures = []
for path, obj, p in targets:
    actual = [round(v * 255) for v in getattr(obj, p)]
    if actual != expected.get((path, p)):
        failures.append({'property': path + '.' + p, 'actual': actual, 'expected': expected.get((path, p))})
_rna_xml.xml_file_write(bpy.context, str(out / 'reexport.xml'), preset.preset_xml_map)
for path, obj, p in targets:
    setattr(obj, p, original[path, p])
assert bpy.ops.script.execute_preset(filepath=str(out / 'reexport.xml'), menu_idname='USERPREF_MT_interface_theme_presets') == {'FINISHED'}
for path, obj, p in targets:
    actual = [round(v * 255) for v in getattr(obj, p)]
    if actual != expected.get((path, p)):
        failures.append({'reexport_property': path + '.' + p, 'actual': actual})
assert tuple(brush.annotation_color) == custom_brush
assert tuple(saved.color) == saved_color

# Old exported attributes remain accepted, but never leak into the next export.
legacy = ET.parse(export)
legacy.find('.//ThemeUserInterface').set('mixar_profile_fill', '#123456ff')
legacy_path = str(out / 'legacy.xml')
legacy.write(legacy_path, encoding='utf-8')
assert bpy.ops.script.execute_preset(filepath=legacy_path, menu_idname='USERPREF_MT_interface_theme_presets') == {'FINISHED'}
assert [round(v * 255) for v in t.user_interface.mixar_profile_fill] == [18, 52, 86, 255]
_rna_xml.xml_file_write(bpy.context, str(out / 'legacy-reexport.xml'), preset.preset_xml_map)
assert 'mixar_profile_fill=' not in (out / 'legacy-reexport.xml').read_text()
assert not missing and not failures, (missing, failures)
result = {'retired': len(retired), 'registered_at_start' : registered_at_start, 'checked': len(targets), 'missing': missing, 'failures': failures}
(out / 'result.json').write_text(json.dumps(result, indent=2))
print('THEME_AUDIT_RESULT=' + json.dumps(result), flush=True)
