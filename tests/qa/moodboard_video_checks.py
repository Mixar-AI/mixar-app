# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real-app checks for ``moodboard.view_video`` (run inside the QA app).

Puts a rendered red→blue clip and a still on the Moodboard, then drives
``moodboard/core/video_rpc.handle_request`` with a synchronous main-thread
hop (this module already runs on the main thread): default sample, a time
range, and every refusal code. The driver exercises the REAL timer hop and
the socket dispatcher separately. Writes ``moodboard-frames.png`` for the
vision check and ``moodboard-checklist.json`` with the verdicts.
"""
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import time

import bpy


def _video_checks():
    spec = importlib.util.spec_from_file_location(
        'folder_video_checks', str(Path(__file__).with_name('context_folder_video_checks.py')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def board_item_for(scene, filepath):
    """The board item whose image is linked to ``filepath`` (movies stay linked)."""
    target = os.path.realpath(filepath)
    for item in scene.mixie_moodboard_images:
        image = item.image
        if image is not None and image.filepath:
            if os.path.realpath(bpy.path.abspath(image.filepath)) == target:
                return item
    return None


def centre_rgb(frame):
    from PIL import Image
    image = Image.open(io.BytesIO(base64.b64decode(frame['image_base64']))).convert('RGB')
    return image, image.getpixel((image.width // 2, image.height // 2))


def run(out_dir, scene):
    assert os.environ.get('MIXAR_QA') == '1'
    from mixar.modules.moodboard.core import video_rpc
    from mixar.modules.moodboard.core.media_import import load_media_file_to_board
    out = Path(out_dir)
    fixtures = out / 'fixtures' / 'moodboard'
    fixtures.mkdir(parents=True, exist_ok=True)
    rows = []

    def check(case, fn):
        try:
            rows.append({'case': case, 'status': 'PASS', 'detail': fn()})
        except Exception as exc:  # noqa: BLE001 — a failure is a row, never an abort
            rows.append({'case': case, 'status': 'FAIL', 'detail': repr(exc)})
        (out / 'moodboard-checklist.json').write_text(json.dumps(rows, indent=2, default=str))

    state = {}
    session_id = str(scene.mixie_session_id or '')

    def fixture():
        clip = _video_checks().render_fixture(scene, fixtures)
        still = fixtures / 'still.png'
        from PIL import Image
        Image.new('RGB', (64, 64), (80, 134, 120)).save(still)
        load_media_file_to_board(scene, str(clip))
        load_media_file_to_board(scene, str(still))
        clip_item, still_item = board_item_for(scene, str(clip)), board_item_for(scene, str(still))
        assert clip_item is not None and still_item is not None
        assert clip_item.image.source == 'MOVIE', clip_item.image.source
        state.update(clip=clip, video_name=clip_item.image.name, still_name=still_item.image.name)
        return {'video_name': state['video_name'], 'still_name': state['still_name'],
                'frame_duration': clip_item.image.frame_duration}
    check('01 clip and still added to the Moodboard', fixture)

    def call(params, timeout=30.0):
        box = {}
        video_rpc.handle_request('moodboard.view_video', params, lambda r: box.setdefault('r', r),
                                 run_on_main_thread=lambda fn: (fn(), True)[1])
        deadline = time.monotonic() + timeout
        while 'r' not in box and time.monotonic() < deadline:
            time.sleep(0.05)
        assert 'r' in box, 'no reply'
        assert str(fixtures) not in json.dumps(box['r']), box['r']
        return box['r']

    def default_sample():
        r = call({'image_name': state['video_name'], 'session_id': session_id})
        assert r.get('success'), r.get('error')
        assert r['image_name'] == state['video_name']
        idx = [f['frame_index'] for f in r['frames']]
        assert idx == [0, 10, 19, 29, 38, 47], idx
        first, last = centre_rgb(r['frames'][0])[1], centre_rgb(r['frames'][-1])[1]
        assert first[0] > 180 and first[2] < 80, first
        assert last[2] > 180 and last[0] < 80, last
        _video_checks().contact_sheet(r['frames'], out / 'moodboard-frames.png')
        return {'indices': idx, 'first_rgb': first, 'last_rgb': last, 'fps': r['fps']}
    check('02 default sample of the board video: 6 frames, red fades to blue', default_sample)

    def narrowed():
        r = call({'image_name': state['video_name'], 'session_id': session_id,
                  'start_s': 1.0, 'end_s': 1.5, 'count': 3, 'max_dim': 128})
        assert r.get('success'), r.get('error')
        assert [f['frame_index'] for f in r['frames']] == [24, 30, 36]
        assert {centre_rgb(f)[0].size for f in r['frames']} == {(128, 72)}
        return [f['t_s'] for f in r['frames']]
    check('03 start_s/end_s/count/max_dim honoured', narrowed)

    def errors():
        got = {}
        for label, params, code in [
            ('still', {'image_name': state['still_name'], 'session_id': session_id}, 'not_video'),
            ('unknown', {'image_name': 'Nope.mp4', 'session_id': session_id}, 'not_found'),
            ('no name', {'session_id': session_id}, 'invalid_params'),
            ('foreign session', {'image_name': state['video_name'], 'session_id': 'someone-else'}, 'scene_not_found'),
            ('inverted range', {'image_name': state['video_name'], 'session_id': session_id,
                                'start_s': 1.5, 'end_s': 1.0}, 'invalid_range'),
        ]:
            r = call(params)
            assert not r.get('success') and r['error']['code'] == code, (label, r)
            got[label] = r['error']['code']
        return got
    check('04 refusal codes are specific and path-free', errors)
    return rows
