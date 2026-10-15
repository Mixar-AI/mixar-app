# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""``mixie.agent_animate``: the agent's door to the retarget.

Frozen with the backend's ``GENERATION_SPECS["tripo_retarget"]``: the
``bl_idname`` and the ``object_name`` / ``animations`` / ``animate_in_place``
props. It resolves the rig through the Auto Rig stamp, refuses with a reason
the agent can act on, and enqueues through the one retarget helper.
"""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPERATORS = ROOT / "src/scripts/mixar/modules/moodboard/ui/operators"

# A real ``bpy.types.Operator`` base, so the class below is a class and its
# execute() can run (same preamble as test_agent_video_ops.py).
from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

if "keyring" not in sys.modules:
    sys.modules["keyring"] = ModuleType("keyring")

from mixar.modules.common.utils import agent_feedback
from mixar.modules.hunyuan.constants import (
    ANIMATE_IN_PLACE_PARAM,
    ANIMATE_PRESETS_PARAM,
    ANIMATE_RIG_JOB_PROP,
    ANIMATE_RIG_SKELETON_PROP,
)
from mixar.modules.hunyuan.core import animate_enqueue, animate_presets
from mixar.modules.moodboard.ui.operators import agent_animate_ops

BL_IDNAME = "mixie.agent_animate"
CHOICES = [{"value": "preset:biped:walk", "label": "Walk"},
           {"value": "preset:biped:idle", "label": "Idle"},
           {"value": "preset:quadruped:walk", "label": "Quadruped Walk"}]


class _Object:
    def __init__(self, name, type='MESH', parent=None, **stamps):
        self.name, self.type, self.parent, self.modifiers = name, type, parent, []
        self.children_recursive = []
        self._props = dict(stamps)
        if parent is not None:
            parent.children_recursive.append(self)

    def get(self, key, default=None):
        return self._props.get(key, default)

    def find_armature(self):
        return self.parent if self.parent is not None and self.parent.type == 'ARMATURE' else None


def _character(skeleton="biped"):
    stamps = {ANIMATE_RIG_JOB_PROP: "job-1"}
    if skeleton:
        stamps[ANIMATE_RIG_SKELETON_PROP] = skeleton
    rig = _Object("Armature", 'ARMATURE', **stamps)
    return rig, _Object("Hero", parent=rig, **stamps)


class _Objects(dict):
    """``scene.objects``: looked up by name, iterated as objects."""

    def __iter__(self):
        return iter(list(self.values()))


def _scene(*objects, name="Scene"):
    return NS(name=name, objects=_Objects((obj.name, obj) for obj in objects))


@pytest.fixture
def catalog(monkeypatch):
    state = {"catalog": ("tripo_retarget", "tripo_retarget_v2_5", CHOICES)}
    monkeypatch.setattr(animate_presets, "retarget_catalog", lambda: state["catalog"])
    return state


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def test_a_rigged_mesh_or_its_armature_plans_the_same_submission(catalog):
    rig, body = _character()
    scene = _scene(rig, body)
    for obj in (rig, body):
        submission, reason = agent_animate_ops.plan_agent_animate(
            obj, "preset:biped:walk, preset:biped:idle", True, scene)
        assert reason == ""
        # The queue row names the character's mesh; the merge targets the rig.
        assert submission == {
            "rig_job_id": "job-1", "service_key": "tripo_retarget",
            "model": "tripo_retarget_v2_5",
            "params": {ANIMATE_PRESETS_PARAM: ["preset:biped:walk", "preset:biped:idle"],
                       ANIMATE_IN_PLACE_PARAM: True},
            "label": "Hero", "rig_name": "Armature",
        }


def _plan(obj, animations, scene=None):
    character = [obj] + ([obj.parent] if obj.parent is not None else [])
    return agent_animate_ops.plan_agent_animate(
        obj, animations, False, scene if scene is not None else _scene(*character))


@pytest.mark.parametrize("obj, animations, fragment", [
    (_Object("Plain"), "preset:biped:walk", "run mixie.agent_auto_rig"),
    (_character()[1], "", "at least one animation preset"),
    (_character()[1], "preset:biped:fly", "Unknown animation preset"),
    (_character()[1], "preset:quadruped:walk", "not for a biped rig"),
    # A Meshy (or pre-Animate) rig: stamped with the job, not the skeleton.
    (_character(skeleton="")[1], "preset:biped:walk", "can't take preset animations"),
    (_character(skeleton="avian")[1], "preset:biped:walk",
     "No preset animations are available for avian rigs"),
])
def test_refusals_say_what_to_do(catalog, obj, animations, fragment):
    submission, reason = _plan(obj, animations)
    assert submission is None and fragment in reason


def test_a_character_outside_the_scene_the_result_lands_in_is_refused(catalog):
    # Built in a workspace: the result lands (and merges) in the main scene.
    rig, body = _character()
    main = _scene(name="Main")
    submission, reason = _plan(body, "preset:biped:walk", main)
    assert submission is None
    assert "'Armature' is not in the main scene 'Main'" in reason


def test_refusals_reach_the_agent_in_english(catalog, monkeypatch):
    import mixar.modules.common.i18n as i18n

    monkeypatch.setattr(i18n, "rpt_", lambda text: "TRANSLATED")
    _submission, reason = _plan(_character()[1], "preset:quadruped:walk")
    assert reason.startswith("preset:quadruped:walk: not for a biped rig")


def test_a_catalog_without_the_service_refuses(catalog):
    catalog["catalog"] = ("", "", [])
    submission, reason = _plan(_character()[1], "preset:biped:walk")
    assert submission is None and "unavailable in the generation catalog" in reason


# --------------------------------------------------------------------------- #
# The operator
# --------------------------------------------------------------------------- #


@pytest.fixture
def seams(monkeypatch, catalog):
    calls = NS(reasons=[], enqueued=[], job=NS(id="q1"))
    rig, body = _character()
    objects = {rig.name: rig, body.name: body}
    # The operator module holds its own ``bpy`` reference (whichever mock was
    # live when another test first imported the operators package).
    monkeypatch.setattr(agent_animate_ops.bpy.data, "objects", NS(get=objects.get))
    calls.scene = _scene(rig, body)
    monkeypatch.setattr(agent_animate_ops, "landing_scene", lambda context: calls.scene)
    monkeypatch.setattr(agent_feedback, "set_agent_gen_reason",
                        lambda context, reason: calls.reasons.append(reason))
    monkeypatch.setattr(agent_animate_ops, "set_agent_gen_reason",
                        lambda context, reason: calls.reasons.append(reason))

    def _enqueue(**kw):
        calls.enqueued.append(kw)
        return calls.job

    monkeypatch.setattr(animate_enqueue, "enqueue_retarget_job", _enqueue)
    return calls


def _operator(**props):
    op = agent_animate_ops.MIXIE_OT_agent_animate()
    op.report = lambda *args, **kwargs: None
    defaults = {"object_name": "", "animations": "", "animate_in_place": False}
    for name, value in {**defaults, **props}.items():
        setattr(op, name, value)
    return op


def test_execute_enqueues_through_the_shared_retarget_helper(seams):
    op = _operator(object_name="Hero", animations="preset:biped:idle", animate_in_place=True)
    assert op.execute(NS(window_manager=MagicMock())) == {'FINISHED'}
    assert seams.reasons == []
    (kw,) = seams.enqueued
    assert kw["rig_job_id"] == "job-1" and kw["label"] == "Hero"
    assert kw["params"] == {ANIMATE_PRESETS_PARAM: ["preset:biped:idle"],
                            ANIMATE_IN_PLACE_PARAM: True}


@pytest.mark.parametrize("props, fragment", [
    ({}, "object_name is required"),
    ({"object_name": "Ghost"}, "No object named 'Ghost'"),
    ({"object_name": "Hero", "animations": "preset:quadruped:walk"}, "not for a biped rig"),
])
def test_execute_refuses_with_a_reason_before_enqueueing(seams, props, fragment):
    assert _operator(**props).execute(NS(window_manager=MagicMock())) == {'CANCELLED'}
    assert seams.enqueued == [] and fragment in seams.reasons[-1]


def test_execute_reports_a_duplicate_and_an_enqueue_failure(seams, monkeypatch):
    seams.job = None
    op = _operator(object_name="Hero", animations="preset:biped:walk")
    assert op.execute(NS(window_manager=MagicMock())) == {'CANCELLED'}
    assert "already queued or running" in seams.reasons[-1]

    def _boom(**kw):
        raise RuntimeError("offline")

    monkeypatch.setattr(animate_enqueue, "enqueue_retarget_job", _boom)
    assert op.execute(NS(window_manager=MagicMock())) == {'CANCELLED'}
    assert "Animate submission failed: offline" in seams.reasons[-1]


def test_execute_refuses_a_character_outside_the_landing_scene(seams):
    seams.scene = _scene(name="Main")
    op = _operator(object_name="Hero", animations="preset:biped:walk")
    assert op.execute(NS(window_manager=MagicMock())) == {'CANCELLED'}
    assert seams.enqueued == [] and "not in the main scene 'Main'" in seams.reasons[-1]


def test_the_landing_scene_is_the_agent_sessions_and_the_ref_stays(monkeypatch):
    from mixar.modules.common.job_queue.core import queue_download

    session_scene, window_scene = NS(name="Main"), NS(name="Shown")
    monkeypatch.setattr(queue_download, "resolve_job_scene",
                        lambda name, session: session_scene if session == "s1" else None)
    wm = {"mixar_agent_ref": '{"generation_id": "g1", "session_id": "s1"}'}
    context = NS(window_manager=NS(get=wm.get, keys=wm.keys), scene=window_scene)
    assert agent_animate_ops.landing_scene(context) is session_scene
    assert "mixar_agent_ref" in wm  # peeked, left for the enqueue to claim
    wm.clear()
    assert agent_animate_ops.landing_scene(context) is window_scene


# --------------------------------------------------------------------------- #
# The frozen contract and registration
# --------------------------------------------------------------------------- #


def test_the_operator_carries_the_frozen_bl_idname_and_props():
    cls = agent_animate_ops.MIXIE_OT_agent_animate
    assert cls.bl_idname == BL_IDNAME
    source = (OPERATORS / "agent_animate_ops.py").read_text(encoding="utf-8")
    for prop in ("object_name: StringProperty(", "animations: StringProperty(",
                 "animate_in_place: BoolProperty("):
        assert prop in source


def test_the_operator_module_is_registered():
    # agent_auto_rig_ops shipped once without this line and every enqueue
    # failed with "operator not found".
    source = (OPERATORS / "__init__.py").read_text(encoding="utf-8")
    assert "agent_animate_ops," in source[source.index("modules = ("):]
