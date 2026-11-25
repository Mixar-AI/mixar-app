#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Upscale Image node: catalog gate, menus, staged source, result on the board.

No backend, no credits. A local catalog fixture publishes ``image_upscale``
(the shape the backend seed serves); the job-queue service is stubbed in the
running app so the REAL node, operator, ``StagedImageJob`` and image download
paths run end to end, and the "upscaled" result is served from a local HTTP
server. Asserts:

- catalog gate: no ``image_upscale`` capability -> no Upscale Image template;
  published -> it appears in the template menu (real click + screenshot);
- Create Connected Node from a selected still makes an ``IMAGE_UPSCALE`` node
  linked to it, promptless, with the catalog's factor/face params;
- Run stages the ORIGINAL packed PNG bytes under ``purpose=image_upscale``,
  then enqueues ``image_upscale`` with ``image_s3_key`` and the node's params;
- the result lands as a NEW board image ``<source>_upscaled`` at the served
  size, embedded in the node, which reaches SUCCESS; the source is untouched;
- an output past the catalog cap is refused before any upload, naming the
  largest factor that fits.

Replay: QA_HARNESS=../mixar-qa-harness MIXAR_QA_PORT=<port>
QA_SCENARIO_OUT=<dir> python tests/qa/moodboard_image_upscale_e2e.py
"""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

SCENARIO = 'moodboard_image_upscale'
OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-image-upscale'))
ADD = 'MIXIE_OT_moodboard_add_template'
MENU = 'Start with an editable node template'


def _models():
    factor = {'type': 'float', 'default': 2.0, 'min': 1.0, 'max': 4.0, 'step': 0.5,
              'label': 'Upscale Factor', 'widget': 'slider', 'order': 0,
              'description': 'Output size relative to the source (1x-4x).'}
    face = {'type': 'boolean', 'default': True, 'label': 'Face Enhancement',
            'widget': 'toggle', 'order': 1, 'description': 'Restore faces in photos'}
    return [
        {'slug': 'topaz-standard-v2', 'label': 'Topaz Standard V2', 'is_default': True,
         'description': 'Balanced upscaling for most photos',
         'parameters': {'upscale_factor': factor, 'face_enhancement': face}},
        {'slug': 'topaz-cgi', 'label': 'Topaz CGI', 'is_default': False,
         'description': 'For renders, textures, illustrations and other digital art',
         'parameters': {'upscale_factor': factor}},
    ]


def _catalog(max_output_pixels=96_000_000):
    image_gen = {'key': 'image_gen', 'label': 'Image Gen', 'services': [{
        'key': 'image_gen', 'surface': 'moodboard',
        'models': [{'slug': 'qa', 'label': 'QA model', 'is_default': True, 'parameters': {}}]}]}
    upscale = {'key': 'image_upscale', 'label': 'Image Upscale', 'services': [{
        'key': 'image_upscale', 'label': 'Topaz Image Upscale', 'surface': 'moodboard',
        'output_kind': 'image', 'feature_key': 'image_upscale',
        'input_spec': {'inputs': [{
            'name': 'image', 'kind': 'image', 'required': True, 'multiple': False,
            'max_count': 1, 'max_size_mb': 30, 'max_pixels': 96_000_000,
            'max_output_pixels': max_output_pixels, 'upload_purpose': 'image_upscale',
        }], 'max_materials': 1},
        'models': _models()}]}
    return [image_gen, upscale]


def _fixture(qa, capabilities):
    qa.eval(f'''
from mixar.bootstrap import generation_catalog_cache as catalog
with catalog._lock:
    catalog._catalog={{'capabilities':{capabilities!r},'credit_costs':{{'image_upscale':8}}}}
    catalog._bump_enum_version_locked()
catalog._on_catalog_swapped()
result=True
''')


SETUP = r'''
import os, tempfile, threading, functools, http.server
from types import SimpleNamespace
assert os.environ.get('MIXAR_QA') == '1'
from mixar.bootstrap import generation_catalog_cache as catalog
from mixar.modules.common.api.services import job_queue_service as jqs
from mixar.modules.common.utils.image_utils import add_image_to_moodboard
ns = bpy.app.driver_namespace
ns['_qa_up_catalog'] = catalog._catalog
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type in {'VIEW_3D', 'MIXIE'})
area.type = 'MIXIE'

# The SOURCE: a packed 256x192 gradient still on the board.
src = bpy.data.images.new('qa_upscale_src', 256, 192, alpha=True)
px = [0.0] * (256 * 192 * 4)
for y in range(192):
    for x in range(256):
        i = (y * 256 + x) * 4
        px[i:i + 4] = (x / 255, y / 191, 0.5, 1.0)
src.pixels = px
src.pack()
ns['_qa_up_src'] = src.name  # '.001' if a previous replay left one behind
add_image_to_moodboard(src, scene=win.scene)

# The "upscaled" RESULT (512x384) served over local HTTP like a presigned URL.
root = tempfile.mkdtemp(prefix='qa_upscale_')
out = bpy.data.images.new('qa_upscale_out_tmp', 512, 384, alpha=True)
out.pixels = [0.2, 0.6, 0.3, 1.0] * (512 * 384)
out.filepath_raw = os.path.join(root, 'upscaled.png')
out.file_format = 'PNG'
out.save()
bpy.data.images.remove(out)
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
ns['_qa_up_server'] = server
url = f'http://127.0.0.1:{server.server_address[1]}/upscaled.png'

# Stub the job-queue service: record exactly what the real job sends.
svc = jqs.get_job_queue_service()
calls = ns['_qa_up_calls'] = []
ns['_qa_up_orig'] = (svc.stage_media, svc.enqueue)

def _later(fn):
    bpy.app.timers.register(lambda: (fn(), None)[1], first_interval=0.05)

def stage_media(**kw):
    body = kw['body_factory']().read()
    calls.append(('stage', {k: kw[k] for k in ('media_kind', 'filename', 'content_type',
                                               'content_length', 'purpose')}, body))
    key = 'user-uploads/qa/image_upscale/images/256x192/qa/qa_upscale_src.png'
    _later(lambda: kw['on_success'](SimpleNamespace(data={'data': {'s3_key': key}})))
    return 'qa-stage'

def enqueue(**kw):
    calls.append(('enqueue', {k: kw[k] for k in ('job_type', 'model', 'payload')}, None))
    data = {'job_id': 'qa-upscale', 'status': 'DONE', 'result': {'images': [url]}}
    _later(lambda: kw['on_success'](SimpleNamespace(data={'data': data})))
    return 'qa-enqueue'

svc.stage_media = stage_media
svc.enqueue = enqueue
result = {'source_packed_bytes': len(src.packed_file.data), 'url': url, 'source': src.name}
'''

TEARDOWN = r'''
from mixar.bootstrap import generation_catalog_cache as catalog
from mixar.modules.common.api.services import job_queue_service as jqs
ns = bpy.app.driver_namespace
svc = jqs.get_job_queue_service()
orig = ns.pop('_qa_up_orig', None)
if orig:
    svc.stage_media, svc.enqueue = orig
server = ns.pop('_qa_up_server', None)
if server:
    server.shutdown()
if '_qa_up_catalog' in ns:
    with catalog._lock:
        catalog._catalog = ns.pop('_qa_up_catalog')
        catalog._bump_enum_version_locked()
    catalog._on_catalog_swapped()
result = True
'''


def _template_menu(qa, name):
    qa.click(text=MENU)
    texts = {w['text'] for w in qa.find(op=ADD, popup=True)['widgets']}
    qa.snap(str(OUT / f'{name}.png'))
    qa.press('ESC')
    return sorted(texts)


CREATE = r'''
win = drv.main_window()
scene = win.scene
area = next(a for a in win.screen.areas if a.type == 'MIXIE')
region = next(r for r in area.regions if r.type == 'WINDOW')
src_name = bpy.app.driver_namespace['_qa_up_src']
for item in scene.mixie_moodboard_images:
    item.selected = getattr(item.image, 'name', '') == src_name
with bpy.context.temp_override(window=win, area=area, region=region):
    status = bpy.ops.mixie.moodboard_create_connected_action(action_type='IMAGE_UPSCALE')
node = next(n for n in scene.mixie_moodboard_action_nodes if n.action_type == 'IMAGE_UPSCALE')
from mixar.modules.moodboard.core.node_graph import input_media_items
from mixar.modules.moodboard.core.node_schema import collect_node_params
inputs = [getattr(i.image, 'name', '') for i in input_media_items(scene, node)]
result = {'status': sorted(status), 'node_id': node.node_id, 'inputs': inputs,
          'show_prompt': bool(node.show_prompt), 'params': collect_node_params(node),
          'state': node.state}
'''


def _run(node_id, factor):
    return f'''
win = drv.main_window()
scene = win.scene
from mixar.modules.moodboard.core.node_graph import action_node_by_id
node = action_node_by_id(scene, {node_id!r})
for p in node.parameters:
    if p.name == 'upscale_factor':
        p.value_float = {factor}
node.state = 'DRAFT'
node.error = ''
area = next(a for a in win.screen.areas if a.type == 'MIXIE')
region = next(r for r in area.regions if r.type == 'WINDOW')
try:
    with bpy.context.temp_override(window=win, area=area, region=region):
        status = sorted(bpy.ops.mixie.moodboard_run_action_node(node_id={node_id!r}))
except RuntimeError:  # the operator reported an ERROR: the run was refused
    status = ['CANCELLED']
result = {{'status': status, 'state': node.state, 'error': node.error}}
'''


def _node_state(node_id):
    return f'''
scene = drv.main_window().scene
from mixar.modules.moodboard.core.node_graph import action_node_by_id
node = action_node_by_id(scene, {node_id!r})
embedded = [getattr(i.image, 'name', '') for i in scene.mixie_moodboard_images
            if getattr(i, 'embedded_node_id', '') == node.node_id]
img = bpy.data.images.get(embedded[0]) if embedded else None
src = bpy.data.images[bpy.app.driver_namespace['_qa_up_src']]
calls = bpy.app.driver_namespace['_qa_up_calls']
stage = [c for c in calls if c[0] == 'stage']
result = {{
    'state': node.state, 'error': node.error, 'embedded': embedded,
    'size': list(img.size) if img else None,
    'source_size': list(src.size),
    'calls': [c[0] for c in calls],
    'stage': stage[-1][1] if stage else None,
    'stage_matches_packed': bool(stage) and stage[-1][2] == bytes(src.packed_file.data),
    'enqueue': [c[1] for c in calls if c[0] == 'enqueue'],
}}
'''


def scenario(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    # UI modules register in batches after startup: wait for the properties
    # and operators used (and the chat ones dismiss_splash reads).
    qa.wait("hasattr(bpy.types.Scene, 'mixie_moodboard_images') and "
            "hasattr(bpy.types.Scene, 'mixie_chat_messages') and "
            "hasattr(bpy.ops.mixie, 'moodboard_run_action_node') and "
            "hasattr(bpy.ops.mixie, 'agent_image_upscale')", timeout=60)
    qa.dismiss_splash()
    # No sign-in needed: the fixture below replaces whatever catalog (if any)
    # this profile has, and the teardown puts it back.
    setup = qa.step('setup', qa.eval, SETUP)
    try:
        _fixture(qa, [c for c in _catalog() if c['key'] != 'image_upscale'])
        hidden = qa.step('menu_without_capability', _template_menu, qa, 'menu-hidden')
        if 'Upscale Image' in hidden:
            raise ScenarioFail(f'Upscale Image shown without the capability: {hidden}')
        _fixture(qa, _catalog())
        shown = qa.step('menu_with_capability', _template_menu, qa, 'menu-shown')
        if 'Upscale Image' not in shown:
            raise ScenarioFail(f'Upscale Image missing from the template menu: {shown}')

        created = qa.step('create_connected', qa.eval, CREATE)
        source = setup['source']
        if created['inputs'] != [source] or created['show_prompt']:
            raise ScenarioFail(f'node not wired to the source as promptless: {created}')
        if created['params'] != {'upscale_factor': 2.0, 'face_enhancement': True}:
            raise ScenarioFail(f'node params do not follow the catalog: {created}')
        node_id = created['node_id']
        qa.snap(str(OUT / 'node-draft.png'))

        ran = qa.step('run_node', qa.eval, _run(node_id, 2.0))
        if ran['status'] != ['FINISHED']:
            raise ScenarioFail(f'run refused: {ran}')
        qa.wait(f"(lambda n: n.state in {{'SUCCESS','FAILED'}})(__import__("
                f"'mixar.modules.moodboard.core.node_graph',fromlist=['x']).action_node_by_id("
                f"drv.main_window().scene, {node_id!r}))", timeout=30)
        done = qa.step('result_on_board', qa.eval, _node_state(node_id))
        if done['state'] != 'SUCCESS' or done['calls'] != ['stage', 'enqueue']:
            raise ScenarioFail(f'job did not complete through stage -> enqueue: {done}')
        stage = done['stage']
        if (stage['purpose'] != 'image_upscale' or stage['media_kind'] != 'image'
                or not done['stage_matches_packed'] or stage['content_type'] != 'image/png'):
            raise ScenarioFail(f'source was not staged as the original packed PNG: {done}')
        (enq,) = done['enqueue']
        if (enq['job_type'] != 'image_upscale' or enq['model'] != 'topaz-standard-v2'
                or enq['payload'].get('image_s3_key', '').find('/image_upscale/images/') < 0
                or enq['payload'].get('params') != {'upscale_factor': 2.0, 'face_enhancement': True}):
            raise ScenarioFail(f'enqueue payload is wrong: {enq}')
        stem = source.rsplit('.', 1)[0] if source[-4:-3] == '.' else source
        if not done['embedded'] or not done['embedded'][0].startswith(f'{stem}_upscaled'):
            raise ScenarioFail(f'result is not a new embedded board image: {done}')
        if done['size'] != [512, 384] or done['source_size'] != [256, 192]:
            raise ScenarioFail(f'result/source sizes wrong: {done}')
        qa.eval('''
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'MIXIE')
area.tag_redraw()
result = True
''')
        qa.snap(str(OUT / 'node-result.png'))

        _fixture(qa, _catalog(max_output_pixels=500_000))
        refused = qa.step('output_cap_refused', qa.eval, _run(node_id, 4.0))
        after = qa.eval(_node_state(node_id))
        if refused['status'] != ['CANCELLED'] or 'or less' not in refused['error']:
            raise ScenarioFail(f'oversize output was not refused up front: {refused}')
        if after['calls'] != ['stage', 'enqueue']:
            raise ScenarioFail(f'a refused run still uploaded: {after}')
        qa.snap(str(OUT / 'node-refused.png'))
        return {'credits': 0, 'source_bytes': setup['source_packed_bytes'],
                'refusal': refused['error'], 'screenshots': str(OUT)}
    finally:
        qa.eval(TEARDOWN)


def run(qa):
    return scenario(qa)


if __name__ == '__main__':
    run_scenario(SCENARIO, run)
