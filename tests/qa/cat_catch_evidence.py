# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Capture Catching through real moodboard selection and the native flight clock."""

import json

from PIL import Image, ImageDraw

from moodboard_attachment_flight_e2e import clear_selection, record
from reference_drop_ux_e2e import SCENE, attachments, batch_drop, board, pause
from zen_motion_capture import contact_sheet, preview


def capture_catch(qa, out):
    """No injected Catching flag or fake timer: the clicked reference drives the cat."""
    out.mkdir(parents=True, exist_ok=True)
    qa.eval("assert __import__('os').environ.get('MIXAR_QA')=='1'\nresult=True")
    assert not board(qa) and not attachments(qa), 'Use a fresh isolated QA app'
    reference = out/'catch-reference.png'
    image = Image.new('RGB', (320, 240), '#25435a')
    draw = ImageDraw.Draw(image)
    draw.ellipse((85, 35, 235, 185), fill='#eaba66')
    draw.text((120, 205), 'QA CATCH', fill='white')
    image.save(reference)
    item = None
    try:
        batch_drop(qa, [str(reference)])
        qa.wait(f'len({SCENE}.mixie_moodboard_images)==1', timeout=10)
        qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount>.998', timeout=8)
        item = board(qa)[0]
        clear_selection(qa)
        qa.eval("scene=drv.main_window().scene\nscene.mixie_chat_state='IDLE'\n"
                "scene.mixie_chat_is_busy=False\nbpy.ops.mixar.bubble_minimise()\nresult=True")
        pause(qa, .4)
        assert qa.find(surface='pill_cat')['widgets'][0]['value'] == 'Idle'
        # record() clicks moodboard_media and captures both real swap chains,
        # including the original reference, moving ribbon and resting capsule.
        result = record(qa, item['id'], out, minimized=True)
        samples = json.loads((out/'samples.json').read_text())
        tracking = [s for s in samples if any(.15 < f['progress'] < .9 for f in s['flights'])]
        assert len(tracking) >= 3, 'Missing intermediate catch frames'
        assert all(s['cat'] and s['cat']['activity'] == 'Catching' for s in tracking)
        progress = [f['progress'] for s in samples for f in s['flights']]
        assert min(progress) < .4 and max(progress) > .8, 'Missing tracking/landing approach'
        settled = [s for s in samples if s['time'] > samples[-1]['time']-.15]
        assert len(settled) >= 2 and all(
            not s['flights'] and s['cat'] and s['cat']['activity'] == 'Idle' for s in settled)
        assert len(attachments(qa)) == 1 and attachments(qa)[0]['path'] == item['name']
        assert board(qa) == [item], 'Catching changed the source reference'

        faces = []
        for index, sample in enumerate(samples):
            assert sample['cat'], 'The seated pill disappeared during its catch'
            x0, y0, x1, y1 = sample['cat']['rect']
            path = out/f'cat-{index:03}.png'
            with Image.open(sample['target_path']) as pill:
                pill.crop((x0, pill.height-y1, x1, pill.height-y0)).save(path)
            faces.append(dict(time=sample['time'], path=str(path),
                              activity=sample['cat']['activity'], rect=sample['cat']['rect']))
        assert len({tuple(f['rect']) for f in faces}) == 1, 'Catch moved the cat hit target'
        signatures = set()
        for face in faces:
            if face['activity'] == 'Catching':
                with Image.open(face['path']) as pixels:
                    signatures.add(pixels.convert('RGB').tobytes())
        assert len(signatures) >= 3, 'Catching did not visibly animate'
        (out/'cat-samples.json').write_text(json.dumps(faces, indent=2)+'\n')
        preview(faces, out/'cat-motion.gif')
        contact_sheet(faces, out/'cat-frames.png')
        return dict(result, activity='Catching', tracking_frames=len(tracking),
                    catch_appearances=len(signatures), returned_to='Idle',
                    progress_range=[min(progress), max(progress)], paid_requests=0)
    finally:
        if item is not None:
            clear_selection(qa)
            qa.eval(f'''scene={SCENE}
for index in reversed(range(len(scene.mixie_moodboard_images))):
    if scene.mixie_moodboard_images[index].node_id == {item['id']!r}:
        scene.mixie_moodboard_images.remove(index)
image=bpy.data.images.get({item['name']!r})
if image is not None:
    bpy.data.images.remove(image)
result=True
''')
