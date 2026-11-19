# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from mixar.modules.common.utils.generation_dispatch import (
    dispatch_scope, failure_outcome, record_exception, record_reason,
)
from mixar.modules.common.analytics import journey_events


def test_reason_is_scoped_and_does_not_leak_after_exception():
    with dispatch_scope() as outer:
        record_reason('missing_image')
        with pytest.raises(RuntimeError), dispatch_scope() as inner:
            record_reason('catalog_unavailable')
            raise RuntimeError('private contents')
        assert inner == {'reason': 'catalog_unavailable'}
        assert outer == {'reason': 'missing_image'}
    record_reason('enqueue_failed')  # direct calls outside dispatch are inert
    with dispatch_scope() as next_attempt:
        assert next_attempt == {}


def test_telemetry_only_accepts_bounded_reasons():
    with patch.object(journey_events, 'capture') as capture:
        journey_events.generation_dispatch(None, {'attempt_id': 'a'}, 'error', reason='missing_image')
        assert capture.call_args.args[1]['reason'] == 'missing_image'
        journey_events.generation_dispatch(None, {}, 'error', reason='/private/key.png')
        assert 'reason' not in capture.call_args.args[1]


def test_empty_image_encoding_never_enqueues_or_clears_draft():
    # Execute the real method with a plain self: bpy Operator bases are mocks
    # outside Blender. Dependencies at the method boundary remain explicit.
    path = Path('src/scripts/mixar/modules/moodboard/ui/operators/model_gen_ops.py')
    tree = ast.parse(path.read_text())
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_submit')
    namespace = {'record_reason': record_reason, 'rpt_': lambda text: text}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    reports = []
    operator = NS(_turnaround_payload=lambda *args: None, report=lambda level, text: reports.append(text))
    from mixar.modules.common import generation_params
    from mixar.modules.common.utils import image_utils
    with patch.object(generation_params, 'model_supports_multi_view', return_value=False), \
         patch.object(image_utils, 'compress_for_service', return_value=b''), \
         patch('mixar.modules.common.job_queue.enqueue_generation') as enqueue, \
         dispatch_scope() as feedback:
        assert namespace['_submit'](operator, NS(), 'model_3d', 'model', NS(name='image'), 'keep draft') is None
        enqueue.assert_not_called()
        assert feedback == {'reason': 'image_processing_failed'}
    assert 'Reload' in reports[0]


@pytest.mark.parametrize('feedback, outcome', [
    ({}, 'rejected'),
    ({'reason': 'duplicate_job'}, 'rejected'),
    ({'reason': 'catalog_unavailable'}, 'rejected'),
    ({'reason': 'missing_image'}, 'needs_input'),
    ({'reason': 'missing_input'}, 'needs_input'),
    ({'reason': 'missing_prompt'}, 'needs_input'),
    ({'reason': 'enqueue_failed'}, 'error'),
    ({'reason': 'image_processing_failed'}, 'error'),
    ({'reason': 'missing_input', 'exception': True}, 'error'),
])
def test_missing_input_is_not_a_rejection_and_only_failures_are_errors(feedback, outcome):
    assert failure_outcome(feedback) == outcome


def test_an_inner_operator_exception_marks_the_dispatch_as_failed():
    import importlib
    capture = importlib.import_module('mixar.modules.common.analytics.capture')
    def execute(self, context):
        raise ValueError('boom')
    wrapped = capture._operator_wrapper(execute, 'mixie.imagegen_generate', with_event=False)
    with patch.object(capture, 'capture'), patch.object(capture, '_report_operator_exception'), \
            dispatch_scope() as feedback, pytest.raises(ValueError):
        wrapped(None, None)
    assert feedback == {'exception': True}
    assert failure_outcome(feedback) == 'error'
    record_exception()  # outside a dispatch it is inert


@pytest.mark.parametrize('outcome, reason', [
    ('rejected', 'duplicate_job'), ('needs_input', 'missing_prompt'),
])
def test_refusal_outcomes_are_accepted_dispatch_outcomes(outcome, reason):
    with patch.object(journey_events, 'capture') as capture:
        journey_events.generation_dispatch(None, {}, outcome, reason=reason)
    assert capture.call_args.args[1] == {'outcome': outcome, 'reason': reason}


@pytest.mark.parametrize('name, message', [
    ('imagegen_ops', '"Please enter a prompt'),
    ('video_gen_ops', '"Enter a video prompt"'),
    ('world_labs_ops', '"Please enter a text prompt"'),
    ('lookdev_ops', '"Please enter a prompt'),
])
def test_empty_prompt_refusals_record_missing_prompt(name, message):
    # Without the reason an empty-prompt Generate reads as a 'rejected' refusal.
    source = Path(f'src/scripts/mixar/modules/moodboard/ui/operators/{name}.py').read_text()
    head = source[:source.index(message)]
    assert head.rstrip().rsplit('\n', 2)[-2].strip() == 'record_reason("missing_prompt")'


@pytest.mark.parametrize('name, message', [
    ('segment_gen_ops', '"No input image selected"'),
    ('image_to_3d_ops', '"Please select an image in the moodboard"'),
    ('image_to_3d_ops', '"Please add an input image"'),
    ('image_to_3d_ops', '"No image selected in moodboard"'),
    ('image_to_3d_ops', '"No input image selected"'),
])
def test_missing_image_refusals_record_missing_image(name, message):
    # Without the reason a Generate with no input image reads as 'rejected'.
    source = Path(f'src/scripts/mixar/modules/moodboard/ui/operators/{name}.py').read_text()
    head = source[:source.index(message)]
    assert head.rstrip().rsplit('\n', 2)[-2].strip() == 'record_reason("missing_image")'


def _video_count_refusal(image_mode, images, videos):
    """Run the real Video Generate execute up to its reference-count refusal."""
    path = Path('src/scripts/mixar/modules/moodboard/ui/operators/video_gen_ops.py')
    tree = ast.parse(path.read_text())
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'execute')
    namespace = {'record_reason': record_reason}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    reports = []
    operator = NS(report=lambda level, text: reports.append(text))
    context = NS(scene=NS(mixie_moodboard_sidebar=NS(tab_video_gen=NS(prompt='a cat', mode='', model=''))))
    refs = {'images': ['img'] * images, 'videos': ['vid'] * videos, 'all_video_sources_available': True}
    limits = {'max_images': 2, 'max_videos': 1, 'max_materials': 3}
    from mixar.modules.common import generation_params
    from mixar.modules.moodboard.core import media_utils, video_generation_catalog
    with patch.object(generation_params, 'resolve_service_key', return_value='video_gen'), \
         patch.object(generation_params, 'resolve_model_slug', return_value='model'), \
         patch.object(generation_params, 'collect_params', return_value={'image_mode': image_mode}), \
         patch.object(media_utils, 'get_selected_moodboard_media_inputs', return_value=refs), \
         patch.object(video_generation_catalog, 'get_video_generation_limits', return_value=limits), \
         dispatch_scope() as feedback:
        assert namespace['execute'](operator, context) == {'CANCELLED'}
    assert len(reports) == 1
    return feedback


@pytest.mark.parametrize('image_mode, images, videos, reason', [
    ('first_frame', 0, 0, 'missing_image'),
    ('first_last_frame', 0, 0, 'missing_image'),
    ('first_last_frame', 1, 0, 'missing_image'),
    ('first_frame', 2, 0, None),          # too many frames is not missing input
    ('first_last_frame', 3, 0, None),
    ('first_frame', 1, 1, None),          # videos unsupported in frame modes
    ('', 3, 0, None),                     # over the reference ceiling
])
def test_video_frame_mode_shortfall_records_missing_image(image_mode, images, videos, reason):
    feedback = _video_count_refusal(image_mode, images, videos)
    assert feedback.get('reason') == reason


def test_dispatcher_classifies_escaped_errors():
    source = Path('src/scripts/mixar/modules/moodboard/ui/operators/prompt_generate_ops.py').read_text()
    handler = source[source.index('except RuntimeError'):]
    assert 'failure_outcome(feedback)' in handler.split('self.report')[0]
    assert "attempt, 'error'" not in source


@pytest.mark.parametrize('name', ['image_to_3d_ops', 'imagegen_ops', 'video_gen_ops', 'world_labs_ops'])
def test_island_enqueue_exceptions_are_recorded_as_failures(name):
    # A caught enqueue exception is a failure; without the reason it would
    # read as a refusal. Each recording precedes its "Failed to start" report.
    source = Path(f'src/scripts/mixar/modules/moodboard/ui/operators/{name}.py').read_text()
    tail = source[source.index('record_reason("enqueue_failed")'):]
    assert tail.index('Failed to start') < tail.index('return')
