# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from mixar.modules.common.utils.generation_dispatch import dispatch_scope, record_reason
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
