# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A Generate Video node's output duration is seeded from the videos feeding it.

``seed_video_duration`` runs against stand-in nodes with an injected
``measure``, so the real arithmetic is executed; the connect-path wiring is
pinned at source level because ``node_graph`` needs Blender to import.
"""

import importlib
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

MOODBOARD = Path(__file__).resolve().parents[2] / "src/scripts/mixar/modules/moodboard"


def _load_module():
    # moodboard/core/__init__ imports the job queue and auth stack; load the
    # two standalone files under a throwaway package instead.
    package = ModuleType("moodboard_core_under_test")
    package.__path__ = [str(MOODBOARD / "core")]
    sys.modules.setdefault(package.__name__, package)
    return importlib.import_module(f"{package.__name__}.video_duration_seed")


video_duration_seed = _load_module()
seed_video_duration = video_duration_seed.seed_video_duration


def _parameter(name="duration", kind='INTEGER', minimum=4.0, maximum=30.0, value=5):
    return SimpleNamespace(
        name=name, parameter_type=kind, minimum=minimum, maximum=maximum,
        value_integer=value, value_float=float(value),
    )


def _node(parameters, action_type='VIDEO_GEN'):
    return SimpleNamespace(action_type=action_type, parameters=parameters)


def _seed(parameter, *lengths, action_type='VIDEO_GEN'):
    items = list(range(len(lengths)))
    return seed_video_duration(
        _node([parameter], action_type), items, measure=lambda i: lengths[i])


def test_single_video_seeds_its_own_length():
    parameter = _parameter()
    assert _seed(parameter, 12.0) is True
    assert parameter.value_integer == 12


def test_multiple_videos_sum_because_references_read_as_one_timeline():
    parameter = _parameter()
    assert _seed(parameter, 6.0, 7.0) is True
    assert parameter.value_integer == 13


def test_total_is_clamped_to_the_schema_bounds():
    """A 40s reference must not submit a duration the model rejects after
    credits are held."""
    parameter = _parameter()
    _seed(parameter, 40.0)
    assert parameter.value_integer == 30


def test_a_fractional_second_rounds_up_rather_than_truncating():
    parameter = _parameter()
    _seed(parameter, 12.4)
    assert parameter.value_integer == 13


def test_float_error_on_a_whole_second_clip_does_not_inflate():
    parameter = _parameter()
    _seed(parameter, 5.0000001)
    assert parameter.value_integer == 5


def test_a_fractional_bound_cannot_admit_an_integer_outside_it():
    parameter = _parameter(minimum=4.5, maximum=29.5)
    _seed(parameter, 4.2)
    assert parameter.value_integer == 5
    _seed(parameter, 29.9)
    assert parameter.value_integer == 29


def test_bounds_with_no_representable_integer_are_a_no_op():
    parameter = _parameter(minimum=4.2, maximum=4.8, value=5)
    assert _seed(parameter, 4.5) is False
    assert parameter.value_integer == 5


def test_unbounded_integer_stays_inside_a_c_int():
    """Unbounded params keep the +/-1e18 sentinels; the clamp must not hand
    value_integer a bound it cannot hold."""
    parameter = _parameter(minimum=-1.0e18, maximum=1.0e18)
    assert _seed(parameter, 9.0) is True
    assert parameter.value_integer == 9


def test_short_input_is_raised_to_the_minimum():
    parameter = _parameter(minimum=4.0)
    _seed(parameter, 1.5)
    assert parameter.value_integer == 4


def test_unreadable_video_leaves_the_catalog_default_untouched():
    parameter = _parameter(value=5)
    assert _seed(parameter, None) is False
    assert parameter.value_integer == 5


def test_a_model_without_a_duration_parameter_is_a_no_op():
    assert _seed(_parameter(name="length"), 9.0) is False


def test_non_video_nodes_are_never_seeded():
    parameter = _parameter()
    assert _seed(parameter, 9.0, action_type='IMAGE_GEN') is False
    assert parameter.value_integer == 5


def test_float_parameters_keep_sub_second_precision():
    parameter = _parameter(kind='FLOAT')
    assert _seed(parameter, 7.5) is True
    assert parameter.value_float == 7.5


def test_still_media_has_no_duration():
    still = SimpleNamespace(image=SimpleNamespace(source='FILE', filepath="a.png"))
    assert video_duration_seed.video_duration_seconds(still) is None


def test_seeding_runs_on_video_connect_only():
    """A still must not change the duration, and unlinking must not discard a
    value the user has since dialled in. connect_to_next_input routes through
    connect_nodes, so this one call covers both connect paths."""
    source = (MOODBOARD / "core/node_graph.py").read_text(encoding="utf-8")
    connect = source.split("def connect_nodes(")[1].split("\ndef ")[0]
    assert "if source_type == 'VIDEO':" in connect
    assert "seed_video_duration(target, input_media_items(scene, target))" in connect
    assert len(re.findall(r"seed_video_duration\(", source)) == 1
    follow = source.split("def connect_to_next_input(")[1].split("\ndef ")[0]
    assert "return connect_nodes(" in follow


def test_client_duration_is_advisory_and_frees_its_clip():
    source = (MOODBOARD / "core/video_duration_seed.py").read_text(encoding="utf-8")
    helper = source.split("def video_duration_seconds(")[1].split("\ndef ")[0]
    assert "movieclips.load" in helper and "movieclips.remove" in helper
    assert "KNOWN CATALOG GAP" in source
