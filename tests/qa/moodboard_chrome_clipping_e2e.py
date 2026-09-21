#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit native regression: canvas content continues behind floating controls.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT; requires Pillow.
Native pan puts cards under the rail, templates and N-panel. A temporary
position fixture hides the card for pixel comparisons against the same view.
"""

from PIL import Image, ImageChops

from moodboard_drawer_e2e import OUT, SCENE, geometry, require, run_scenario, target, toggle
from moodboard_drawer_tools_e2e import resize
from moodboard_node_layout_e2e import BLOCK, SETTINGS, inside
from moodboard_node_position_e2e import card, center_fixture, context, offsets, pan
from moodboard_redesign_e2e import ADD, BOARD


def redraw(qa, host):
    qa.eval(context(host) + """
area.tag_redraw()
bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=2)
result=True
""")


def content(qa, host):
    return target(qa, 'moodboard_canvas', area_type=host)['rect']


def snapshot(qa, host, name):
    path = OUT / f'{host}-{name}.png'
    reply = qa.cmd('snap', path=str(path), area=host)
    return Image.open(path).convert('RGB'), reply['cropped_to']


def crop(image, origin, rect):
    x0, y0, _, y1 = origin
    a, b, c, d = [round(v) for v in rect]
    return image.crop((a-x0, y1-d, c-x0, y1-b))


def assert_targets(qa, host):
    canvas = content(qa, host)
    kind = 'TOOL_PROPS' if host == 'VIEW_3D' else 'WINDOW'
    widgets = qa.find(area_type=host, region_type=kind, limit=1000)['widgets']
    painted = qa.eval(context(host) +
        'result=[region.x,region.y,region.x+region.width,region.y+region.height]')
    for widget in widgets:
        surface = widget.get('surface', '')
        if ((surface.startswith('moodboard_') and not surface.startswith('moodboard_drawer'))
                or widget.get('block') == BLOCK):
            bounds = painted if widget.get('block') == BLOCK else canvas
            require(inside(widget['rect'], bounds), f'Target escapes its host: {widget}')


def edge(qa, host, scale, side, suffix=""):
    center_fixture(qa, host, size=True)
    original = offsets(qa, host)
    x0, y0, x1, y1 = content(qa, host)
    a, b, c, d = card(qa, host)
    dx = x0-a-180 if side == 'left' else x1-c+180 if side == 'right' else 0
    dy = y1-d+180 if side == 'top' else 0
    pan(qa, host, dx, dy)
    # Capture after native pan, with the pointer safely off the card/chrome.
    qa.eval(context(host) + f"drv.move_to(win,{int(x1-100)},{int(y0+60)});result=True")
    redraw(qa, host)
    actual = offsets(qa, host)
    require(actual, 'Visible card lost all controls')
    for key, rect in actual.items():
        require(all(abs(a-b) <= 2 for a, b in zip(rect, original[key])),
                f'{key} reflowed under {side} chrome')
    shown, origin = snapshot(qa, host, f'{scale}-{side}{suffix}')
    position = qa.eval(context(host) + 'result=[node.position_x,node.position_y]')
    qa.eval(context(host) + 'node.position_x=node.position_y=1000000;result=True')
    redraw(qa, host)
    hidden, _ = snapshot(qa, host, f'{scale}-{side}{suffix}-baseline')
    qa.eval(context(host) + f'node.position_x,node.position_y={position!r};result=True')
    redraw(qa, host)
    # Opaque button interiors stay on top while the surrounding canvas is
    # still visible. Read the actual native layout instead of re-creating it.
    kind = 'TOOL_PROPS' if host == 'VIEW_3D' else 'WINDOW'
    widgets = qa.find(area_type=host, region_type=kind, limit=1000)['widgets']
    chrome = [w for w in widgets if w.get('block', '').startswith('MIXIE_PT_canvas_')]
    require(chrome, 'Missing floating toolbar')
    for widget in chrome:
        a, b, c, d = widget['rect']
        inset = min(c-a, d-b)*.3
        rect = (a+inset, b+inset, c-inset, d-inset)
        diff = ImageChops.difference(crop(shown, origin, rect), crop(hidden, origin, rect))
        require(diff.getbbox() is None, f"Node covered toolbar button: {widget.get('text')}")
    a, b, c, d = card(qa, host)
    if side == 'left':
        rail = next(w for w in chrome if w['block'] == 'MIXIE_PT_canvas_tools')['rect']
        sample_x = (rail[0]+rail[2])/2
        # Sample the frame padding: an empty prompt uses the canvas color.
        sample_y = b+10
        sample = (sample_x-4, sample_y-3, sample_x+4, sample_y+3)
    elif side == 'top':
        top = next(w for w in chrome if w['block'].startswith('MIXIE_PT_canvas_templates'))['rect']
        sample_x = c-10
        sample = (sample_x-3, top[3]+4, sample_x+3, y1-4)
    else:
        sample = None
    if sample:
        diff = ImageChops.difference(crop(shown, origin, sample), crop(hidden, origin, sample))
        require(diff.getbbox() is not None, f'Canvas still cut off at the {side} toolbar margin')
    assert_targets(qa, host)
    if side == 'left':
        # Below the actual buttons, the former toolbar column is usable canvas.
        qa.eval(context(host) + "node.selected=False;win.scene.mixie_moodboard_active_node_id='';result=True")
        redraw(qa, host)
        qa.cmd('click_xy', x=int(sample_x), y=int(sample_y))
        qa.wait(f'{SCENE}.mixie_moodboard_action_nodes[0].selected', timeout=4)
    return {'content': content(qa, host), 'stable_offsets': actual, 'exposed_sample': sample}


def toolbar_precedence(qa, host, scale):
    center_fixture(qa, host, size=True)
    button = qa.find(**BOARD, area_type=host)['widgets'][0]
    settings = qa.find(op=SETTINGS, area_type=host, region_type=(
        'TOOL_PROPS' if host == 'VIEW_3D' else 'WINDOW'))['widgets'][0]
    dx, dy = [a-b for a, b in zip(button['center'], settings['center'])]
    qa.eval(context(host) + f"""
a=region.view2d.region_to_view(0,0)
b=region.view2d.region_to_view({dx},{dy})
node.position_x+=b[0]-a[0]
node.position_y+=b[1]-a[1]
result=True
""")
    redraw(qa, host)
    snapshot(qa, host, f'{scale}-toolbar-above-settings')
    # The model Settings button is directly underneath this Board menu.
    # Opening the menu must never edit/select the covered node control.
    qa.click(**BOARD, area_type=host)
    require(qa.find(op='MIXIE_OT_moodboard_frame', popup=True)['widgets'],
            'Node Settings intercepted a toolbar click')
    qa.press('ESC')
    return {'toolbar_above_node_control': True}


def sidebar(qa, host, visible):
    current = qa.eval(context(host) + "result=any(r.type=='UI' and r.width>1 for r in area.regions)")
    if current != visible:
        # N remains a region shortcut when hovering the toolbar, too.
        button = qa.find(**BOARD, area_type=host)['widgets'][0]
        x, y = button['center']
        qa.eval(context(host) + f'drv.move_to(win,{int(x)},{int(y)});result=True')
        qa.press('N')
        qa.wait("any(r.type=='UI' and r.width>1 for r in next(a for a in "
                f"drv.main_window().screen.areas if a.type=={host!r}).regions)=={visible}", timeout=5)
        redraw(qa, host)


def run_cases(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"), 'Use isolated QA')
    qa.cmd('wait_login', timeout=90)
    qa.wait("__import__('mixar.bootstrap.generation_catalog_cache',fromlist=['is_loaded']).is_loaded()",
            timeout=45)
    qa.eval('bpy.ops.mixar.agent_bubble_purge_windows();result=True')
    if geometry(qa)['amount'] < .98:
        toggle(qa, 1)
    resize(qa, 850)
    qa.click(op=ADD, text='Generate Image', region_type='TOOL_PROPS')
    result = {}
    for host in ('VIEW_3D', 'MIXIE'):
        if host == 'MIXIE':
            qa.eval("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').type='MIXIE';result=True")
            qa.wait("bool(drv.find(area_type='MIXIE',surface='moodboard_canvas'))", timeout=5)
        for scale in (1.0, 1.25):
            qa.eval(f'bpy.context.preferences.view.ui_scale={scale};result=True')
            redraw(qa, host)
            if host == 'MIXIE':
                sidebar(qa, host, True)
            for side in ('left', 'top', 'right'):
                key = f'{host}-{scale}-{side}'
                result[key] = qa.step(key, edge, qa, host, scale, side)
            if host == 'MIXIE':
                before = content(qa, host)
                sidebar(qa, host, False)
                require(content(qa, host)[2] > before[2], 'Closing N-panel did not release canvas space')
                result[f'{host}-{scale}-sidebar-closed'] = qa.step(
                    f'{host}-{scale}-sidebar-closed', edge, qa, host, scale, 'right', '-closed')
            qa.step(f'{host}-{scale}-toolbar-precedence', toolbar_precedence, qa, host, scale)
        # Chrome remains clickable above content and the native menu still frames content.
        qa.click(**BOARD, area_type=host)
        qa.click(op='MIXIE_OT_moodboard_frame', popup=True)
    require(qa.eval(f"result=all(n.state=='DRAFT' and not n.job_id for n in {SCENE}.mixie_moodboard_action_nodes)"),
            'Unexpected generation')
    return {'backend_submissions': 0, 'cases': result}


def run(qa):
    original_scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    try:
        return run_cases(qa)
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={original_scale};result=True')


if __name__ == '__main__':
    run_scenario('moodboard_chrome_clipping_e2e', run)
