# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Character Parts: stable source ownership and safe, catalog-selected submission."""

import base64
from contextlib import nullcontext
import io
from types import SimpleNamespace as NS
from unittest.mock import Mock

from PIL import Image
import pytest

from mixar.modules.moodboard.core import character_parts_node as node_core
from mixar.modules.moodboard.core.character_parts_payload import encode_source_and_masks


def png(size=(8, 8), color=255):
    output = io.BytesIO()
    Image.new('L', size, color).save(output, 'PNG')
    return output.getvalue()


def test_scaled_masks_preserve_source_and_hard_edges():
    source = png((8, 8), 64)
    mask = Image.new('L', (2, 2), 0)
    mask.putpixel((0, 0), 255)
    output = io.BytesIO()
    mask.save(output, 'PNG')
    image, masks = encode_source_and_masks(source, [output.getvalue()])
    assert base64.b64decode(image) == source
    result = Image.open(io.BytesIO(base64.b64decode(masks[0])))
    assert result.size == (8, 8)
    assert set(result.getdata()) == {0, 255}
    assert result.getpixel((3, 3)) == 255
    assert result.getpixel((4, 4)) == 0


def item():
    return NS(node_id='source', image=NS(source='FILE'), selected=False,
              segments=[NS(active=True, mask_image=NS(name='mask'))])


def test_source_uses_connection_not_current_selection(monkeypatch):
    from mixar.modules.moodboard.core import node_graph

    source = item()
    scene, node = NS(selected_image=item()), NS(node_id='parts')
    monkeypatch.setattr(node_graph, 'input_media_items', lambda s, n: [source])
    assert node_core.source_item(scene, node) is source


@pytest.mark.parametrize('inputs', [[], [item(), item()], [NS(image=NS(source='MOVIE'))]])
def test_requires_one_still_connection(monkeypatch, inputs):
    from mixar.modules.moodboard.core import node_graph

    monkeypatch.setattr(node_graph, 'input_media_items', lambda s, n: inputs)
    with pytest.raises(ValueError, match='Connect one image'):
        node_core.source_item(NS(), NS())


@pytest.mark.parametrize('segments', [[], [NS(active=False, mask_image=object())],
                                      [NS(active=True, mask_image=None)]])
def test_no_enabled_masks_fails_before_submission(segments):
    with pytest.raises(ValueError, match='Create masks'):
        node_core.active_masks(NS(segments=segments))


def catalog(monkeypatch, loaded=True, services=True, model=True, disabled=None):
    from mixar.bootstrap import generation_catalog_cache as cache

    monkeypatch.setattr(cache, 'is_loaded', lambda: loaded)
    monkeypatch.setattr(cache, 'get_capability', lambda key: {'key': key, 'enabled': disabled != 'capability'})
    monkeypatch.setattr(cache, 'get_services', lambda *a, **kw: [{'key': 'scene_gen', 'enabled': disabled != 'service'}] if services else [])
    monkeypatch.setattr(cache, 'get_model', lambda *a: {'slug': 'chosen', 'enabled': disabled != 'model'} if model else None)
    return NS(service_key_id='scene_gen', model_slug='chosen')


@pytest.mark.parametrize('flags', [dict(loaded=False), dict(services=False), dict(model=False),
                                    dict(disabled='capability'), dict(disabled='service'), dict(disabled='model')])
def test_catalog_removal_fails_closed(monkeypatch, flags):
    node = catalog(monkeypatch, **flags)
    with pytest.raises(ValueError):
        node_core.resolve_target(node)


def test_submit_carries_node_identity_model_and_only_active_masks(monkeypatch):
    from mixar.modules.common.utils import image_utils
    from mixar.modules.moodboard.core import node_job_bridge, scene_gen_queue

    node = catalog(monkeypatch)
    node.node_id = 'parts'
    source = item()
    inactive = NS(active=False, mask_image=NS(name='excluded'))
    source.segments.append(inactive)
    monkeypatch.setattr(node_core, 'source_item', lambda *a: source)
    monkeypatch.setattr(node_core, 'collect_node_params', lambda node: {'quality': 7})
    monkeypatch.setattr(image_utils, 'image_to_png_bytes', lambda image: png())
    monkeypatch.setattr(node_job_bridge, 'ensure_graph_listener', Mock())
    enqueue = Mock(return_value=NS(id='fixture-job'))
    monkeypatch.setattr(scene_gen_queue, 'enqueue_scene_gen_job', enqueue)
    job, params = node_core.run_character_parts_node(NS(scene=NS(name='original-scene', session_uid=42)), node)
    assert job.id == 'fixture-job'
    args = enqueue.call_args.kwargs
    assert args['scene_name'] == 'original-scene'
    assert args['graph_node_id'] == 'parts'
    assert args['model'] == 'chosen'
    assert args['payload']['params'] == params == {'quality': 7}
    assert args['payload']['total_objects'] == len(args['payload']['mask_bytes_list_b64']) == 1
    assert 'texture_size' not in args['payload']


def test_import_has_owned_collection_and_restores_global_importer(monkeypatch):
    import bpy
    from mixar.modules.moodboard.core import node_graph, scene_importer

    class Objects(list):
        active = None

    selected = NS(select_get=lambda **kw: True, select_set=Mock())
    objects = Objects([selected])
    objects.active = selected
    view_layer = NS(objects=objects)
    source_scene = NS(name='origin', session_uid=42, camera='unchanged-camera', objects=['Cube'], view_layers=[view_layer],
                      collection=NS(children=NS(link=Mock())))
    collection = NS(name='parts-collection', objects=['earlier-part'])
    collections = NS(get=lambda name: collection if name else None,
                     new=Mock(return_value=collection))
    monkeypatch.setattr(bpy, 'data', NS(scenes=NS(get=lambda name: source_scene),
                                       collections=collections))
    override = Mock(return_value=nullcontext())
    monkeypatch.setattr(bpy, 'context', NS(temp_override=override))
    owner = NS(state='RUNNING', job_id='job1')
    monkeypatch.setattr(node_graph, 'action_node_by_id', lambda *a: owner)
    before = {'unrelated': object()}
    monkeypatch.setattr(scene_importer, '_scene_state', before)
    imported = NS(name='part')

    def add(*args, **kw):
        assert scene_importer._scene_state['collection'] is collection
        assert scene_importer._scene_state['camera'] is None
        assert kw['auto_adjust_camera'] is False
        objects.active = None
        return imported

    monkeypatch.setattr(scene_importer, 'add_object', add)
    job = NS(id='job1', backend_job_id='server-job1', state='RUNNING_DOWNLOAD')
    ready, done = node_core._import_callbacks('origin', 42, 'parts', {'job': job})
    assert ready(b'glb', {}, 0) == [imported]
    assert scene_importer._scene_state is before
    assert source_scene.camera == 'unchanged-camera' and source_scene.objects == ['Cube']
    override.assert_called_once_with(scene=source_scene, view_layer=view_layer)
    source_scene.collection.children.link.assert_called_once_with(collection)
    assert objects.active is selected
    selected.select_set.assert_called_once_with(True, view_layer=view_layer)
    create = Mock()
    monkeypatch.setattr(node_graph, 'create_asset_result', create)
    done(NS(), 'part')
    assert create.call_args.args[0] is source_scene
    assert create.call_args.args[2] == 'part'

    monkeypatch.setattr(scene_importer, 'add_object', Mock(side_effect=ValueError('bad glb')))
    with pytest.raises(ValueError, match='bad glb'):
        ready(b'broken', {}, 1)
    assert scene_importer._scene_state is before


@pytest.mark.parametrize('change', ['cancelled', 'replaced-run', 'replaced-scene', 'failed', 'success'])
def test_late_import_cannot_modify_cancelled_or_replaced_owner(monkeypatch, change):
    import bpy
    from mixar.modules.moodboard.core import node_graph

    scene = NS(session_uid=42)
    node = NS(state='RUNNING', job_id='job1')
    job = NS(id='job1', backend_job_id='server-job1', state='RUNNING_DOWNLOAD')
    if change == 'cancelled':
        job.state = 'CANCELLED'
    elif change == 'replaced-run':
        node.job_id = 'new-job'
    elif change == 'replaced-scene':
        scene.session_uid = 43
    else:
        job.state = change.upper()
    collections = Mock()
    monkeypatch.setattr(bpy, 'data', NS(scenes=NS(get=lambda name: scene), collections=collections))
    monkeypatch.setattr(node_graph, 'action_node_by_id', lambda *a: node)
    ready, _ = node_core._import_callbacks('origin', 42, 'parts', {'job': job})
    with pytest.raises(ValueError, match='no longer active'):
        ready(b'glb', {}, 0)
    collections.new.assert_not_called()


@pytest.mark.parametrize('hook_fails', [False, True])
def test_custom_queue_import_invokes_result_hook_before_success(monkeypatch, hook_fails):
    import bpy
    from mixar.modules.moodboard.core import scene_gen_queue

    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(scene_gen_queue.threading, 'Thread', Thread)
    monkeypatch.setattr(scene_gen_queue.requests, 'get', lambda *a, **kw: NS(
        content=b'fixture-glb', raise_for_status=lambda: None))
    monkeypatch.setattr(bpy.app.timers, 'register', lambda callback, **kw: callback())
    events = []
    def hook(job, names):
        if hook_fails:
            raise ValueError('missing owner')
        events.append(('imported', names))

    job = scene_gen_queue.SceneGenQueueJob(
        state=scene_gen_queue.JobState.RUNNING_DOWNLOAD,
        _on_object_ready=lambda *args: [NS(name='part')],
        _on_imported=hook,
        _objects=[{'object_id': 0, 'glb_url': 'https://fixture.invalid/part.glb'}],
    )
    assert job.handle_result([], lambda names: events.append(('done', names)),
                             lambda error: events.append(('error', error)))
    if hook_fails:
        assert events == [('error', 'Could not attach Character Parts results to their node')]
    else:
        assert events == [('imported', 'part'), ('done', 'part')]
    assert job.imported_object_names == 'part'


def test_menu_created_continuation_is_revealed_without_moving_explicit_drop():
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / 'src/scripts/mixar/modules/moodboard/ui/operators/node_graph_ops.py'
    tree = ast.parse(path.read_text())
    operator = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                    and node.name == 'MIXIE_OT_moodboard_create_connected_action')
    execute = next(node for node in operator.body if isinstance(node, ast.FunctionDef)
                   and node.name == 'execute')
    reveal = next(node for node in execute.body if isinstance(node, ast.If)
                  and isinstance(node.test, ast.UnaryOp))
    assert ast.unparse(reveal.test) == 'not self.use_drop_position'
    assert 'ensure_moodboard_region_visible' in ast.unparse(reveal)


@pytest.mark.parametrize('retired_state', ['FAILED', 'SUCCESS', 'CANCELLED'])
def test_late_scene_gen_completion_does_not_revive_retired_job(monkeypatch, retired_state):
    import bpy
    from mixar.modules.moodboard.core import scene_gen_queue

    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    pending = []

    def register(callback, **kwargs):
        if callback.__name__ == '_import_cb':
            callback()
        else:
            pending.append(callback)

    monkeypatch.setattr(scene_gen_queue.threading, 'Thread', Thread)
    monkeypatch.setattr(scene_gen_queue.requests, 'get', lambda *a, **kw: NS(
        content=b'fixture-glb', raise_for_status=lambda: None))
    monkeypatch.setattr(bpy.app.timers, 'register', register)
    ready = Mock(return_value=[NS(name='part')])
    attached, succeeded, failed = Mock(), Mock(), Mock()
    job = scene_gen_queue.SceneGenQueueJob(
        state=scene_gen_queue.JobState.RUNNING_DOWNLOAD,
        _on_object_ready=ready, _on_imported=attached,
        _objects=[{'object_id': 0, 'glb_url': 'https://fixture.invalid/part.glb'}],
    )
    assert job.handle_result([], succeeded, failed)
    ready.assert_called_once()
    assert len(pending) == 1
    # Watchdog failure, an already completed run, or clear_all cancellation
    # can occur while completion is waiting for the next main-thread tick.
    job.state = scene_gen_queue.JobState(retired_state)
    job.imported_object_names = 'prior-result'
    assert pending.pop()() is None
    assert job.state == scene_gen_queue.JobState(retired_state)
    assert job.imported_object_names == 'prior-result'
    attached.assert_not_called()
    succeeded.assert_not_called()
    failed.assert_not_called()
