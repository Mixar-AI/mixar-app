# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A generated model lands where the user pointed, without a follow-up turn.

A 3D job outlives the agent's turn and used to import at the world origin;
the agent could only say "after import it still needs to be positioned".
Placement now rides with the job and is applied by the post-import hook.
What is pinned: the spec parsing, the matrix maths (pure), and that every
agent-facing 3D operator threads the placement through to the hook.
"""

import json
import math
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# The job_queue package imports the API client, which imports auth, which
# imports keyring on non-Windows — a runtime dependency the standalone suite
# does not have. Stubbed here the way test_auth_refresh does, so this file
# runs alone as well as inside the full session (where mock_bpy stubs it).
sys.modules.setdefault("keyring", MagicMock())

from mixar.modules.common.job_queue.core import placement as P  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "src/scripts/mixar/modules"


def source(rel):
    return (MODULES / rel).read_text()


# =============================================================================
# Reading the spec
# =============================================================================

class TestNormalize:
    def test_location_is_the_only_requirement(self):
        assert P.normalize_placement({"location": [1, 2, 3]}) == {"location": [1.0, 2.0, 3.0]}

    def test_no_location_is_no_placement(self):
        assert P.normalize_placement({"normal": [0, 0, 1]}) is None
        assert P.normalize_placement({"location": [1, 2]}) is None
        assert P.normalize_placement({"location": [1, 2, float("nan")]}) is None
        assert P.normalize_placement("nope") is None
        assert P.normalize_placement(None) is None

    def test_the_normal_is_unit_length(self):
        spec = P.normalize_placement({"location": [0, 0, 0], "normal": [0, 0, 5]})
        assert spec["normal"] == [0.0, 0.0, 1.0]

    def test_a_zero_normal_is_dropped_not_divided_by(self):
        spec = P.normalize_placement({"location": [0, 0, 0], "normal": [0, 0, 0]})
        assert "normal" not in spec

    def test_size_must_be_positive_and_sane(self):
        assert "size" in P.normalize_placement({"location": [0, 0, 0], "size": 0.3})
        assert "size" not in P.normalize_placement({"location": [0, 0, 0], "size": 0})
        assert "size" not in P.normalize_placement({"location": [0, 0, 0], "size": -1})
        assert "size" not in P.normalize_placement({"location": [0, 0, 0], "size": 1e9})

    def test_labels_are_bounded_and_a_bool_is_not_a_mark(self):
        spec = P.normalize_placement({
            "location": [0, 0, 0], "on": " Tree " + "x" * 300, "mark": True,
        })
        assert len(spec["on"]) == 128
        assert "mark" not in spec
        assert P.normalize_placement({"location": [0, 0, 0], "mark": 3})["mark"] == 3


class TestParse:
    def test_json_text_from_the_operator_property(self):
        spec = P.parse_placement(json.dumps({"location": [1, 2, 3], "on": "Tree"}))
        assert spec == {"location": [1.0, 2.0, 3.0], "on": "Tree"}

    def test_empty_and_broken_text_are_no_placement(self):
        assert P.parse_placement("") is None
        assert P.parse_placement("   ") is None
        assert P.parse_placement("{not json") is None
        assert P.parse_placement(None) is None


# =============================================================================
# The matrix — pure
# =============================================================================

def approx(a, b, tol=1e-9):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


class TestMatrix:
    def test_an_upright_placement_only_translates(self):
        m = P.placement_matrix([1, 2, 3])
        assert approx(P.transform_point(m, (0, 0, 0)), [1, 2, 3])
        assert approx(P.transform_point(m, (0, 0, 1)), [1, 2, 4])

    def test_the_base_stays_on_the_target_whatever_the_normal(self):
        for normal in ([1, 0, 0], [0, -1, 0], [0, 0, -1], [0.3, 0.4, 0.5]):
            length = math.sqrt(sum(c * c for c in normal))
            unit = [c / length for c in normal]
            m = P.placement_matrix([5, 6, 7], unit, 33.0, 2.5)
            assert approx(P.transform_point(m, (0, 0, 0)), [5, 6, 7])

    def test_up_is_carried_onto_the_normal(self):
        m = P.placement_matrix([0, 0, 0], [1, 0, 0])
        assert approx(P.transform_point(m, (0, 0, 1)), [1, 0, 0])
        m = P.placement_matrix([0, 0, 0], [0, 0, -1])
        assert approx(P.transform_point(m, (0, 0, 1)), [0, 0, -1])
        unit = [1 / math.sqrt(3)] * 3
        m = P.placement_matrix([0, 0, 0], unit)
        assert approx(P.transform_point(m, (0, 0, 1)), unit)

    def test_the_tilt_is_a_proper_rotation(self):
        for normal in ([1, 0, 0], [0, 1, 0], [0.6, 0, 0.8], [-0.1, 0.7, 0.7071]):
            length = math.sqrt(sum(c * c for c in normal))
            r = P.rotation_to_normal([c / length for c in normal])
            for i in range(3):
                for j in range(3):
                    dot = sum(r[k][i] * r[k][j] for k in range(3))
                    assert abs(dot - (1.0 if i == j else 0.0)) < 1e-9

    def test_yaw_turns_the_model_about_its_up_axis(self):
        m = P.placement_matrix([0, 0, 0], None, 90.0)
        assert approx(P.transform_point(m, (1, 0, 0)), [0, 1, 0])
        assert approx(P.transform_point(m, (0, 0, 1)), [0, 0, 1])

    def test_yaw_happens_before_the_tilt(self):
        """Yaw while upright, then lean onto the surface: a bird facing -Y on
        the ground still faces along the branch after the tilt."""
        m = P.placement_matrix([0, 0, 0], [1, 0, 0], 90.0)
        # +X yawed 90 about Z is +Y; tilting +Z onto +X rotates about Y, which
        # leaves +Y alone.
        assert approx(P.transform_point(m, (1, 0, 0)), [0, 1, 0])

    def test_scale_grows_the_model_about_its_base(self):
        m = P.placement_matrix([1, 1, 0], None, 0.0, 2.0)
        assert approx(P.transform_point(m, (0, 0, 1)), [1, 1, 2])
        assert approx(P.transform_point(m, (0, 0, 0)), [1, 1, 0])


class TestApply:
    def test_no_location_touches_nothing_and_never_raises(self):
        assert P.apply_placement("Mesh", {"size": 2}) is False
        assert P.apply_placement("Mesh", None) is False

    def test_a_mocked_scene_never_raises(self):
        """bpy is a MagicMock here; whatever it answers, the hook must not
        take the import down with it."""
        P.apply_placement("Mesh", {"location": [1, 2, 3], "normal": [0, 0, 1], "size": 0.3})

    def test_describe_reads_like_a_queue_row(self):
        text = P.describe_placement({"location": [1, 2, 3], "on": "Tree", "size": 0.3})
        assert text == "placed at (1, 2, 3) on Tree, 0.3 m across"
        assert P.describe_placement(None) == ""


# =============================================================================
# Wiring — every agent-facing 3D operator threads placement to the hook
# =============================================================================

class TestWiring:
    def test_both_agent_operators_expose_placement(self):
        for rel in ("moodboard/ui/operators/image_to_3d_ops.py",
                    "hunyuan/ui/operators/hunyuan_ops.py"):
            text = source(rel)
            assert "placement: " in text and "StringProperty(default=\"\")" in text, rel
            assert "parse_placement(self.placement)" in text, rel

    def test_the_rapid_pro_and_model_3d_paths_all_hand_it_to_the_hook(self):
        hunyuan = source("hunyuan/ui/operators/hunyuan_ops.py")
        pro = hunyuan[hunyuan.index("def _submit_pro_direct"):hunyuan.index("def _resolve_turnaround")]
        assert "placement=parse_placement(self.placement)" in pro
        rapid = hunyuan[hunyuan.index("def _submit_rapid_direct"):hunyuan.index("def _submit_topology_direct")]
        assert "placement=parse_placement(self.placement)" in rapid
        model3d = source("moodboard/ui/operators/image_to_3d_ops.py")
        direct = model3d[model3d.index("def _execute_direct"):]
        assert "placement=placement" in direct

    def test_enqueue_pro_job_accepts_placement(self):
        text = source("moodboard/core/generation_enqueue.py")
        sig = text[text.index("def enqueue_pro_job"):text.index("def enqueue_scene_gen_hp_jobs")]
        assert "placement: Optional[dict] = None" in sig
        assert "placement=placement" in sig

    def test_the_hook_places_only_a_normalized_import(self):
        """Placement assumes the base is at the origin — the state
        rename_generated_model leaves. A failed rename must not place."""
        text = source("moodboard/core/generation_enqueue.py")
        hook = text[text.index("def make_model_rename_on_imported"):text.index("def make_texture_reimport_on_imported")]
        assert hook.index("rename_generated_model(") < hook.index("apply_placement(")
        assert "if placement and final:" in hook

    def test_the_hook_places_before_the_material_pass(self):
        text = source("moodboard/core/generation_enqueue.py")
        hook = text[text.index("def make_model_rename_on_imported"):text.index("def make_texture_reimport_on_imported")]
        assert hook.index("apply_placement(") < hook.index("convert_imported_material_to_paint_layers(")

    def test_placement_works_on_the_root_of_the_import(self):
        """A Trellis result is a mesh under an Empty; moving only the mesh
        would tear it off its parent's transform."""
        text = source("common/job_queue/core/placement.py")
        body = text[text.index("def apply_placement"):]
        assert "root.parent" in body
        assert "root.matrix_world = Matrix(rows) @ root.matrix_world" in body
