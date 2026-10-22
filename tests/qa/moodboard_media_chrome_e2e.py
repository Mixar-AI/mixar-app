#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native media titles/actions: fixed font, toolbar skin, rename/preview/export.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Requires Pillow and an
isolated Dev app. Eval sets placement fixtures; all feature actions use native
events. No generation is submitted; export's file browser is cancelled.

On macOS, screen.screenshot can omit standalone-editor tooltip regions even
when the popup is visible on screen. Inspect those tooltips with an OS window
capture as well; the framebuffer PNG alone cannot establish their absence.
"""

from PIL import Image, ImageChops

from moodboard_drawer_e2e import (
    OUT, SCENE, drop, geometry, png, require, run_scenario, target, toggle,
)
from moodboard_drawer_tools_e2e import resize

OPS = ['MIXIE_OT_moodboard_rename_media', 'MIXIE_OT_moodboard_preview_media',
       'MIXIE_OT_moodboard_export_images']


def context(host):
    kind = 'TOOL_PROPS' if host == 'VIEW_3D' else 'WINDOW'
    return f"""
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=={host!r})
region=next(r for r in area.regions if r.type=={kind!r})
media=win.scene.mixie_moodboard_images[0]
"""


def center(qa, host, initial=False):
    qa.eval(context(host) + f"""
from mixar.modules.moodboard.constants import MOODBOARD_IMAGE_BASE_SIZE
if {initial!r}:
    a=region.view2d.region_to_view(0,0)
    b=region.view2d.region_to_view(1000,0)
    media.scale=(b[0]-a[0])/MOODBOARD_IMAGE_BASE_SIZE
w=media.scale*MOODBOARD_IMAGE_BASE_SIZE
h=w*media.image.size[1]/media.image.size[0]
cx,cy=region.view2d.region_to_view(region.width*.52,region.height*.48)
media.position_x,media.position_y=cx-w/2,cy-h/2
area.tag_redraw()
bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
result=True
""")


def capture_title(qa, host, media_id, index):
    center(qa, host)
    path = OUT / f'{host}-title-{index}.png'
    title = target(qa, 'moodboard_media_title', text=media_id, area_type=host)
    actions = [qa.find(op=op, area_type=host)['widgets'][0] for op in OPS]
    require(title['rect'][2] <= min(w['rect'][0] for w in actions),
            'Media title overlaps its action buttons')
    qa.cmd('snap', path=str(path), target={'surface':'moodboard_media_title',
                                         'text':media_id, 'area_type':host}, margin=0)
    image = Image.open(path).convert('RGB')
    r, g, b = image.split()
    ink = ImageChops.darker(ImageChops.darker(r,g),b).point(lambda v:255 if v>165 else 0)
    bounds = ink.getbbox()
    require(bounds is not None, 'Image name is not visible')
    card = target(qa, 'moodboard_media', text=media_id, area_type=host)['rect']
    return {'ink':[bounds[2]-bounds[0], bounds[3]-bounds[1]],
            'width':card[2]-card[0], 'actions':[w['layout_rect'] for w in actions]}


EXPECTED_TIPS = {
    # Introspection exports uiBut.tip (the RNA description), while the hover
    # popup executes the custom native tooltip callback. Inspect the captured
    # popups below to verify that callback does not repeat the RNA description.
    OPS[0]: "Rename this image or video in place. Enter applies the new name, "
            "Escape keeps the old one",
    OPS[1]: "Open this image or video in its own preview window. "
            "Several can be open at once",
    OPS[2]: "Save selected images or copy selected videos to disk",
}


def tooltips(qa, host):
    for op, expected in EXPECTED_TIPS.items():
        query = {'op': op, 'area_type': host}
        actual = qa.find(**query)['widgets'][0]['tip']
        require(actual == expected, f'{op} repeated or changed help: {actual!r}')
        qa.eval(f"""
def hover():
    widget=drv.find_one(**{query!r})
    x,y=drv.pick_click_point(widget)
    drv.move_to(widget['_win'],x,y-50)
    yield .2
    # Native UI suppresses tips after an action until pointer motion restores
    # them. Cross its movement threshold inside the button before settling.
    dx=min(15, max(1, (widget['rect'][2]-widget['rect'][0])//4))
    drv.move_to(widget['_win'],x-dx,y)
    yield .2
    drv.move_to(widget['_win'],x+dx,y)
    yield .2
    drv.move_to(widget['_win'],x,y)
    yield 1.5
    return True
result=hover()
""")
        qa.cmd('snap', path=str(OUT/f'{host}-{op}-tooltip.png'), area=host)


def chrome(qa, host, media_id):
    rail = qa.find(op='MIXIE_OT_moodboard_add_textbox', area_type=host)['widgets'][0]
    for op in OPS:
        widget = qa.find(op=op, area_type=host)['widgets'][0]
        require(all(widget[key] == rail[key]
                    for key in ('mixar_theme','mixar_component','mixar_variant')),
                'Image actions do not use the toolbar styling')
    center(qa, host, initial=True)
    sizes = [capture_title(qa,host,media_id,0)]
    for index, key in enumerate(('WHEELUPMOUSE','WHEELDOWNMOUSE','WHEELDOWNMOUSE'),1):
        panel = target(qa,'moodboard_media', text=media_id, area_type=host)
        qa.eval(f"drv.move_to(drv.main_window(), {panel['center'][0]}, "
                f"{panel['center'][1]}); result=True")
        qa.press(key)
        qa.press(key)
        sizes.append(capture_title(qa,host,media_id,index))
    require(max(s['width'] for s in sizes)-min(s['width'] for s in sizes)>100,
            'Canvas zoom did not change the image dimensions')
    for axis in (0,1):
        require(max(s['ink'][axis] for s in sizes)-min(s['ink'][axis] for s in sizes)<=1,
                f'Canvas zoom changed filename glyph size: {sizes}')
    center(qa,host,initial=True)
    qa.cmd('snap', path=str(OUT/f'{host}-chrome.png'), area=host)
    return sizes


def rename(qa, host, media_id):
    qa.click(op=OPS[0], area_type=host)
    qa.wait(f"bool(drv.find(area_type={host!r},prop='name',but_type='Text'))",timeout=5)
    qa.cmd('type',text='reference.png')
    qa.press('RET')
    qa.wait(f"{SCENE}.mixie_moodboard_images[0].image.name=='reference.png'", timeout=5)
    qa.wait(f"bool(drv.find(surface='moodboard_media_title',text={media_id!r}))",timeout=5)
    qa.click(op=OPS[0], area_type=host)
    qa.cmd('type',text='Discard this change')
    qa.press('ESC')
    require(qa.eval(f'result={SCENE}.mixie_moodboard_images[0].image.name') == 'reference.png',
            'Escape did not cancel the inline rename')


def preview_export(qa, host):
    before = qa.eval('result=[w.as_pointer() for w in bpy.context.window_manager.windows]')
    qa.click(op=OPS[1], area_type=host)
    qa.wait(f'len(bpy.context.window_manager.windows)=={len(before)+1}',timeout=5)
    require(qa.eval(f"result=any(a.type=='IMAGE_EDITOR' and "
                    f"a.spaces.active.image=={SCENE}.mixie_moodboard_images[0].image "
                    "for w in bpy.context.window_manager.windows "
                    f"if w.as_pointer() not in {before!r} for a in w.screen.areas)"),
            'Preview did not open the selected reference')
    # Close only the preview window created by this test.
    qa.eval(f"win=next(w for w in bpy.context.window_manager.windows "
            f"if w.as_pointer() not in {before!r})\n"
            "with bpy.context.temp_override(window=win):\n"
            "    bpy.ops.wm.window_close()\nresult=True")
    qa.click(op=OPS[2], area_type=host)
    qa.wait("bool(drv.find(op='FILE_OT_cancel'))",timeout=8)
    qa.click(op='FILE_OT_cancel')
    qa.wait("not drv.find(op='FILE_OT_cancel')",timeout=5)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"), 'Use isolated QA')
    require(qa.eval(f'result=len({SCENE}.mixie_moodboard_images)') == 0, 'Use a fresh scene')
    if geometry(qa)['amount'] < .98:
        toggle(qa,1)
    resize(qa,850)
    path = png(OUT/'outputroom.png',(58,84,102),320,180)
    media_id = drop(qa,path,target={'surface':'moodboard_drawer_panel'})
    qa.click(surface='moodboard_media',text=media_id)
    results = {}
    for host in ('VIEW_3D','MIXIE'):
        if host == 'MIXIE':
            qa.eval("next(a for a in drv.main_window().screen.areas "
                    "if a.type=='VIEW_3D').type='MIXIE'; result=True")
        center(qa,host,initial=True)
        results[host]=qa.step(host+'-title-zoom-and-skin',chrome,qa,host,media_id)
        qa.step(host+'-single-tooltip-description',tooltips,qa,host)
        qa.step(host+'-rename-apply-cancel',rename,qa,host,media_id)
        qa.step(host+'-preview-export-cancel',preview_export,qa,host)
    return {'backend_submissions':0,'title_pixels':results}


if __name__ == '__main__':
    run_scenario('moodboard_media_chrome_e2e',run)
