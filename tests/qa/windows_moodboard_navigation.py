# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real canvas navigation for Windows replays with small new node cards.

No model parameters, control visibility, or view matrices are forced. Add a
real template, capture its initial geometry, then use native Frame Selected.
Operator tooltip descriptions are read from classes when the native QA dump
omits them; actual hover captures remain mandatory visual evidence.
"""
import json
import os

from lib import ensure_moodboard_area, open_moodboard_node
import moodboard_redesign_e2e as redesign
import moodboard_drawer_tools_e2e as tools
from moodboard_drawer_e2e import geometry, toggle


def toolbar_visible(qa, visible):
    """Real T shortcut on an uncovered viewport; fixture isolation only."""
    shown = qa.eval("result=next(a for a in drv.main_window().screen.areas "
                    "if a.type=='VIEW_3D').spaces.active.show_region_toolbar")
    if shown == visible:
        return
    opened = geometry(qa)['amount'] > .98
    if opened:
        toggle(qa, 0)
    qa.eval("w=drv.main_window();a=next(a for a in w.screen.areas if a.type=='VIEW_3D');"
            "r=next(r for r in a.regions if r.type=='WINDOW');"
            "drv.move_to(w,r.x+r.width//2,r.y+r.height//2);result=True")
    qa.press('T')
    qa.wait("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')"
            f'.spaces.active.show_region_toolbar=={visible}', timeout=5)
    if opened:
        toggle(qa, 1)


def frame(qa, folder, node_id):
    label = 'node-' + node_id[:8]
    geometry = qa.eval("host=drv.moodboard_host();w=drv.main_window()\n"
        "a=next(a for a in w.screen.areas if a.type==host['area_type'])\n"
        "r=next(r for r in a.regions if r.type==host['region_type'])\n"
        f"n=next(n for n in w.scene.mixie_moodboard_action_nodes if n.node_id=={node_id!r})\n"
        "p=r.view2d.view_to_region(n.position_x,n.position_y,clip=False)\n"
        "q=r.view2d.view_to_region(n.position_x+n.width,n.position_y+n.height,clip=False)\n"
        "result={'card_pixels':[q[0]-p[0],q[1]-p[1]],'card_world':[n.width,n.height],"
        "'host':host,'region_pixels':[r.width,r.height],"
        "'ui_scale':bpy.context.preferences.system.ui_scale}")
    (folder / (label + '-before-frame-state.json')).write_text(json.dumps(geometry, indent=2))
    qa.cmd('snap', path=str(folder / (label + '-before-frame.png')))
    open_moodboard_node(qa, node_id)
    qa.wait("bool(drv.find(op='MIXIE_OT_moodboard_node_settings'))", timeout=8)
    qa.cmd('snap', path=str(folder / (label + '-framed.png')))


def add(qa, folder, template):
    ensure_moodboard_area(qa)
    qa.wait("__import__('mixar.bootstrap.generation_catalog_cache',"
            "fromlist=['is_loaded']).is_loaded()", timeout=45)
    before = redesign.nodes(qa)
    query = {'op': redesign.ADD, 'text': template}
    if qa.find(**query)['total']:
        qa.click(**query)
    else:
        qa.click(**redesign.TEMPLATES)
        qa.wait(f'bool(drv.find(popup=True,text={template!r}))', timeout=6)
        qa.click(popup=True, **query)
    qa.wait(f'len(drv.main_window().scene.mixie_moodboard_action_nodes)=={len(before)+1}', timeout=8)
    node = redesign.nodes(qa)[-1]
    assert node['state'] == 'DRAFT' and not node['job_id'] and node['model'], node
    frame(qa, folder, node['id'])
    return node['id']


def toolbar(qa):
    """Keep layout assertions while resolving help from registered classes."""
    controls = [qa.find(**q)['widgets'] for q in (tools.MEDIA, tools.TEXT, tools.ANNOTATE)]
    assert all(len(w) == 1 for w in controls), controls
    media, text, annotate = (w[0] for w in controls)
    panel = tools.target(qa, 'moodboard_drawer_panel')['rect']
    for w in (media, text, annotate):
        x0, y0, x1, y1 = w['rect']
        assert w['enabled'] and w['mixar_theme'] == 'ZEN', w
        assert w['mixar_component'] == 'action' and w['block'] == 'MIXIE_PT_canvas_tools', w
        assert panel[0] < x0 < x1 < panel[2] and panel[1] < y0 < y1 < panel[3], w
    assert media['rect'][::2] == text['rect'][::2] == annotate['rect'][::2]
    assert text['rect'][3] <= media['rect'][1] and annotate['rect'][3] <= text['rect'][1]
    scale = qa.eval('result=bpy.context.preferences.system.ui_scale')
    assert abs(media['rect'][2] - media['rect'][0] - 32 * scale) <= 2
    assert abs(media['rect'][0] - panel[0] - 12 * scale) <= 2
    assert [w['text'] for w in (media, text, annotate)] == ['', '', '']
    assert not qa.find(**tools.ERASE)['total']
    descriptions = qa.eval("from mixar.modules.moodboard.ui.operators.canvas_annotation_ops import MIXIE_OT_moodboard_annotate_canvas as a\n"
        "from mixar.modules.moodboard.ui.operators.textbox_add_ops import MIXIE_OT_moodboard_add_textbox as t\n"
        "result={a.__name__:a.bl_description,t.__name__:t.bl_description}")
    assert 'saved in the project' in descriptions['MIXIE_OT_moodboard_annotate_canvas']
    assert 'Add a text box' in descriptions['MIXIE_OT_moodboard_add_textbox']
    assert media['tip'].startswith('Add media'), media
    return {'controls': controls, 'operator_descriptions': descriptions,
            'tooltip_visual_verdict_requires_native_hover_capture': True}


def adapt(module, qa, folder):
    name = module.__name__
    if name == 'moodboard_node_dropdowns_e2e':
        module.add_moodboard_node = lambda client, template: add(client, folder, template)
    elif name == 'moodboard_parameter_help_e2e':
        original = module.add
        original_click = qa.click
        original_run = module.run
        old_toolbar = qa.eval("result=next(a for a in drv.main_window().screen.areas "
                              "if a.type=='VIEW_3D').spaces.active.show_region_toolbar")
        board_clicks = []

        def settled_click(**query):
            if query.get('text') == 'Arrange, frame, or clear the board':
                index = len(board_clicks)
                observed = {'query': query, 'before': qa.find(**query),
                            'scale': qa.eval('result=bpy.context.preferences.system.ui_scale')}
                observed['regions'] = qa.eval("w=drv.main_window();host=drv.moodboard_host();"
                    "a=next(a for a in w.screen.areas if a.type==host['area_type']);"
                    "result={'window':[w.width,w.height],'area':[a.x,a.y,a.width,a.height],"
                    "'host':host,'toolbar':getattr(a.spaces.active,'show_region_toolbar',False),"
                    "'sidebar':getattr(a.spaces.active,'show_region_ui',False),"
                    "'regions':[{'type':r.type,'rect':[r.x,r.y,r.x+r.width,r.y+r.height]} for r in a.regions]}")
                qa.cmd('snap', path=str(folder / f'board-{index}-before.png'))
                if (os.environ.get('QA_HELP_ISOLATE_TOOLBAR') == '1'
                        and observed['scale'] > 1.1 and observed['regions']['toolbar']
                        and observed['regions']['host']['area_type'] == 'VIEW_3D'):
                    # Preserve the prior failure; this is a separate help-only
                    # coverage fixture, never a pass for covered resize zones.
                    toolbar_visible(qa, False)
                    observed['isolation'] = 'Real T hides underlying toolbar; original Board overlap remains a finding'
                    observed['after_isolation'] = qa.find(**query)
                    qa.cmd('snap', path=str(folder / f'board-{index}-toolbar-hidden.png'))
                observed['click'] = original_click(**query)
                observed['after'] = qa.find(popup=True)
                board_clicks.append(observed)
                (folder / 'board-click-state.json').write_text(json.dumps(board_clicks, indent=2))
                qa.cmd('snap', path=str(folder / f'board-{index}-after.png'))
                return observed['click']
            # Scale changes redraw the menu after its native opening event.
            # Wait for its observed item; never replay the opening click.
            if query.get('op') == 'MIXIE_OT_moodboard_frame' and query.get('popup'):
                qa.wait(f'bool(drv.find(**{query!r}))', timeout=5)
            return original_click(**query)

        def framed_add(client, *args, **kwargs):
            node = original(client, *args, **kwargs)
            frame(client, folder, node)
            return node

        module.add = framed_add
        qa.click = settled_click

        def isolated_run(client):
            try:
                return original_run(client)
            finally:
                if client.eval("result=any(a.type=='VIEW_3D' for a in drv.main_window().screen.areas)"):
                    toolbar_visible(client, old_toolbar)

        module.run = isolated_run
    elif name == 'moodboard_drawer_tools_e2e':
        module.toolbar = toolbar
