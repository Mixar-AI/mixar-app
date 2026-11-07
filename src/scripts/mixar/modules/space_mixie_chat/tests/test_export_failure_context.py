# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Failure diagnostics distinguish exporter failures without leaking user content."""
import errno
import json

import pytest

from mixar.modules.common.analytics import export_events
from mixar.modules.space_mixie_chat.core import agent_export
from test_agent_export_workflow import fake_scene  # noqa: F401


@pytest.mark.parametrize('stage,exception', [
    ('exporter', PermissionError(errno.EACCES, 'private texture', '/private/秘密.glb')),
    ('exporter', TypeError('unsupported option private texture')),
    ('prepare', ValueError('private texture')),
    ('verify', RuntimeError('private texture')),
])
def test_failure_context(fake_scene, monkeypatch, stage, exception):
    events = []
    monkeypatch.setattr(export_events, 'capture',
                        lambda event, props, context=None: events.append((event, props)))

    def fail(*args, **kwargs):
        raise exception

    if stage == 'exporter':
        monkeypatch.setattr(agent_export, '_exporter', lambda fmt: fail)
    elif stage == 'prepare':
        monkeypatch.setattr(agent_export, '_required_armatures', fail)
    else:
        monkeypatch.setattr(agent_export, 'verify_export', fail)
    result = agent_export.export_to_path(str(fake_scene.tmp / '秘密.glb'), {'format': 'glb'})
    assert not result['success']
    assert f'during {stage} ({type(exception).__name__})' in result['error']
    completed = [p for e, p in events if e == 'export.completed']
    assert len(completed) == 1
    props = completed[0]
    assert props['success'] is False
    assert props['failure_stage'] == stage
    assert props['error_type'] == type(exception).__name__
    assert props['error_errno'] == (errno.EACCES if isinstance(exception, OSError) else None)
    assert 'private' not in json.dumps(props) and '秘密' not in json.dumps(props, ensure_ascii=False)


def test_cancelled_exporter_is_not_success(fake_scene, monkeypatch):
    events = []
    monkeypatch.setattr(export_events, 'capture',
                        lambda event, props, context=None: events.append((event, props)))
    monkeypatch.setattr(agent_export, '_exporter', lambda fmt: lambda **kw: {'CANCELLED'})
    result = agent_export.export_to_path(str(fake_scene.tmp / 'cancelled.glb'), {'format': 'glb'})
    assert not result['success'] and 'CANCELLED' in result['error']
    props = [p for e, p in events if e == 'export.completed']
    assert len(props) == 1 and props[0]['failure_stage'] == 'exporter'
    assert props[0]['error_type'] == 'RuntimeError'
