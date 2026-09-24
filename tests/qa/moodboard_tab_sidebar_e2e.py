#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit Moodboard grip/N-panel regression on an isolated macOS Dev app.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Uses native grip targets
and N-key events; the window-size fixture only changes this QA process.
"""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
sys.path.insert(0, str(Path(__file__).parent))
from moodboard_drawer_e2e import SETUP, geometry, target, toggle
from zen_ui_fixes_e2e import native


def sidebar(qa, visible):
    current = qa.eval(SETUP + 'result=area.spaces.active.show_region_ui')
    if current != visible:
        # The viewport has no semantic focus widget; use its own region bounds.
        qa.eval(SETUP + 'drv.move_to(win, viewport.x + viewport.width // 4, '
                'viewport.y + viewport.height // 2); result=True')
        time.sleep(.15)
        qa.press('N')
        qa.wait("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')"
                f'.spaces.active.show_region_ui == {visible}', timeout=4)
        time.sleep(.3)


def anchored(qa, open_drawer=False):
    state = geometry(qa)
    grip = target(qa, 'moodboard_drawer_grip')['rect']
    edge = state['area'][2] - 1
    assert abs(state['drawer'][2] - 1 - edge) <= 1, state
    if open_drawer:
        panel = target(qa, 'moodboard_drawer_panel')['rect']
        assert abs(panel[2] - edge) <= 1, (panel, edge)
        assert abs(panel[0] - grip[2]) <= 1, (panel, grip)
    else:
        assert abs(grip[2] - edge) <= 1, (grip, edge)
        # The sidebar must not put category tabs behind the closed grip.
        sidebar_edge = qa.eval(SETUP +
            'ui=next(r for r in area.regions if r.type=="UI"); '
            'result=ui.x+ui.width if area.spaces.active.show_region_ui else None')
        if sidebar_edge is not None:
            assert sidebar_edge <= grip[0] + 1, (sidebar_edge, grip)
    return {'grip': grip, 'drawer': state['drawer'], 'viewport': state['viewport']}


def capture(qa, out, name):
    # Capture native framebuffer crops. Loading screenshot Image datablocks
    # inside Blender would invalidate viewport resources between these shots.
    qa.eval(SETUP + f'''
def capture_frame():
    for region in area.regions:
        region.tag_redraw()
    yield .5
    grip = drv.find_one(surface='moodboard_drawer_grip')['rect']
    x0 = max(area.x, grip[0] - 8)
    y0 = max(area.y, grip[1] - 8)
    x1 = min(area.x + area.width, grip[2] + 8)
    y1 = min(area.y + area.height, grip[3] + 8)
    with bpy.context.temp_override(window=win):
        win.mixar_qa_capture_frame(filepath={str(out / f'{name}.png')!r},
            x=area.x, y=area.y, width=area.width, height=area.height)
        win.mixar_qa_capture_frame(filepath={str(out / f'{name}-grip.png')!r},
            x=x0, y=y0, width=x1-x0, height=y1-y0)
    return True
result=capture_frame()
''')


def sidebar_tabs(qa):
    for label in ('Mixar', 'Tool'):
        query = {'area_type': 'VIEW_3D', 'surface': 'panel_tab', 'text': label}
        hits = qa.find(**query)['widgets']
        assert len(hits) == 1, hits
        if not hits[0].get('sel'):
            qa.click(**query)
        qa.wait(f'any(w.get("sel") for w in drv.find(**{query!r}))', timeout=4)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-tab-sidebar'))
    out.mkdir(parents=True, exist_ok=True)
    qa.eval(f'import sys; sys.path.insert(0,{str(Path(__file__).parent)!r}); '
            'bpy.ops.mixar.agent_bubble_purge_windows(); result=True')
    qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    time.sleep(.4)
    if geometry(qa)['amount'] > .02:
        toggle(qa, 0)
    host = native(qa, 'host')
    old_scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    old_sidebar = qa.eval(SETUP + 'result=area.spaces.active.show_region_ui')
    results = []
    try:
        for width, scale in ((1440, 1.0), (900, 1.0), (900, 1.25)):
            native(qa, 'host', size=(width, host[3]))
            qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
            time.sleep(.6)
            sidebar(qa, False)
            closed = qa.step(f'edge_without_sidebar_{width}_{scale}', anchored, qa)
            capture(qa, out, f'closed-{width}-{scale}')
            sidebar(qa, True)
            qa.step(f'sidebar_categories_reachable_{width}_{scale}', sidebar_tabs, qa)
            shown = qa.step(f'edge_with_sidebar_{width}_{scale}', anchored, qa)
            assert closed == shown, (closed, shown)
            capture(qa, out, f'sidebar-{width}-{scale}')
            # These clicks would hit category tabs/fields if visual hit order
            # still followed the ordinary sidebar-first allocation order.
            toggle(qa, 1)
            opened = qa.step(f'click_open_over_sidebar_{width}_{scale}', anchored, qa, True)
            assert opened['viewport'] == closed['viewport']
            capture(qa, out, f'open-{width}-{scale}')
            sidebar(qa, False)
            assert anchored(qa, True) == opened
            sidebar(qa, True)
            assert anchored(qa, True) == opened
            toggle(qa, 0)
            qa.step(f'click_close_over_sidebar_{width}_{scale}', anchored, qa)
            results.append({'width': width, 'ui_scale': scale, 'closed': shown, 'open': opened})

        # Drag the real grip to resize while the N-panel remains open.
        toggle(qa, 1)
        grip = target(qa, 'moodboard_drawer_grip')
        original_width = qa.eval('result=bpy.context.window_manager.mixar_moodboard_drawer_width')
        qa.cmd('drag', **{'from': {'surface': 'moodboard_drawer_grip'},
                          'to': {'x': grip['center'][0] - 100, 'y': grip['center'][1]},
                          'steps': 12})
        time.sleep(.4)
        resized = qa.step('drag_keeps_right_edge_with_sidebar', anchored, qa, True)
        width = qa.eval('result=bpy.context.window_manager.mixar_moodboard_drawer_width')
        assert width > original_width, (width, original_width)
        toggle(qa, 0)
        toggle(qa, 1)
        assert anchored(qa, True) == resized
        capture(qa, out, 'resized-with-sidebar')
        toggle(qa, 0)
        qa.step('resized_width_survives_close_reopen', lambda: width)
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={old_scale}; result=True')
        native(qa, 'host', size=host[2:])
        time.sleep(.4)
        sidebar(qa, old_sidebar)
    return {'backend_calls': 0, 'cases': results, 'snaps': str(out)}


if __name__ == '__main__':
    run_scenario('moodboard_tab_sidebar_e2e', run)
