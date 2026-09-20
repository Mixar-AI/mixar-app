#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit Library scrolling with real local assets in an isolated QA app.

QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/library_scroll_e2e.py
Wheel/trackpad/key/drag events use live native widget geometry. No backend calls.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixar-library-scroll')).resolve()
WM = 'bpy.context.window_manager'
TILES = "drv.find(surface='library_tile')"
RAIL = "drv.find(area_type='AGENT_BUBBLE',text='QA Library 00')[0]"


def pause(qa, seconds=.3):
    qa.eval(f'def wait():\n    yield {seconds}\n    return True\nresult=wait()')


def visible(qa):
    return qa.eval(f"result=[h['value'].rsplit('/',1)[-1] for h in {TILES}]")


def rect(qa, name, surface='library_tile'):
    return qa.eval(f"result=next(h['rect'] for h in drv.find(surface={surface!r}) "
                   f"if h['value'].endswith({name!r}))")


def capture(qa, name):
    from PIL import Image
    path = OUT / (name + '.png')
    qa.cmd('snap', path=str(path),
           target={'area_type': 'AGENT_BUBBLE', 'prop': 'mixar_generations_scroll'}, margin=2000)
    if name in ('first', 'last'):
        # Check native scrollbar pixels as well as RNA: a 0–1 range clamps
        # Blender's paint denominator to 2 and strands the thumb halfway down.
        bar = qa.find(prop='mixar_generations_scroll')['widgets'][0]['rect']
        frame = Image.open(path).convert('RGB')
        x = int((bar[0] + bar[2]) / 2)
        top, bottom = frame.height - bar[3], frame.height - bar[1]
        reds = [frame.getpixel((x, y))[0] for y in range(top + 2, bottom - 2)]
        peak = max(reds)
        assert peak > 40, 'Scrollbar thumb did not render'
        thumb = [i / len(reds) for i, red in enumerate(reds) if red > peak * .8]
        assert (max(thumb) < .1 if name == 'first' else min(thumb) > .9), thumb


def input_at(qa, key, target=None, count=1, pan=0):
    target = target or f'{TILES}[0]'
    qa.eval(f"hit={target}\nx,y=map(int,hit['center'])\nw=hit['_win']\n"
            "def events():\n    drv.move_to(w,x,y)\n    yield .1\n"
            f"    for _ in range({count}):\n"
            + (f"        drv._sim(w,type='MOUSEMOVE',value='NOTHING',x=x,y=y-{pan})\n"
               "        yield .05\n" if pan else '')
            + f"        drv._sim(w,type={key!r},value={'NOTHING' if pan else 'PRESS'!r},x=x,y=y)\n"
            "        yield .08\n    return True\nresult=events()")
    pause(qa)


def fixture(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
            "assert not drv.main_window().scene.mixie_chat_is_busy\n"
            "bpy.context.preferences.view.show_tooltips=False\nresult=True")
    qa.eval(f'''from pathlib import Path
import colorsys, math
root=Path({str(OUT / 'fixtures')!r})
materials=set()
for i in range(257):
    material=bpy.data.materials.new(f"QA Asset {{i:03d}}")
    material.asset_mark()
    rgb=colorsys.hsv_to_rgb(i/257, .75, .85)
    material.diffuse_color=(*rgb,1)
    preview=material.preview_ensure()
    preview.image_size=(32,32)
    pixels=[]
    for y in range(32):
        for x in range(32):
            r=((x-15.5)/15)**2+((y-15.5)/15)**2
            light=.3+.7*math.sqrt(max(0,1-r))
            pixels.extend((*[c*light for c in rgb],1) if r<1 else (0,0,0,1))
    preview.image_pixels_float=pixels
    materials.add(material)
for i in range(20):
    path=root/f"library-{{i:02d}}"
    path.mkdir(parents=True,exist_ok=True)
    if i==0:
        bpy.data.libraries.write(str(path/'assets.blend'),materials,fake_user=True)
    bpy.ops.preferences.asset_library_add(directory=str(path))
    bpy.context.preferences.filepaths.asset_libraries[-1].name=f"QA Library {{i:02d}}"
with bpy.context.temp_override(window=drv.main_window()):
    bpy.ops.mixar.agent_bubble_show_window()
result=True''')
    pause(qa)
    qa.eval(f"{WM}.mixar_bubble_tab='GENERATIONS'\n"
            f"{WM}.mixar_generations_source='LIBRARY'\n"
            f"{WM}.mixar_generations_library='QA Library 00'\n"
            "h=drv.find(area_type='AGENT_BUBBLE',text='Agent chat')[0]\n"
            "with bpy.context.temp_override(window=h['_win']):\n"
            "    bpy.ops.mixar.bubble_set_size(width=678,height=500)\nresult=True")
    qa.wait(f'len({TILES})>0', timeout=30)
    pause(qa, 1.0)


def run(qa):
    qa.wait(f"hasattr({WM},'mixar_generations_scroll')", timeout=30)
    qa.step('local_asset_and_library_overflow_fixture', fixture, qa)
    first = visible(qa)
    assert first and 'QA Asset 000' in first, first
    capture(qa, 'first')
    selected = qa.eval(f'result={WM}.mixar_generations_selected')

    original_row = rect(qa, 'QA Asset 004')
    first_row = rect(qa, 'QA Asset 000')
    pitch = first_row[1] - original_row[1]

    def wheel():
        input_at(qa, 'WHEELDOWNMOUSE')
        delta = rect(qa, 'QA Asset 004')[1] - original_row[1]
        assert 1 < delta < pitch, delta
        assert 'QA Asset 000' in visible(qa)
        input_at(qa, 'WHEELUPMOUSE')
        assert visible(qa) == first
    qa.step('wheel_moves_content_without_row_snapping', wheel)

    def trackpad():
        from PIL import Image, ImageChops, ImageStat
        input_at(qa, 'TRACKPADPAN', pan=10)
        moved = rect(qa, 'QA Asset 004')
        assert abs(moved[1] - original_row[1] - 10) <= 1, (original_row, moved)
        # The first tile stays full size in paint, with only its visible hit area exposed.
        cropped = rect(qa, 'QA Asset 000')
        assert abs(cropped[3] - first_row[3]) <= 1
        assert abs(cropped[1] - first_row[1] - 10) <= 1
        capture(qa, 'tiny-pan')
        before = Image.open(OUT / 'first.png').convert('RGB')
        after = Image.open(OUT / 'tiny-pan.png').convert('RGB')
        x0, y0, x1, y1 = original_row
        box = (x0 + 8, before.height - y1 + 8, x1 - 8, before.height - y0 - 8)
        shifted = (box[0], box[1] - 10, box[2], box[3] - 10)
        error = ImageStat.Stat(ImageChops.difference(before.crop(box), after.crop(shifted))).mean
        assert max(error) < 2, error
        input_at(qa, 'TRACKPADPAN', pan=-10)
        assert abs(rect(qa, 'QA Asset 004')[1] - original_row[1]) <= 1
        library_before = rect(qa, 'QA Library 00', 'library_source')
        input_at(qa, 'TRACKPADPAN', target=RAIL, pan=3)
        library_after = rect(qa, 'QA Library 00', 'library_source')
        assert abs(library_after[1] - library_before[1] - 3) <= 1
        assert rect(qa, 'QA Asset 004') == original_row
        input_at(qa, 'HOME', target=RAIL)
        input_at(qa, 'HOME')
        assert visible(qa) == first
    qa.step('small_trackpad_deltas_move_pixels_and_hit_targets', trackpad)

    def partial_row():
        input_at(qa, 'TRACKPADPAN', pan=int(pitch / 3))
        capture(qa, 'partial-row')
        bounds = qa.find(prop='mixar_generations_scroll')['widgets'][0]['rect']
        hits = qa.find(surface='library_tile')['widgets']
        assert all(h['rect'][1] >= bounds[1] and h['rect'][3] <= bounds[3] + 1 for h in hits)
        qa.click(surface='library_tile', text='QA Asset 000', contains=True)
        assert qa.eval(f'result={WM}.mixar_generations_selected').endswith('/QA Asset 000')
        qa.eval(f"{WM}.mixar_generations_selected={selected!r}\nresult=True")
        input_at(qa, 'HOME')
    qa.step('partial_rows_clip_paint_and_remain_selectable', partial_row)

    def keyboard():
        input_at(qa, 'PAGE_DOWN')
        assert visible(qa) != first
        input_at(qa, 'END')
        assert 'QA Asset 256' in visible(qa), visible(qa)
        capture(qa, 'last')
        input_at(qa, 'WHEELDOWNMOUSE', count=3)
        assert qa.eval(f'result={WM}.mixar_generations_scroll') == 100
        assert qa.eval(f'result={WM}.mixar_generations_selected') == selected
        qa.click(surface='library_tile', text='QA Asset 256', contains=True)
        assert qa.eval(f'result={WM}.mixar_generations_selected').endswith('/QA Asset 256')
        input_at(qa, 'HOME')
    qa.step('all_257_assets_reachable_and_selection_preserved', keyboard)

    def scrollbar():
        before = rect(qa, 'QA Asset 004')
        qa.eval("h=drv.find(prop='mixar_generations_scroll')[0]\n"
                "x0,y0,x1,y1=h['rect']\nx=int((x0+x1)/2)\nw=h['_win']\n"
                "def drag():\n    drv.move_to(w,x,int(y1-3))\n    yield .1\n"
                "    drv._sim(w,type='LEFTMOUSE',value='PRESS',x=x,y=int(y1-3))\n"
                "    yield .1\n    drv._sim(w,type='MOUSEMOVE',value='NOTHING',x=x,y=int(y1-5))\n"
                "    yield .1\n    drv._sim(w,type='LEFTMOUSE',value='RELEASE',x=x,y=int(y1-5))\n"
                "    yield .2\n    return True\nresult=drag()")
        movement = rect(qa, 'QA Asset 004')[1] - before[1]
        assert 1 < movement < pitch, movement
        input_at(qa, 'HOME')
        qa.eval("h=drv.find(prop='mixar_generations_scroll')[0]\n"
                "x0,y0,x1,y1=h['rect']\nx=int((x0+x1)/2)\nw=h['_win']\n"
                "def drag():\n    drv.move_to(w,x,int(y1-3))\n    yield .1\n"
                "    drv._sim(w,type='LEFTMOUSE',value='PRESS',x=x,y=int(y1-3))\n"
                "    yield .1\n    drv._sim(w,type='MOUSEMOVE',value='NOTHING',x=x,y=int(y0+2))\n"
                "    yield .1\n    drv._sim(w,type='LEFTMOUSE',value='RELEASE',x=x,y=int(y0+2))\n"
                "    yield .2\n    return True\nresult=drag()")
        assert 'QA Asset 256' in visible(qa), visible(qa)
    qa.step('native_scrollbar_drag_reaches_end', scrollbar)

    def filtering():
        qa.eval(f"{WM}.mixar_generations_filter='IMAGE'\nresult=True")
        assert qa.eval(f'result={WM}.mixar_generations_scroll') == 0
        assert not visible(qa)
        qa.eval(f"{WM}.mixar_generations_filter='ALL'\nresult=True")
        pause(qa)
        assert visible(qa) == first
    qa.step('filter_resets_grid_and_handles_empty_results', filtering)

    def rail():
        target = "drv.find(prop='mixar_generations_library_scroll')[0]"
        input_at(qa, 'WHEELDOWNMOUSE', target=target)
        assert qa.eval(f'result={WM}.mixar_generations_library_scroll') > 0
        input_at(qa, 'END', target=target)
        assert qa.find(text='QA Library 19', surface='library_source')['total']
        assert qa.find(op='MIXAR_OT_generations_add_library')['total']
        assert visible(qa) == first
        capture(qa, 'rail-last')
        qa.click(text='QA Library 19', surface='library_source')
        assert qa.eval(f'result={WM}.mixar_generations_library') == 'QA Library 19'
        qa.eval(f"{WM}.mixar_generations_library='QA Library 00'\nresult=True")
    qa.step('all_20_libraries_reachable_add_button_pinned', rail)

    def resize():
        for height in (300, 580):
            qa.eval("h=drv.find(area_type='AGENT_BUBBLE',text='Agent chat')[0]\n"
                    "with bpy.context.temp_override(window=h['_win']):\n"
                    f"    bpy.ops.mixar.bubble_set_size(width=678,height={height})\nresult=True")
            pause(qa)
            input_at(qa, 'END')
            assert 'QA Asset 256' in visible(qa)
            capture(qa, f'resize-{height}')
    qa.step('resize_keeps_last_asset_reachable', resize)

    def reload_keymap():
        qa.eval("path=bpy.utils.preset_find('Blender','keyconfig',ext='.py')\n"
                "assert bpy.ops.preferences.keyconfig_activate(filepath=path)=={'FINISHED'}\n"
                "result=True")
        pause(qa)
        input_at(qa, 'HOME')
        assert 'QA Asset 000' in visible(qa)
        input_at(qa, 'WHEELDOWNMOUSE')
        assert qa.eval(f'result={WM}.mixar_generations_scroll') > 0
    qa.step('addon_bindings_survive_keyconfig_reload', reload_keymap)
    def ai_generations():
        qa.eval("for i in range(17):\n"
                "    collection=bpy.data.collections.new(f'QA Splat {i:02d}')\n"
                "    collection['mixar_splat_world']=True\n"
                f"{WM}.mixar_generations_source='AI'\n"
                f"{WM}.mixar_generations_filter='SPLAT'\nresult=True")
        pause(qa)
        input_at(qa, 'END')
        assert 'splat:QA Splat 16' in visible(qa)
        capture(qa, 'ai-last')
        qa.eval(f"{WM}.mixar_generations_source='LIBRARY'\n"
                f"{WM}.mixar_generations_filter='ALL'\nresult=True")
    qa.step('ai_generations_share_grid_scrolling', ai_generations)
    return {'assets':257, 'libraries':20, 'screenshots':str(OUT)}


if __name__ == '__main__':
    run_scenario('library_scroll_e2e', run)
