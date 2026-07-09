# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD_UI = ROOT / "src/scripts/mixar/modules/moodboard/ui"
COMMON_JOB_QUEUE = ROOT / "src/scripts/mixar/modules/common/job_queue"


def read(relative_path: str) -> str:
    return (MOODBOARD_UI / relative_path).read_text()


def read_job_queue(relative_path: str) -> str:
    return (COMMON_JOB_QUEUE / relative_path).read_text()


def test_scene_gen_exp_operators_are_not_registered():
    operators = read("operators/scene_gen_exp_ops.py")
    place_ops = read("operators/scene_gen_exp_place_ops.py")

    assert "classes = ()" in operators
    assert "classes = ()" in place_ops
    assert "register_class" not in operators
    assert "mixie.scene_gen_exp_" not in read("operators/__init__.py")


def test_scene_gen_exp_ui_list_is_not_registered():
    ui_list = read("lists/scene_gen_exp_uilist.py")

    assert "classes = ()" in ui_list
    assert "MIXIE_UL_scene_gen_labels" not in read("moodboard_sidebar_panel.py")
    assert "MIXIE_UL_scene_gen_labels" not in read("sidebar_panel_drawers.py")


def test_scene_gen_exp_properties_are_not_registered_on_bpy_types():
    scene_registration = read("moodboard_scene_registration.py")
    tab_properties = read("moodboard_tab_properties.py")
    exp_tab_properties = read("moodboard_scene_gen_exp_tab_props.py")
    queue_properties = read_job_queue("ui/properties/queue_properties.py")

    forbidden = (
        "MixieSceneGenExpBBox",
        "MixieSceneGenExpLabelObject",
        "MixieMoodboardTabSceneGenExpProps",
        "tab_scene_gen_exp",
        "mixie_scene_gen_exp_is_processing",
        "mixie_scene_gen_hp_is_generating",
        "mixie_scene_gen_lp_is_generating",
        "scene_gen_hp",
        "scene_gen_lp",
        "SCENE_GEN_EXP",
    )
    assert "classes = ()" in exp_tab_properties
    for symbol in forbidden:
        assert symbol not in scene_registration
        assert symbol not in tab_properties
        assert symbol not in queue_properties
