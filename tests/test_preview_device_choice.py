# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""A copied GPU scene must honor CPU eligibility for native and worker previews."""
import copy
from types import SimpleNamespace

import pytest

from test_async_preview import KEY, _pixels, preview  # noqa: F401


@pytest.mark.parametrize('worker_decision,gpu_available', [
    (None, True),  # native job, CPU user preference despite an enabled GPU
    (False, True),  # worker receives the app's CPU decision
    (True, False),  # worker has lost/unavailable GPU hardware
])
def test_copied_gpu_scene_becomes_cpu_and_restores(preview, monkeypatch,
                                                worker_decision, gpu_available):
    source = preview.bpy.context.scene
    private = copy.deepcopy(source)
    assert source.cycles.device == private.cycles.device == 'GPU'
    monkeypatch.setattr(preview, 'render_device', SimpleNamespace(
        use_gpu=lambda: False, gpu_enabled=lambda: gpu_available))
    saved = []

    def set_value(owner, name, value):
        saved.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    info = preview._configure(preview.bpy.context, source, private, set_value,
                              {'inspection': None}, engine='cycles',
                              use_gpu=worker_decision)
    assert private.cycles.device == info['device'] == 'CPU'
    assert source.cycles.device == 'GPU', 'private job changed the source scene'
    for owner, name, value in reversed(saved):
        setattr(owner, name, value)
    assert private.cycles.device == 'GPU'


def test_native_completion_restores_original_gpu_selection(preview, monkeypatch):
    scene = preview.bpy.context.scene
    monkeypatch.setattr(preview, 'render_device', SimpleNamespace(use_gpu=lambda: False))
    result = preview.start(preview.bpy.context, KEY, engine='cycles')
    assert result['status'] == 'running'
    assert scene.cycles.device == result['render']['device'] == 'CPU'
    _pixels(preview)
    preview._finish(KEY, True)
    assert scene.cycles.device == 'GPU'
    assert preview.poll(KEY)['status'] == 'done'
