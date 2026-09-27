#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit My Libraries replay: folder media, multi-select, Add N, remove.

QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/library_folder_media_e2e.py

A folder holding only plain PNGs (no .blend) is connected. The grid must list
them with real thumbnails, a click then a second selection must ring both
tiles, "Add 2" must put both on the moodboard, and removing the library must
drop its rail row while leaving the files on disk. No backend calls.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixar-library-folder-media')).resolve()
WM = 'bpy.context.window_manager'
TILES = "drv.find(surface='library_tile')"
FOLDER = OUT / 'fixtures' / 'pictures'


def pause(qa, seconds=.3):
    qa.eval(f'def wait():\n    yield {seconds}\n    return True\nresult=wait()')


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / (name + '.png')),
           target={'area_type': 'AGENT_BUBBLE', 'prop': 'mixar_generations_scroll'},
           margin=2000)


def fixture(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
            "bpy.context.preferences.view.show_tooltips=False\nresult=True")
    qa.eval(f'''from pathlib import Path
root=Path({str(FOLDER)!r})
root.mkdir(parents=True,exist_ok=True)
for i,rgb in enumerate(((1,.2,.2),(.2,1,.2),(.2,.2,1))):
    img=bpy.data.images.new(f"qa_pic_{{i}}",64,64)
    img.pixels=[*rgb,1]*(64*64)
    img.filepath_raw=str(root/f"qa_pic_{{i}}.png")
    img.file_format='PNG'
    img.save()
    bpy.data.images.remove(img)
bpy.ops.preferences.asset_library_add(directory=str(root))
bpy.context.preferences.filepaths.asset_libraries[-1].name="QA Pictures"
with bpy.context.temp_override(window=drv.main_window()):
    bpy.ops.mixar.agent_bubble_show_window()
result=True''')
    pause(qa)
    qa.eval(f"{WM}.mixar_bubble_tab='GENERATIONS'\n"
            f"{WM}.mixar_generations_source='LIBRARY'\n"
            f"{WM}.mixar_generations_library='QA Pictures'\nresult=True")


def run(qa):
    qa.wait(f"hasattr({WM},'mixar_generations_files')", timeout=30)
    qa.step('folder_of_pictures_fixture', fixture, qa)

    # 1. The pictures are listed (they used to read "No assets in this library").
    qa.wait(f"len({TILES})==3", timeout=30)
    values = qa.eval(f"result=sorted(h['value'] for h in {TILES})")
    assert all(v.startswith('file:') and 'qa_pic_' in v for v in values), values
    pause(qa, 1.5)  # deferred thumbnails land
    snap(qa, 'listed')

    # 2. Click selects one; a second selection rings both.
    qa.click(surface='library_tile', value=values[0])
    assert qa.eval(f'result={WM}.mixar_generations_selected') == values[0]
    qa.eval(f"bpy.ops.mixar.generations_select(value={values[1]!r}, extend=True)\nresult=True")
    assert qa.eval(f"result=len({WM}.mixar_generations_multi.split(chr(10)))") == 2
    pause(qa)
    snap(qa, 'two_selected')

    # 3. "Add 2" boards both files.
    before = qa.eval("result=len(bpy.context.scene.mixie_moodboard_images)")
    qa.eval("bpy.ops.mixar.generations_add_selected()\nresult=True")
    qa.wait(f"len(bpy.context.scene.mixie_moodboard_images)=={before}+2", timeout=10)

    # 4. Removing the library drops its row; files stay on disk.
    qa.eval("bpy.ops.mixar.generations_remove_library(library_name='QA Pictures')\nresult=True")
    qa.wait("not drv.find(surface='library_source', text='QA Pictures')", timeout=10)
    assert qa.eval(f"import os\nresult=len(os.listdir({str(FOLDER)!r}))") == 3
    snap(qa, 'removed')


if __name__ == '__main__':
    run_scenario('library_folder_media_e2e', run)
