#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""No-credit file-load recovery for deferred picker and reconstruction exports.

Run against an isolated QA app using QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT as in render_archive_coordination_e2e.py. Creates a local
asset fixture, defers work under a render reservation, loads a clean file,
then generates and saves a real picker thumbnail in the new document.
"""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

IMPORTS = '''
import os, uuid
from pathlib import Path
from types import SimpleNamespace
from mixar.modules.common.render_coordinator import core as slot
from mixar.modules.space_mixie_chat.core import asset_choice_previews as picker
from mixar.modules.moodboard.core.scene_asset_exporter import (
    export_object_to_asset_library, schedule_object_export)
'''

SETUP = IMPORTS + '''
assert os.environ.get('MIXAR_QA') == '1'
assert not slot.busy()
root = Path(os.environ['MIXAR_QA_OUT']) / ('load-coordination-' + uuid.uuid4().hex[:8])
library = root / 'library'
library.mkdir(parents=True)
(root / 'discarded').mkdir()
with bpy.context.temp_override(window=drv.main_window()):
    obj = bpy.context.scene.objects.get('Cube')
    assert obj is not None
    assert export_object_to_asset_library(obj, 'QA cube', str(library))
    blend = next(library.rglob('*.blend'))
    with bpy.data.libraries.load(str(blend), assets_only=True) as (source, dest):
        name = source.objects[0]
    lib_name = 'QA load ' + uuid.uuid4().hex[:8]
    bpy.context.preferences.filepaths.asset_libraries.new(name=lib_name, directory=str(library))
    f = drv._load_qa = SimpleNamespace(root=root, candidate=dict(
        asset_name=name, library=lib_name, blend_file=str(blend.relative_to(library)), type='MESH'))
    slot.acquire('qa-held-render')
    action = SimpleNamespace(asset_name=name, library=lib_name,
        blend_file=f.candidate['blend_file'], asset_type='MESH', value='cube', image='')
    picker.schedule(bpy.context.scene, SimpleNamespace(bubble_id='old', action_items=[action]))
    schedule_object_export(obj, 'Must be discarded', str(root / 'discarded'))
assert picker._process_next() == 0.25
assert picker._queue and picker._timer_running
result = str(root)
'''

RESTART = IMPORTS + '''
f = drv._load_qa
assert not slot.busy()
assert not picker._queue and not picker._timer_running
assert not list((f.root / 'discarded').rglob('*.blend'))
with bpy.context.temp_override(window=drv.main_window()):
    scene = bpy.context.scene
    msg = scene.mixie_chat_messages.add()
    msg.bubble_id = 'qa-new-picker'
    action = msg.action_items.add()
    for name in ('asset_name', 'library', 'blend_file'):
        setattr(action, name, f.candidate[name])
    action.asset_type = 'MESH'
    action.value = 'cube'
    picker.schedule(scene, msg)
    f.scene_name = scene.name
assert bpy.app.timers.is_registered(picker._process_next)
result = True
'''

VERIFY = IMPORTS + '''
f = drv._load_qa
scene = bpy.data.scenes[f.scene_name]
msg = next(m for m in scene.mixie_chat_messages if m.bubble_id == 'qa-new-picker')
assert msg.action_items[0].image == picker.image_name_for(f.candidate)
img = bpy.data.images[msg.action_items[0].image]
assert min(img.size) >= 32
pixels = list(img.pixels)
assert max(pixels[0::4]) > min(pixels[0::4]) + 0.1
path = f.root / 'picker-after-load.png'
img.filepath_raw = str(path)
img.file_format = 'PNG'
img.save()
assert not picker._queue and not picker._timer_running
assert not list((f.root / 'discarded').rglob('*.blend'))
result = {'picker_thumbnail': str(path), 'stale_export_discarded': True}
'''


def run(qa):
    qa.step('login', qa.cmd, 'wait_login', timeout=60)
    qa.step('clean_scene', qa.cmd, 'reset_state')
    qa.step('reconnect', qa.cmd, 'wait_login', timeout=60)
    qa.step('defer_picker_and_export', qa.eval, SETUP)
    qa.step('load_new_file', qa.cmd, 'reset_state')
    qa.step('reconnect_new_file', qa.cmd, 'wait_login', timeout=60)
    qa.step('restart_picker', qa.eval, RESTART)
    qa.step('wait_thumbnail', qa.wait,
            "not __import__('mixar.modules.space_mixie_chat.core.asset_choice_previews', fromlist=['_timer_running'])._timer_running")
    return qa.step('verify_thumbnail_and_discard', qa.eval, VERIFY)


if __name__ == '__main__':
    run_scenario('render_coordination_load', run)
