#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Agent asset picker: the Agent tab swaps its transcript for a Library-style
grid of the top five library matches, and answers through native clicks.

No backend and no credits. The agent's paused ``choice`` question is replayed
through the REAL slot processor with exactly the slots the backend's
SlotTransformer emits for ``request_user_input(asset_options=...)``; the
library is six local .blend assets (the sixth proves the top-five cap); the
answer is captured at the turn transport instead of being streamed. Every
click is a native button rectangle, every assertion reads RNA state, and
every capture is checked for real pixels.

Run on a fresh isolated app with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT.
"""
import json
import os
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

WM = 'bpy.context.window_manager'
BUBBLE = {'area_type': 'AGENT_BUBBLE', 'text': 'Agent chat'}
QUESTION = 'Which dining chair from your library should I use?'
LIBRARY = 'QA Picker Library'

FIXTURE = '''import os, colorsys, math
from pathlib import Path
assert os.environ.get("MIXAR_QA") == "1"
bpy.context.preferences.view.show_tooltips = False
root = Path(ROOT)
root.mkdir(parents=True, exist_ok=True)
objects = set()
for i in range(6):
    mesh = bpy.data.meshes.new(f"QA Chair Mesh {i}")
    mesh.from_pydata([(-.4,-.4,0), (.4,-.4,0), (.4,.4,0), (-.4,.4,0), (0,0,1)],
                     [], [(0,1,2,3), (0,1,4), (1,2,4), (2,3,4), (3,0,4)])
    obj = bpy.data.objects.new(f"QA Chair {i}", mesh)
    obj.asset_mark()
    preview = obj.preview_ensure()
    preview.image_size = (64, 64)
    rgb = colorsys.hsv_to_rgb(i / 6, .6, .9)
    pixels = []
    for y in range(64):
        for x in range(64):
            r = ((x - 31.5) / 30) ** 2 + ((y - 31.5) / 30) ** 2
            pixels.extend((*[c * (.35 + .65 * math.sqrt(max(0, 1 - r))) for c in rgb], 1)
                          if r < 1 else (.08, .08, .08, 1))
    preview.image_pixels_float = pixels
    objects.add(obj)
bpy.data.libraries.write(str(root / "chairs.blend"), objects, fake_user=True)
for obj in objects:
    bpy.data.objects.remove(obj)
bpy.ops.preferences.asset_library_add(directory=str(root))
bpy.context.preferences.filepaths.asset_libraries[-1].name = LIBRARY
with bpy.context.temp_override(window=drv.main_window()):
    bpy.ops.mixar.agent_bubble_show_window()
result = True'''

# The transport and connection stubs: the answer is recorded, never sent.
STUB = '''from types import SimpleNamespace
from mixar.modules.space_mixie_chat.core import turn_transport
from mixar.modules.space_mixie_chat.core import get_session_manager
f = drv._asset_picker = SimpleNamespace(sent=[], original=turn_transport.create_turn_handler)
class Handler:
    def __init__(self, **kwargs):
        pass
    def start_input_stream(self, **kwargs):
        f.sent.append(kwargs.get("action"))
        return True
turn_transport.create_turn_handler = lambda **kwargs: Handler(**kwargs)
get_session_manager().is_connected = lambda scene: True
result = True'''

RESTORE = '''from mixar.modules.space_mixie_chat.core import turn_transport
from mixar.modules.space_mixie_chat.core import get_session_manager
turn_transport.create_turn_handler = drv._asset_picker.original
try:
    del get_session_manager().is_connected
except AttributeError:
    pass
result = True'''


def settle(qa):
    qa.eval('def wait():\n    yield .4\n    return True\nresult=wait()')


def size(qa, width, height):
    qa.eval(f'w=drv.find_one(**{BUBBLE!r})["_win"]\n'
            'with bpy.context.temp_override(window=w):\n'
            f'    bpy.ops.mixar.bubble_set_size(width={width},height={height})\nresult=True')
    settle(qa)


def ask(qa, bubble_id, picks=6):
    """Pause the turn with the backend's asset question, via the real slots."""
    actions = [{'label': f'QA Chair {i}', 'value': f'QA Chair {i}', 'style': 'default',
                'asset_name': f'QA Chair {i}', 'library': LIBRARY, 'blend_file': 'chairs.blend',
                'asset_type': 'Object', 'score': round(.91 - i * .02, 4)} for i in range(picks)]
    actions += [{'label': 'Model from scratch', 'value': 'Model from scratch', 'style': 'default'},
                {'label': 'Cancel', 'value': 'abort', 'style': 'danger'}]
    event = {'bubble_id': bubble_id, 'input_type': 'choice',
             'content': {'set': f'**{QUESTION}**'}, 'actions': actions}
    qa.eval('from mixar.modules.space_mixie_chat.core.slot_processor import get_slot_processor\n'
            'scene = drv.main_window().scene\n'
            f'get_slot_processor().apply_event({event!r}, scene)\n'
            'result = scene.mixie_chat_state')
    qa.wait("drv.main_window().scene.mixie_chat_state == 'AWAITING_INPUT'", timeout=5)
    qa.wait("len(drv.find(surface='asset_pick_tile')) == 5", timeout=10)


def capture(qa, out, name):
    path = out / f'{name}.png'
    qa.cmd('snap', path=str(path), target=BUBBLE, margin=4000)
    with Image.open(path) as image:
        assert min(image.size) > 100, image.size
        assert max(image.convert('RGB').getextrema()[0]) > 120, 'Blank app capture'
    return path


def disjoint(a, b):
    return a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def picker_geometry(qa):
    tiles = [t['rect'] for t in qa.find(surface='asset_pick_tile')['widgets']]
    actions = {a['value']: a['rect'] for a in qa.find(surface='asset_pick_action')['widgets']}
    for i, a in enumerate(tiles):
        for b in tiles[i + 1:]:
            assert disjoint(a, b), (a, b)
        for rect in actions.values():
            assert disjoint(a, rect), (a, rect)
    return {'tiles': tiles, 'actions': actions,
            'rows': len({round(t[3]) for t in tiles})}


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/asset-picker-qa')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.wait(f"hasattr({WM},'mixie_chat_asset_pick_selected')", timeout=30)
    qa.step('local_library_fixture', qa.eval,
            f'ROOT = {str(out / "fixtures")!r}\nLIBRARY = {LIBRARY!r}\n' + FIXTURE)
    qa.step('stub_transport', qa.eval, STUB)
    summary = {}
    try:
        qa.eval(f'{WM}.mixar_bubble_tab = "GENERATIONS"; result = True')
        size(qa, 1310, 520)

        def takeover():
            ask(qa, 'qa-asset-picker-1')
            # The island comes forward to the Agent tab by itself ...
            assert qa.eval(f'result = {WM}.mixar_bubble_tab') == 'AGENT'
            # ... shows the TOP FIVE only, best match selected ...
            tiles = qa.find(surface='asset_pick_tile')['widgets']
            assert [t['value'] for t in tiles] == [f'QA Chair {i}' for i in range(5)]
            assert tiles[0]['sel'] and not any(t['sel'] for t in tiles[1:])
            # ... and the transcript's buttons are gone, not merely covered.
            assert not qa.find(surface='chat_action')['widgets']
            values = {a['value'] for a in qa.find(surface='asset_pick_action')['widgets']}
            assert values == {'QA Chair 0', 'Model from scratch', 'abort'}, values
        qa.step('asset_question_replaces_the_transcript_with_five_picks', takeover)

        qa.wait('all(bpy.data.images.get(a.image) for m in drv.main_window().scene.mixie_chat_messages '
                "if m.bubble_id == 'qa-asset-picker-1' for a in m.action_items if a.asset_name)",
                timeout=90)
        settle(qa)
        summary['default'] = qa.step('default_geometry', picker_geometry, qa)
        assert summary['default']['rows'] == 1, 'Five picks should share one row at the default size'
        capture(qa, out, 'picker-best-match')

        def select_then_use():
            qa.click(surface='asset_pick_tile', value='QA Chair 3')
            qa.wait(f"{WM}.mixie_chat_asset_pick_selected == 'QA Chair 3'", timeout=5)
            settle(qa)
            tile = next(t for t in qa.find(surface='asset_pick_tile')['widgets']
                        if t['value'] == 'QA Chair 3')
            assert tile['sel']
            assert qa.eval('result = drv._asset_picker.sent') == [], 'A tile click must only select'
            capture(qa, out, 'picker-selected')
            qa.click(surface='asset_pick_action', value='QA Chair 3')
            qa.wait("drv._asset_picker.sent == ['QA Chair 3']", timeout=5)
            qa.wait("len(drv.find(surface='asset_pick_tile')) == 0", timeout=5)
            last = qa.eval('m = drv.main_window().scene.mixie_chat_messages[-1]; '
                           'result = [m.sender, m.text]')
            assert last == ['USER', 'QA Chair 3'], last
            capture(qa, out, 'transcript-restored')
        qa.step('tile_selects_and_use_this_asset_answers_with_it', select_then_use)

        def model_from_scratch():
            ask(qa, 'qa-asset-picker-2')
            assert qa.eval(f'result = {WM}.mixie_chat_asset_pick_selected') == ''
            qa.click(surface='asset_pick_action', value='Model from scratch')
            qa.wait("drv._asset_picker.sent[-1] == 'Model from scratch'", timeout=5)
            qa.wait("len(drv.find(surface='asset_pick_tile')) == 0", timeout=5)
        qa.step('model_from_scratch_answers_with_the_backend_opt_out', model_from_scratch)

        def cancel_and_narrow():
            ask(qa, 'qa-asset-picker-3')
            size(qa, 480, 500)
            summary['narrow'] = picker_geometry(qa)
            assert summary['narrow']['rows'] > 1, 'A narrow island should wrap the picks'
            capture(qa, out, 'picker-narrow')
            qa.click(surface='asset_pick_action', value='abort')
            qa.wait("drv._asset_picker.sent[-1] == 'abort'", timeout=5)
            qa.wait("len(drv.find(surface='asset_pick_tile')) == 0", timeout=5)
        qa.step('narrow_island_wraps_and_cancel_answers', cancel_and_narrow)

        (out / 'asset-picker-geometry.json').write_text(json.dumps(summary, indent=2) + '\n')
        return {'answers': qa.eval('result = drv._asset_picker.sent'), 'paid_requests': 0,
                'screenshots': str(out)}
    finally:
        qa.eval(RESTORE)


if __name__ == '__main__':
    run_scenario('asset_picker_e2e', run)
