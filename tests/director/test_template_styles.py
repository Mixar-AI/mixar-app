# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every Template Style pick has an effect the director can see at once.

Handheld and Z-Fixed used to arm a flag and nothing else (no curves for the
noise to ride on, no leveling until Navigate), and Dolly Zoom was a plain
dolly with the lens untouched.
"""

from pathlib import Path
from types import SimpleNamespace

from mixar.modules.director.core import camera_moves

ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
TEMPLATE_OPS = (DIRECTOR / "ui/operators/template_ops.py").read_text(encoding="utf-8")


class _Collection(list):
    def add(self):
        beat = SimpleNamespace(frame=0)
        self.append(beat)
        return beat


def _run_move(monkeypatch, move, lens=50.0):
    scene = SimpleNamespace(
        frame_current=1,
        render=SimpleNamespace(fps=24, fps_base=1.0),
    )
    scene.frame_set = lambda frame: setattr(scene, "frame_current", frame)
    camera = SimpleNamespace(matrix_world=None, data=SimpleNamespace(lens=lens))
    shot = SimpleNamespace(scene_ref=scene, camera=camera, beats=_Collection())
    captured = []

    def _capture(_context, target_shot, _seconds):
        beat = target_shot.beats.add()
        beat.frame = int(scene.frame_current)
        captured.append((beat.frame, camera.data.lens))
        return beat

    monkeypatch.setattr(camera_moves, "capture_beat", _capture)
    monkeypatch.setattr(camera_moves, "move_poses", lambda scene, camera, move: [object()])
    context = SimpleNamespace(scene=scene, view_layer=SimpleNamespace(update=lambda: None))
    frames = camera_moves.apply_camera_move(context, shot, SimpleNamespace(beat_seconds=1.0), move)
    return frames, captured


def test_dolly_zoom_is_a_real_camera_move():
    keys = [key for key, _label, _tip in camera_moves.CAMERA_MOVES]
    assert "DOLLY_ZOOM" in keys
    assert camera_moves.lens_scale("DOLLY_ZOOM") == 1.0 - camera_moves._DOLLY_FACTOR
    assert camera_moves.lens_scale("DOLLY_IN") == 1.0
    # Translation shares the dolly-in branch: the subject distance shrinks by
    # the same factor the lens widens by, so its on-screen size holds.
    assert 'if move in {"DOLLY_IN", "DOLLY_OUT", "DOLLY_ZOOM"}:' in (
        DIRECTOR / "core/camera_moves.py"
    ).read_text(encoding="utf-8")


def test_dolly_zoom_keys_the_lens_at_the_target_pose(monkeypatch):
    frames, captured = _run_move(monkeypatch, "DOLLY_ZOOM", lens=50.0)
    assert frames == [1, 25]
    # Anchor keeps the lens; the target capture sees it widened to 60%.
    assert captured == [(1, 50.0), (25, 30.0)]


def test_other_moves_leave_the_lens_alone(monkeypatch):
    _frames, captured = _run_move(monkeypatch, "CRANE_UP", lens=50.0)
    assert [lens for _frame, lens in captured] == [50.0, 50.0]


def test_template_dispatch_maps_dolly_zoom_to_the_zoom_preset():
    assert '"DOLLY_ZOOM": "DOLLY_ZOOM"' in TEMPLATE_OPS
    assert '"CRANE": "CRANE_UP"' in TEMPLATE_OPS


def test_handheld_captures_an_anchor_when_the_shot_has_no_keys():
    body = TEMPLATE_OPS[TEMPLATE_OPS.index("def _apply_handheld") :]
    body = body[: body.index("def _apply_level_horizon")]
    assert "if shot.beats:" in body
    assert "capture_beat(context, shot, state.beat_seconds)" in body


def test_z_fixed_levels_every_keyframe_and_the_live_pose():
    body = TEMPLATE_OPS[TEMPLATE_OPS.index("def _apply_level_horizon") :]
    body = body[: body.index("class MIXAR_OT_director_set_template")]
    assert body.count("level_camera_horizon(camera)") == 2
    assert "scene.frame_set(frame)" in body
    assert "camera.keyframe_insert(" in body and "rotation_data_path(camera)" in body
    # Re-keyed rotations go back through the continuity filter, and the
    # playhead is restored even if leveling raises.
    assert "repair_rotation_continuity(camera)" in body
    assert "finally:" in body and "scene.frame_set(original)" in body


def test_none_only_clears_state():
    execute = TEMPLATE_OPS[TEMPLATE_OPS.index("    def execute(self, context):") :]
    assert 'if self.template == "NONE":\n            return {\'FINISHED\'}' in execute
