# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Evaluating a manifest must not record poses or stop live playback."""

from types import SimpleNamespace

import pytest

from mixar.modules.director.core import playback, record, shot_api


@pytest.mark.parametrize("fail", [False, True])
def test_manifest_sampling_and_restore_suspend_recording(monkeypatch, fail):
    visited = []
    scene = SimpleNamespace(
        frame_current=12, name='Scene', frame_start=1, frame_end=48,
        render=SimpleNamespace(fps=24, fps_base=1, resolution_x=640,
                               resolution_y=360, pixel_aspect_x=1, pixel_aspect_y=1),
    )

    def frame_set(frame):
        visited.append((frame, record.recording_suspended()))
        scene.frame_current = frame

    scene.frame_set = frame_set
    shot = SimpleNamespace(
        camera=SimpleNamespace(type='CAMERA', name='Camera'),
        beats=[SimpleNamespace(frame=1, beat_id='start', image=None),
               SimpleNamespace(frame=48, beat_id='end', image=None)],
        shot_id='shot', name='Shot', version=1, prompt='', guidance_strength='MEDIUM',
    )

    def sample(scene, _camera, frame):
        scene.frame_set(frame)
        if fail:
            raise RuntimeError('sample failed')
        return {'location': (0, 0, 0), 'rotation_quaternion': (1, 0, 0, 0), 'lens_mm': 50}

    monkeypatch.setattr(shot_api, '_sample_camera', sample)
    if fail:
        with pytest.raises(RuntimeError, match='sample failed'):
            shot_api.build_shot_manifest(scene, shot)
    else:
        shot_api.build_shot_manifest(scene, shot)
    assert visited and all(suspended for _frame, suspended in visited)
    assert scene.frame_current == 12
    assert not record.recording_suspended()


def test_sampling_neither_wraps_nor_ends_playback(monkeypatch):
    stopped = []
    scene = SimpleNamespace(name='Scene', as_pointer=lambda: 1, frame_current=12)
    monkeypatch.setattr(playback, '_stop_playback', lambda *_args: stopped.append(True))
    playback.arm_single_play(scene, 1, 48)
    try:
        playback._on_frame_change(scene)
        with record.suspend_recording():
            for frame in (1, 48, 12):
                scene.frame_current = frame
                playback._on_frame_change(scene)
        assert stopped == []
        assert playback.is_armed()
        scene.frame_current = 48
        playback._on_frame_change(scene)
        assert stopped == [True]
    finally:
        playback.disarm()
