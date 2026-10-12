# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real-app checks for ``context_folder.view_video`` (run inside the QA app).

Renders a 2 s red-to-blue Workbench clip as the fixture (no external media),
then drives the in-process decoder, the RPC on the main thread and on the real
``MixarContextFolderRPC`` worker thread, the time-range mapping and the error
codes. Writes ``video-frames.png`` (labelled contact sheet of the sampled
frames) for the vision check and ``video-checklist.json`` with the verdicts.
"""
import base64
import io
import json
import os
from pathlib import Path
import threading
import time

import bmesh
import bpy
from mathutils import Vector

FRAMES = 48
FPS = 24
SIZE = (160, 90)

_RENDER_ATTRS = ('engine', 'fps', 'fps_base', 'resolution_x', 'resolution_y',
                 'resolution_percentage', 'filepath', 'film_transparent', 'use_file_extension')
_IMAGE_ATTRS = ('media_type', 'file_format', 'color_mode')
_FFMPEG_ATTRS = ('format', 'codec', 'constant_rate_factor')


def _snapshot(obj, attrs):
    return {a: getattr(obj, a) for a in attrs if hasattr(obj, a)}


def _restore(obj, saved):
    for attr, value in saved.items():
        try:
            setattr(obj, attr, value)
        except Exception:  # noqa: BLE001 — best effort restore of an enum the engine no longer offers
            pass


def render_fixture(scene, fixtures: Path) -> Path:
    """Render ``clip.mp4``: a cube whose object colour ramps red → blue over 2 s."""
    clip = fixtures / 'clip.mp4'
    for stale in fixtures.glob('*.mp4'):
        stale.unlink()
    saved = {
        'render': _snapshot(scene.render, _RENDER_ATTRS),
        'image': _snapshot(scene.render.image_settings, _IMAGE_ATTRS),
        'ffmpeg': _snapshot(scene.render.ffmpeg, _FFMPEG_ATTRS),
        'frames': (scene.frame_start, scene.frame_end, scene.frame_current),
        'camera': scene.camera,
        'view': (scene.view_settings.view_transform, scene.view_settings.look),
        'shading': (scene.display.shading.light, scene.display.shading.color_type),
    }
    mesh = bpy.data.meshes.new('QA_Video_Cube')
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=4.0)
    bm.to_mesh(mesh)
    bm.free()
    cube = bpy.data.objects.new('QA_Video_Cube', mesh)
    cam_data = bpy.data.cameras.new('QA_Video_Camera')
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = 3.0
    cam = bpy.data.objects.new('QA_Video_Camera', cam_data)
    cam.location = Vector((0.0, 0.0, 10.0))
    scene.collection.objects.link(cube)
    scene.collection.objects.link(cam)
    try:
        cube.color = (1.0, 0.0, 0.0, 1.0)
        cube.keyframe_insert('color', frame=1)
        cube.color = (0.0, 0.0, 1.0, 1.0)
        cube.keyframe_insert('color', frame=FRAMES)
        # Default Bezier easing is fine: only the end frames' colours are asserted.
        scene.camera = cam
        scene.frame_start, scene.frame_end = 1, FRAMES
        r = scene.render
        r.engine = 'BLENDER_WORKBENCH'
        scene.display.shading.light = 'FLAT'
        scene.display.shading.color_type = 'OBJECT'
        scene.view_settings.view_transform = 'Standard'
        scene.view_settings.look = 'None'
        r.fps, r.fps_base = FPS, 1.0
        r.resolution_x, r.resolution_y, r.resolution_percentage = SIZE[0], SIZE[1], 100
        r.film_transparent = False
        r.image_settings.media_type = 'VIDEO'
        r.image_settings.file_format = 'FFMPEG'
        r.image_settings.color_mode = 'RGB'
        r.ffmpeg.format = 'MPEG4'
        r.ffmpeg.codec = 'H264'
        r.ffmpeg.constant_rate_factor = 'HIGH'
        r.use_file_extension = True
        r.filepath = str(fixtures / 'clip')
        bpy.ops.render.render(animation=True)
        produced = sorted(fixtures.glob('*.mp4'))
        assert produced, 'no mp4 written'
        produced[0].rename(clip)
    finally:
        bpy.data.objects.remove(cube, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.cameras.remove(cam_data)
        _restore(scene.render, saved['render'])
        _restore(scene.render.image_settings, saved['image'])
        _restore(scene.render.ffmpeg, saved['ffmpeg'])
        scene.frame_start, scene.frame_end, scene.frame_current = saved['frames']
        scene.camera = saved['camera']
        scene.view_settings.view_transform, scene.view_settings.look = saved['view']
        scene.display.shading.light, scene.display.shading.color_type = saved['shading']
    return clip


def _centre_rgb(frame: dict):
    from PIL import Image
    image = Image.open(io.BytesIO(base64.b64decode(frame['image_base64']))).convert('RGB')
    return image, image.getpixel((image.width // 2, image.height // 2))


def contact_sheet(frames: list, path: Path) -> None:
    from PIL import Image, ImageDraw
    tiles = [_centre_rgb(f)[0] for f in frames]
    w, h = tiles[0].size
    sheet = Image.new('RGB', (w * len(tiles), h + 14), (30, 30, 30))
    draw = ImageDraw.Draw(sheet)
    for i, (tile, frame) in enumerate(zip(tiles, frames)):
        sheet.paste(tile, (i * w, 14))
        draw.text((i * w + 2, 1), f"{frame['t_s']:.2f}s #{frame['frame_index']}", fill=(230, 230, 230))
    sheet.save(path)


def run(out_dir, scene):
    assert os.environ.get('MIXAR_QA') == '1'
    from mixar.modules.context_folder.core import attach, rpc
    out = Path(out_dir)
    fixtures = out / 'fixtures' / 'video'
    fixtures.mkdir(parents=True, exist_ok=True)
    rows = []

    def check(case, fn):
        try:
            rows.append({'case': case, 'status': 'PASS', 'detail': fn()})
        except Exception as exc:  # noqa: BLE001 — a failure is a row, never an abort
            rows.append({'case': case, 'status': 'FAIL', 'detail': repr(exc)})
        (out / 'video-checklist.json').write_text(json.dumps(rows, indent=2, default=str))

    state = {}

    def fixture():
        state['clip'] = render_fixture(scene, fixtures)
        (fixtures / 'still.png').write_bytes(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='))
        size = state['clip'].stat().st_size
        assert size > 1000, size
        return {'bytes': size}
    check('01 fixture mp4 rendered in-app', fixture)

    def decoder():
        import imbuf
        fc, fps, w, h, frames = imbuf.mixar_movie_frames(str(state['clip']), [0, 23, 47, 47, 999], 64)
        assert fc == FRAMES, fc
        assert abs(fps - FPS) < 0.05, fps
        assert (w, h) == SIZE, (w, h)
        assert [f[0] for f in frames] == [0, 23, 47], [f[0] for f in frames]
        assert all((f[1], f[2]) == (64, 36) and len(f[3]) == 64 * 36 * 4 for f in frames), [(f[1], f[2]) for f in frames]
        return {'frame_count': fc, 'fps': fps, 'size': (w, h)}
    check('02 imbuf.mixar_movie_frames decodes, clamps and dedupes', decoder)

    # The QA app is not logged in, so the scene has no session id yet; grants are
    # keyed by session id and skip an empty one, exactly as a real pre-login send would.
    session_id = scene.mixie_session_id or 'qa-folder-video-session'

    def attach_folder():
        for fid in [item.folder_id for item in scene.mixie_context_folders]:
            attach.detach_folder(scene, fid)
        state['fid'] = attach.attach_folder(scene, str(fixtures))['folder_id']
        ctx = attach.folder_context_for_send(scene, session_id)
        entry = ctx['folders'][0]
        kinds = {f['path']: f['kind'] for f in entry['files']}
        assert kinds.get('clip.mp4') == 'video', kinds
        assert str(fixtures) not in json.dumps(ctx)
        return {'kinds': entry['kinds']}
    check('03 manifest lists the clip as kind video, path-free', attach_folder)

    def params(**extra):
        return {'session_id': session_id, 'folder_id': state['fid'], 'path': 'clip.mp4', **extra}

    def default_sample():
        r = rpc.dispatch('context_folder.view_video', params())
        assert r.get('success'), r.get('error')
        assert r['frame_count'] == FRAMES and abs(r['fps'] - FPS) < 0.05, (r['frame_count'], r['fps'])
        assert (r['width'], r['height']) == SIZE
        idx = [f['frame_index'] for f in r['frames']]
        # 0, 0.4, …, 2.0 s at 24 fps → round(9.6)=10, round(28.8)=29; 48 clamps to the last frame.
        assert idx == [0, 10, 19, 29, 38, 47], idx
        ts = [f['t_s'] for f in r['frames']]
        assert ts == sorted(ts) and ts[0] == 0.0
        first, last = _centre_rgb(r['frames'][0])[1], _centre_rgb(r['frames'][-1])[1]
        assert first[0] > 180 and first[2] < 80, first
        assert last[2] > 180 and last[0] < 80, last
        state['frames'] = r['frames']
        contact_sheet(r['frames'], out / 'video-frames.png')
        return {'indices': idx, 'first_rgb': first, 'last_rgb': last, 'duration_s': r['duration_s']}
    check('04 default sample: 6 frames 0..2s, red fades to blue', default_sample)

    def worker_thread():
        done = threading.Event()
        box = {}
        def respond(result):
            box['thread'] = threading.current_thread().name
            box['result'] = result
            done.set()
        rpc.handle_request('context_folder.view_video', params(count=3, max_dim=128), respond)
        deadline = time.monotonic() + 30
        while not done.is_set() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert done.is_set(), 'worker never answered'
        r = box['result']
        assert r.get('success'), r.get('error')
        assert box['thread'] == 'MixarContextFolderRPC', box['thread']
        sizes = {_centre_rgb(f)[0].size for f in r['frames']}
        assert sizes == {(128, 72)}, sizes
        return {'thread': box['thread'], 'indices': [f['frame_index'] for f in r['frames']]}
    check('05 answers on the RPC worker thread at the requested size', worker_thread)

    def time_range():
        r = rpc.dispatch('context_folder.view_video', params(start_s=1.0, end_s=1.5, count=3))
        assert r.get('success'), r.get('error')
        idx = [f['frame_index'] for f in r['frames']]
        assert idx == [24, 30, 36], idx
        mid = rpc.dispatch('context_folder.view_video', params(count=1))
        assert [f['frame_index'] for f in mid['frames']] == [24], mid['frames']
        return {'range_indices': idx}
    check('06 start_s/end_s narrows the sample; count=1 is the midpoint', time_range)

    def errors():
        got = {}
        for label, p, code in [
            ('inverted', params(start_s=1.5, end_s=1.0), 'invalid_range'),
            ('beyond clip', params(start_s=5.0), 'invalid_range'),
            ('still as video', params(path='still.png'), 'not_video'),
            ('video as image', {**params(), 'method': 'view_image'}, 'not_image'),
            ('missing', params(path='nope.mp4'), 'not_found'),
            ('foreign session', {**params(), 'session_id': 'someone-else'}, 'folder_not_attached'),
        ]:
            method = 'context_folder.' + p.pop('method', 'view_video')
            r = rpc.dispatch(method, p)
            assert not r.get('success') and r['error']['code'] == code, (label, r)
            assert str(fixtures) not in json.dumps(r), (label, r)
            got[label] = r['error']['code']
        return got
    check('07 error codes are specific and path-free', errors)

    for fid in [item.folder_id for item in scene.mixie_context_folders]:
        attach.detach_folder(scene, fid)
    return rows
