# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compile-safeguard contracts for the live webcam rig scaffold."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LIVE_RIG = ROOT / "src/scripts/mixar/modules/live_rig"
BOOTSTRAP = ROOT / "src/scripts/mixar/bootstrap"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_live_rig_module_layout_and_bootstrap_exist():
    assert (LIVE_RIG / "constants.py").is_file()
    assert (LIVE_RIG / "core/capture.py").is_file()
    assert (LIVE_RIG / "core/pose_estimate.py").is_file()
    assert (LIVE_RIG / "core/retarget.py").is_file()
    assert (LIVE_RIG / "core/apply.py").is_file()
    assert (LIVE_RIG / "core/session.py").is_file()
    assert (LIVE_RIG / "core/sync_client.py").is_file()
    assert (LIVE_RIG / "core/pump.py").is_file()
    assert (LIVE_RIG / "ui/operators/live_rig_ops.py").is_file()
    assert (LIVE_RIG / "ui/panel.py").is_file()
    assert (BOOTSTRAP / "live_rig_module.py").is_file()


def test_operators_and_panel_declare_classes():
    ops = _read(LIVE_RIG / "ui/operators/live_rig_ops.py")
    panel = _read(LIVE_RIG / "ui/panel.py")
    assert 'bl_idname = "mixar.live_rig_start"' in ops
    assert 'bl_idname = "mixar.live_rig_stop"' in ops
    assert 'bl_idname = "mixar.live_rig_create_room"' in ops
    assert "classes = (" in ops
    assert 'bl_idname = "MIXAR_PT_live_rig"' in panel
    assert "classes = (MIXAR_PT_live_rig,)" in panel


def test_retarget_exposes_mixamo_bones_and_wire_roundtrip_helpers():
    retarget = _read(LIVE_RIG / "core/retarget.py")
    assert "MIXAMO_BONE_ORDER" in retarget
    assert "mixamorig:Hips" in retarget
    assert "def landmarks_to_bone_pose" in retarget
    assert "def bone_pose_to_wire" in retarget
    assert "def bone_pose_from_wire" in retarget


def test_pump_uses_app_timers_and_sync_client_targets_live_rig_api():
    pump = _read(LIVE_RIG / "core/pump.py")
    sync = _read(LIVE_RIG / "core/sync_client.py")
    assert "bpy.app.timers" in pump
    assert "api/v1/live-rig" in sync
    assert "/api/live-rig/ws" in sync
