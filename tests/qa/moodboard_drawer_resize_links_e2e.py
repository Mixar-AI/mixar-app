#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit live drawer resizing and reference socket regression.

Run against a clean isolated Dev app, using the same QA_HARNESS,
MIXAR_QA_PORT and QA_SCENARIO_OUT variables as moodboard_drawer_e2e.py.
All pointer actions use the harness's real event simulation. The standard
keyconfig activation operator is used only to reproduce a preset reload.
"""

import json
import time
from moodboard_drawer_e2e import (
    QA, OUT, SCENE, SETUP, drop, geometry, media, png, point, require,
    run_scenario, select, settle, snap, switch_mode, target, toggle, verify_viewport,
)


def canvas(qa):
    return qa.eval(SETUP + """
a = drawer.view2d.region_to_view(0, 0)
b = drawer.view2d.region_to_view(drawer.width - 1, drawer.height - 1)
result = {'width': drawer.width, 'height': drawer.height,
          'chosen': bpy.context.window_manager.mixar_moodboard_drawer_width,
          'view': [*a, *b],
          'units_per_pixel': [(b[0]-a[0]) / (drawer.width-1),
                              (b[1]-a[1]) / (drawer.height-1)]}
""")


def stable_canvas(before, after):
    for old, new in zip(before['units_per_pixel'], after['units_per_pixel']):
        require(abs(old-new) < max(abs(old)*0.004, 0.0001),
                f'Resizing changed canvas zoom: {before} -> {after}')
    tolerance = max(before['units_per_pixel']) * 4
    for index in (1, 2, 3):
        require(abs(before['view'][index]-after['view'][index]) < tolerance,
                f'Resizing moved the right edge or vertical view: {before} -> {after}')


def resize(qa, pixels, live=False):
    before = canvas(qa)
    grip = target(qa, 'moodboard_drawer_grip')
    start = point(grip)
    end = {'x': start['x'] - round(pixels-before['width']), 'y': start['y']}
    if live:
        # Separate event-loop ticks, matching drv.drag_xy_steps, permit a
        # state/screenshot check while LEFTMOUSE is still held.
        qa.eval(f"drv.move_to(drv.main_window(), {start['x']}, {start['y']})")
        qa.eval(f"drv._sim(drv.main_window(), type='LEFTMOUSE', value='PRESS', "
                f"x={start['x']}, y={start['y']})")
        try:
            for step in range(1, 9):
                x = round(start['x'] + (end['x']-start['x']) * step / 8)
                qa.eval(f"drv.move_to(drv.main_window(), {x}, {end['y']})")
            qa.wait(SET_WIDTH.format(pixels=pixels), timeout=4)
            held = canvas(qa)
            snap(qa, '02_live_drag_held')
            stable_canvas(before, held)
        finally:
            qa.eval(f"drv._sim(drv.main_window(), type='LEFTMOUSE', value='RELEASE', "
                    f"x={end['x']}, y={end['y']})")
    else:
        qa.cmd('drag', **{'from': {'surface': 'moodboard_drawer_grip'},
                         'to': end, 'steps': 14})
    settle(qa, 1)
    qa.wait(SET_WIDTH.format(pixels=pixels), timeout=4)
    after = canvas(qa)
    stable_canvas(before, after)
    qa.wait(f"__import__('time').monotonic() >= {time.monotonic()+0.5}", timeout=2)
    require(abs(canvas(qa)['width']-after['width']) < 3,
            'Released drawer snapped back instead of retaining the chosen width')
    return after


SET_WIDTH = ("abs(next(r for a in drv.main_window().screen.areas if a.type=='VIEW_3D' "
             "for r in a.regions if r.type=='TOOL_PROPS').width - {pixels}) < 4")


def reload_preset(qa):
    result = qa.eval("""
path = bpy.utils.preset_find('Blender', 'keyconfig', ext='.py')
result = {'path': path, 'activation': list(bpy.ops.preferences.keyconfig_activate(filepath=path))}
""")
    require(result['activation'] == ['FINISHED'], f'Preset reload failed: {result}')
    qa.wait("any(k.active and k.idname == 'mixie.moodboard_graph_select' "
            "for k in bpy.context.window_manager.keyconfigs.user.keymaps['Mixie'].keymap_items)",
            timeout=5)
    return result


def keymap_priority(qa):
    state = qa.eval("""
km = bpy.context.window_manager.keyconfigs.user.keymaps['Mixie']
result = [{'operator': k.idname, 'modifiers': [k.shift,k.ctrl,k.alt,k.oskey]}
          for k in km.keymap_items if k.active and k.type == 'LEFTMOUSE' and k.value == 'PRESS']
""")
    for modifiers in ([0, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1]):
        matching = [i['operator'] for i in state if i['modifiers'] == modifiers]
        if not matching and modifiers[-1]:
            continue  # Non-macOS uses Ctrl for the command modifier.
        require('mixie.moodboard_graph_select' in matching and
                'mixie.moodboard_select_image' in matching and
                matching.index('mixie.moodboard_graph_select') <
                matching.index('mixie.moodboard_select_image'),
                f'Graph sockets lose priority for {modifiers}: {matching}')
    return state


def select_exposed_reference(qa, node_id):
    # A newly selected action exposes its parameter panel over the existing
    # reference's center. Its upper-left body remains visible. A selected
    # reference flag alone cannot prove the click landed on the canvas.
    panel = target(qa, 'moodboard_drawer_panel')
    qa.cmd('click_xy', **point(panel, 0.10, 0.90))
    qa.wait(f"not any(n.selected for n in {SCENE}.mixie_moodboard_action_nodes)", timeout=4)
    widget = target(qa, 'moodboard_media', text=node_id)
    qa.cmd('click_xy', **point(widget, 0.06, 0.90))
    qa.wait(f"not any(n.selected for n in {SCENE}.mixie_moodboard_action_nodes) "
            "and not drv.find(popup=True)", timeout=4)
    require(next(i for i in media(qa) if i['id'] == node_id)['selected'],
            'Exposed reference-body click failed to select the reference')


def graph(qa):
    return qa.eval(f"sc={SCENE}\nresult={{"
                   "'nodes': [n.node_id for n in sc.mixie_moodboard_action_nodes],"
                   "'links': [[l.from_node_id,l.to_node_id,l.to_socket] "
                   "for l in sc.mixie_moodboard_links]}")


def pan(qa, dx, dy=0):
    panel = target(qa, 'moodboard_drawer_panel')
    start = point(panel, 0.7, 0.6)
    qa.cmd('drag', **{'from': start, 'to': {'x': start['x']+dx, 'y': start['y']+dy},
                     'steps': 14, 'button': 'MIDDLEMOUSE'})


def run(qa: QA):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.step('wait_idle', qa.wait,
            f"{SCENE}.mixie_chat_state in ('IDLE', 'OFFLINE')", timeout=90)
    if geometry(qa)['workspace'] != 'Zen Mode':
        qa.step('enter_zen', switch_mode, qa, 'mixar.set_ui_mode_ai', 'Zen Mode')
    initial = qa.step('viewport_before', geometry, qa)
    require(not media(qa) and not graph(qa)['nodes'], 'Use a clean QA profile')
    red = png(OUT / 'reference-red.png', (220, 70, 70))
    blue = png(OUT / 'reference-blue.png', (50, 130, 230))
    x0, y0, x1, y1 = initial['viewport']
    first = qa.step('reference_drop_reveals', drop, qa, red,
                    x=round(x0+(x1-x0)*0.45), y=round(y0+(y1-y0)*0.6))
    qa.step('select_existing_reference', select, qa, first)
    qa.step('snap_default_width', snap, qa, '01_default_width')
    base = canvas(qa)
    area_width = initial['area'][2]-initial['area'][0]
    qa.step('live_expand_beyond_old_cap', resize, qa, base['width']+420, True)
    qa.step('resize_to_arbitrary_middle', resize, qa, round(area_width*0.55))
    qa.step('resize_nearly_full_area', resize, qa, round(area_width*0.94))
    qa.step('snap_nearly_full', snap, qa, '03_nearly_full')
    chosen = qa.step('resize_to_working_width', resize, qa, round(area_width*0.70))
    qa.step('click_close_remembers_width', toggle, qa, 0)
    qa.step('click_reopen_remembers_width', toggle, qa, 1)
    require(abs(canvas(qa)['chosen']-chosen['chosen']) < 0.01 and
            abs(canvas(qa)['width']-chosen['width']) < 3,
            'Click close/reopen lost the chosen width')
    stable_canvas(chosen, canvas(qa))
    grip = target(qa, 'moodboard_drawer_grip')
    start = point(grip)
    qa.step('drag_below_minimum_closes', qa.cmd, 'drag',
            **{'from': {'surface': 'moodboard_drawer_grip'},
               'to': {'x': start['x']+canvas(qa)['width']-80, 'y': start['y']}, 'steps': 14})
    qa.step('narrow_drag_closed', settle, qa, 0)
    qa.step('reopen_restores_useful_width', toggle, qa, 1)
    require(abs(canvas(qa)['chosen']-chosen['chosen']) < 0.01,
            'Narrow closing drag replaced useful width')
    qa.step('resizing_keeps_viewport', verify_viewport, qa, initial)
    qa.step('reload_blender_keyconfig', reload_preset, qa)
    priority = qa.step('active_keymap_graph_first', keymap_priority, qa)
    qa.step('catalog_loaded', qa.wait,
            "__import__('mixar.bootstrap.generation_catalog_cache',"
            "fromlist=['is_loaded']).is_loaded()", timeout=45)

    # Put existing reference on the left, leaving room for its next node.
    qa.step('pan_existing_reference_left', pan, qa, -round(chosen['width']*0.35))
    qa.step('existing_output_click', qa.click, surface='moodboard_output', text=first)
    qa.step('continuation_menu_visible', qa.wait,
            "len(drv.find(popup=True,text='Generate Image')) == 1", timeout=5)
    qa.step('snap_output_menu', snap, qa, '04_output_popup')
    qa.step('create_unsubmitted_action', qa.click, popup=True, text='Generate Image')
    qa.step('typed_link_created', qa.wait,
            f"len({SCENE}.mixie_moodboard_action_nodes)==1 and "
            f"len({SCENE}.mixie_moodboard_links)==1", timeout=6)
    state = graph(qa)
    action = state['nodes'][0]
    require(state['links'] == [[first, action, 'reference_images:0']],
            f'Plus continuation created incorrect typed link: {state}')
    qa.step('deselect_action_options', select_exposed_reference, qa, first)
    qa.step('snap_first_link', snap, qa, '05_first_link')
    qa.step('repeatable_socket_available', qa.wait,
            f"len(drv.find(surface='moodboard_socket',text={action!r})) >= 2", timeout=8)

    panel = target(qa, 'moodboard_drawer_panel')
    second = qa.step('drop_second_reference', drop, qa, blue, **point(panel, 0.22, 0.035))
    qa.step('select_second_reference', select, qa, second)
    sockets = qa.find(surface='moodboard_socket', text=action)['widgets']
    empty = max(sockets, key=lambda w: w['index'])
    before = graph(qa)
    qa.step('snap_visible_socket_endpoints', snap, qa, '06_before_drag')
    qa.step('drag_output_to_empty_input', qa.cmd, 'drag',
            **{'from': {'surface': 'moodboard_output', 'text': second},
               'to': {'surface': 'moodboard_socket', 'text': action, 'index': empty['index']},
               'steps': 18})
    qa.step('second_typed_link_created', qa.wait,
            f"len({SCENE}.mixie_moodboard_links)==2", timeout=6)
    state = graph(qa)
    require(state['nodes'] == before['nodes'] and
            [second, action, empty['detail']] in state['links'],
            f'Drag failed to connect the requested reference/input: {state}')
    qa.step('snap_two_connected_references', snap, qa, '06_two_reference_links')
    qa.step('fresh_empty_socket_grows', qa.wait,
            f"len(drv.find(surface='moodboard_socket',text={action!r})) >= 3", timeout=6)
    qa.step('close_connected_board', toggle, qa, 0)
    qa.step('reopen_connected_board', toggle, qa, 1)
    require(graph(qa) == state, 'Closing the drawer lost graph links')
    qa.step('graph_keeps_viewport', verify_viewport, qa, initial)
    qa.step('snap_final_board', snap, qa, '07_reopened_connected_board')
    result = {'arbitrary_width_retained': True, 'live_resize': True,
              'pixel_zoom_and_right_edge_stable': True, 'preset_reload': True,
              'output_menu_and_typed_connection': True, 'drag_connection': True,
              'credits_spent': 0, 'graph': state, 'keymap': priority,
              'screenshots': str(OUT)}
    (OUT / 'state-evidence.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    run_scenario('moodboard_drawer_resize_links_e2e', run)
