# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Session message-validation and rig-math contracts.

The Session is the trust boundary between the LAN WebSocket and the
main-thread camera driver: hostile or malformed phone input must never
raise, and every setting must come out clamped. The rig math is what the
camera actually follows, so the geometric identities (recenter, slerp,
ground-plane dolly, vertigo) are pinned exactly.
"""

import math

import pytest

from mixar.modules.virtual_camera.core import rig_math
from mixar.modules.virtual_camera.core.session import Session


class TestSessionControl:
    def test_ctl_packet_stored_and_snapshot_returns_it(self):
        s = Session()
        s.handle_message(
            {"t": "ctl", "q": [1, 0, 0, 0], "j1": [0.5, -0.5], "j2": [0, 1]},
            now=100.0,
        )
        packet = s.control_snapshot(now=100.2)
        assert packet.quat == (1, 0, 0, 0)
        assert packet.j1 == (0.5, -0.5)
        assert packet.j2 == (0, 1)

    def test_stale_packet_dropped(self):
        s = Session()
        s.handle_message({"t": "ctl", "q": [1, 0, 0, 0], "j1": [0, 0], "j2": [0, 0]}, now=100.0)
        assert s.control_snapshot(now=101.5) is None

    def test_invalid_quat_becomes_none_but_sticks_survive(self):
        s = Session()
        for bad_q in (None, [], [1, 0, 0], [0, 0, 0, 0], "junk", [1, 0, 0, "x"]):
            s.handle_message({"t": "ctl", "q": bad_q, "j1": [1, 0], "j2": [0, 0]}, now=1.0)
            packet = s.control_snapshot(now=1.0)
            assert packet.quat is None
            assert packet.j1 == (1, 0)

    def test_out_of_range_stick_zeroed(self):
        s = Session()
        s.handle_message({"t": "ctl", "q": None, "j1": [99, 0], "j2": [0, 0]}, now=1.0)
        assert s.control_snapshot(now=1.0).j1 == (0.0, 0.0)

    def test_malformed_messages_never_raise(self):
        s = Session()
        for msg in (None, 42, "x", [], {}, {"t": "bogus"}, {"t": "ctl"},
                    {"t": "set"}, {"t": "cmd"}, {"t": "set", "key": "lens"}):
            s.handle_message(msg, now=1.0)


class TestSessionSettings:
    def test_setting_clamped_and_marked_dirty(self):
        s = Session()
        s.handle_message({"t": "set", "key": "lens", "value": 10000}, now=1.0)
        assert s.snapshot_settings()["lens"] == 250.0
        assert s.take_dirty_settings() == {"lens": 250.0}
        assert s.take_dirty_settings() == {}

    def test_unknown_setting_ignored(self):
        s = Session()
        s.handle_message({"t": "set", "key": "__proto__", "value": 1}, now=1.0)
        assert "__proto__" not in s.snapshot_settings()

    def test_non_numeric_setting_ignored(self):
        s = Session()
        before = s.snapshot_settings()
        s.handle_message({"t": "set", "key": "lens", "value": "wide"}, now=1.0)
        assert s.snapshot_settings() == before

    def test_stream_quality_coerced_to_int(self):
        s = Session()
        s.handle_message({"t": "set", "key": "stream_quality", "value": 2.9}, now=1.0)
        assert s.snapshot_settings()["stream_quality"] == 2


class TestSessionCommands:
    def test_allowed_command_queued_and_drained_once(self):
        s = Session()
        s.handle_message({"t": "cmd", "name": "recenter"}, now=1.0)
        s.handle_message(
            {"t": "cmd", "name": "camera_select", "args": {"name": "Cam"}}, now=1.0
        )
        commands = s.take_commands()
        assert [c["name"] for c in commands] == ["recenter", "camera_select"]
        assert commands[1]["args"] == {"name": "Cam"}
        assert s.take_commands() == []

    def test_unknown_command_rejected(self):
        s = Session()
        s.handle_message({"t": "cmd", "name": "run_python"}, now=1.0)
        assert s.take_commands() == []

    def test_non_dict_args_sanitized(self):
        s = Session()
        s.handle_message({"t": "cmd", "name": "stop", "args": [1, 2]}, now=1.0)
        assert s.take_commands()[0]["args"] == {}

    def test_disconnect_clears_control_and_commands(self):
        s = Session()
        s.handle_message({"t": "ctl", "q": [1, 0, 0, 0], "j1": [0, 0], "j2": [0, 0]}, now=1.0)
        s.handle_message({"t": "cmd", "name": "stop"}, now=1.0)
        s.mark_disconnected()
        assert s.control_snapshot(now=1.0) is None
        assert s.take_commands() == []


def _angle_between(a, b):
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return 2 * math.acos(min(dot, 1.0))


class TestRigMath:
    def test_recenter_offset_maps_phone_to_camera_exactly(self):
        camera_q = rig_math.q_normalize((0.9, 0.1, 0.3, 0.1))
        phone_q = rig_math.q_normalize((0.7, -0.2, 0.1, 0.6))
        offset = rig_math.recenter_offset(camera_q, phone_q)
        applied = rig_math.apply_offset(offset, phone_q)
        assert _angle_between(applied, camera_q) < 1e-9

    def test_relative_phone_motion_preserved_after_recenter(self):
        camera_q = rig_math.q_from_axis_angle((0, 0, 1), 1.0)
        phone_q0 = rig_math.q_from_axis_angle((0, 0, 1), 0.2)
        offset = rig_math.recenter_offset(camera_q, phone_q0)
        # Phone yaws a further 0.3 rad -> camera must land at 1.3 rad.
        phone_q1 = rig_math.q_from_axis_angle((0, 0, 1), 0.5)
        applied = rig_math.apply_offset(offset, phone_q1)
        expected = rig_math.q_from_axis_angle((0, 0, 1), 1.3)
        assert _angle_between(applied, expected) < 1e-9

    def test_slerp_endpoints_and_midpoint(self):
        a = (1.0, 0.0, 0.0, 0.0)
        b = rig_math.q_from_axis_angle((0, 0, 1), math.pi / 2)
        assert _angle_between(rig_math.q_slerp(a, b, 0.0), a) < 1e-9
        assert _angle_between(rig_math.q_slerp(a, b, 1.0), b) < 1e-9
        mid = rig_math.q_slerp(a, b, 0.5)
        expected = rig_math.q_from_axis_angle((0, 0, 1), math.pi / 4)
        assert _angle_between(mid, expected) < 1e-9

    def test_slerp_takes_shortest_arc(self):
        a = (1.0, 0.0, 0.0, 0.0)
        b = tuple(-c for c in rig_math.q_from_axis_angle((0, 0, 1), 0.1))
        mid = rig_math.q_slerp(a, b, 0.5)
        assert _angle_between(mid, a) < 0.06

    def test_smoothing_alpha_framerate_independent(self):
        # One 1/30s step must retain exactly what two 1/60s steps retain.
        smoothing = 0.6
        one_step = 1 - rig_math.smoothing_alpha(smoothing, 1 / 30)
        two_steps = (1 - rig_math.smoothing_alpha(smoothing, 1 / 60)) ** 2
        assert one_step == pytest.approx(two_steps, rel=1e-9)

    def test_smoothing_alpha_zero_is_instant(self):
        assert rig_math.smoothing_alpha(0.0, 1 / 60) == 1.0

    def test_dolly_follows_view_heading_on_ground_plane(self):
        # Camera looking north (+Y) pitched 45 degrees down: pushing the
        # stick forward must move along +Y only, never into the floor.
        camera_q = rig_math.q_from_axis_angle((1, 0, 0), math.pi / 4)
        velocity, _ = rig_math.joystick_velocity((0, 1), (0, 0), camera_q, speed=2.0)
        assert velocity[2] == pytest.approx(0.0, abs=1e-9)
        assert velocity[0] == pytest.approx(0.0, abs=1e-9)
        assert velocity[1] == pytest.approx(2.0, rel=1e-9)

    def test_boom_is_vertical_world_axis(self):
        camera_q = rig_math.q_from_axis_angle((1, 0, 0), math.pi / 2)
        velocity, _ = rig_math.joystick_velocity((0, 0), (0, 1), camera_q, speed=3.0)
        assert velocity == (pytest.approx(0.0), pytest.approx(0.0), pytest.approx(3.0))

    def test_vertigo_distance_scales_with_lens(self):
        assert rig_math.vertigo_dolly(4.0, 50.0, 100.0) == pytest.approx(8.0)
        assert rig_math.vertigo_dolly(4.0, 50.0, 25.0) == pytest.approx(2.0)
        # Degenerate lens never divides by zero.
        assert rig_math.vertigo_dolly(4.0, 0.0, 25.0) == 4.0
