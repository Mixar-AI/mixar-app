# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""A video node's output duration is seeded from the videos feeding it.

``sync_video_duration_from_inputs`` is exercised directly with stand-in
objects: ``node_graph`` cannot be imported outside Blender (it reaches bpy
through its sibling modules), so the function is loaded from source into a
namespace with the two collaborators it actually calls.
"""

import re
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
SOURCE = (MOODBOARD / "core/node_graph.py").read_text(encoding="utf-8")


def _load_sync(durations_by_name, inputs):
    """Compile just the function under test against fake collaborators."""
    body = SOURCE.split("def sync_video_duration_from_inputs(scene, node) -> bool:")[1]
    body = body.split("\ndef ")[0]
    source = "def sync_video_duration_from_inputs(scene, node) -> bool:" + body
    namespace = {
        "VIDEO_DURATION_PARAM_NAME": "duration",
        "input_media_items": lambda _scene, _node: inputs,
        "video_duration_seconds": lambda item: durations_by_name.get(item.name),
    }
    exec(compile(source, "node_graph_sync", "exec"), namespace)
    return namespace["sync_video_duration_from_inputs"]


def _parameter(name="duration", kind='INTEGER', minimum=4.0, maximum=30.0, value=5):
    return SimpleNamespace(
        name=name,
        parameter_type=kind,
        minimum=minimum,
        maximum=maximum,
        value_integer=value,
        value_float=float(value),
    )


def _node(parameters, action_type='VIDEO_GEN'):
    return SimpleNamespace(action_type=action_type, parameters=parameters)


def _clip(name):
    return SimpleNamespace(name=name)


def test_single_video_seeds_its_own_length():
    parameter = _parameter()
    sync = _load_sync({"a": 12.0}, [_clip("a")])

    assert sync(object(), _node([parameter])) is True
    assert parameter.value_integer == 12


def test_multiple_videos_sum_because_references_read_as_one_timeline():
    parameter = _parameter()
    sync = _load_sync({"a": 6.0, "b": 7.0}, [_clip("a"), _clip("b")])

    assert sync(object(), _node([parameter])) is True
    assert parameter.value_integer == 13


def test_total_is_clamped_to_the_schema_bounds():
    """A 40s reference must not submit a duration the model rejects after
    credits are held."""
    parameter = _parameter()
    sync = _load_sync({"a": 40.0}, [_clip("a")])

    assert sync(object(), _node([parameter])) is True
    assert parameter.value_integer == 30


def test_rounding_cannot_cross_a_bound():
    parameter = _parameter(minimum=4.0, maximum=29.0)
    sync = _load_sync({"a": 29.4}, [_clip("a")])

    sync(object(), _node([parameter]))
    assert parameter.value_integer == 29


def test_short_input_is_raised_to_the_minimum():
    parameter = _parameter(minimum=4.0)
    sync = _load_sync({"a": 1.5}, [_clip("a")])

    sync(object(), _node([parameter]))
    assert parameter.value_integer == 4


def test_unreadable_video_leaves_the_catalog_default_untouched():
    """A codec Blender cannot read degrades to 'no default', never a wrong one."""
    parameter = _parameter(value=5)
    sync = _load_sync({"a": None}, [_clip("a")])

    assert sync(object(), _node([parameter])) is False
    assert parameter.value_integer == 5


def test_a_model_without_a_duration_parameter_is_a_no_op():
    """Keying on the parameter NAME is a known catalog gap; it must fail soft."""
    parameter = _parameter(name="length")
    sync = _load_sync({"a": 9.0}, [_clip("a")])

    assert sync(object(), _node([parameter])) is False


def test_non_video_nodes_are_never_seeded():
    parameter = _parameter()
    sync = _load_sync({"a": 9.0}, [_clip("a")])

    assert sync(object(), _node([parameter], action_type='IMAGE_GEN')) is False
    assert parameter.value_integer == 5


def test_float_parameters_keep_sub_second_precision():
    parameter = _parameter(kind='FLOAT')
    sync = _load_sync({"a": 7.5}, [_clip("a")])

    assert sync(object(), _node([parameter])) is True
    assert parameter.value_float == 7.5


def test_seeding_runs_on_video_connect_only():
    """Connecting a still must not change the duration, and disconnecting must
    not discard a value the user has since dialled in by hand."""
    connect = SOURCE.split("def connect_nodes(")[1].split("\ndef ")[0]

    assert "if source_type == 'VIDEO':" in connect
    assert "sync_video_duration_from_inputs(scene, target)" in connect
    # No other call site: the unlink paths must leave the value alone.
    assert len(re.findall(r"sync_video_duration_from_inputs\(", SOURCE)) == 2


def test_duration_parameter_name_is_a_documented_catalog_gap():
    constants = (MOODBOARD / "constants.py").read_text(encoding="utf-8")

    assert 'VIDEO_DURATION_PARAM_NAME = "duration"' in constants
    assert "KNOWN CATALOG GAP" in constants


def test_client_duration_is_advisory_not_the_submission_limit():
    """The backend parses the uploaded file and owns the combined-length cap;
    this helper must not become a second source of truth for it."""
    media_utils = (MOODBOARD / "core/media_utils.py").read_text(encoding="utf-8")

    helper = media_utils.split("def video_duration_seconds(")[1].split("\ndef ")[0]
    assert "movieclips.load" in helper
    assert "movieclips.remove" in helper
    assert "return None" in helper
