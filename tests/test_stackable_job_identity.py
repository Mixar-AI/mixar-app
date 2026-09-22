# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Interactive 3D submits must stack — unique label, clean display_label."""

from pathlib import Path

from mixar.modules.common.job_queue.core.labels import stackable_job_identity


ROOT = Path(__file__).resolve().parents[1]
OPS = {
    "model_gen": ROOT
    / "src/scripts/mixar/modules/moodboard/ui/operators/model_gen_ops.py",
    "image_to_3d": ROOT
    / "src/scripts/mixar/modules/moodboard/ui/operators/image_to_3d_ops.py",
    "chat_generate": ROOT
    / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/generate_ops.py",
}


def test_stackable_job_identity_keeps_a_clean_display_and_unique_label():
    label_a, display_a = stackable_job_identity("hero_ref")
    label_b, display_b = stackable_job_identity("hero_ref")
    assert display_a == "hero_ref"
    assert display_b == "hero_ref"
    assert label_a != label_b
    assert label_a.startswith("hero_ref [")
    assert label_b.startswith("hero_ref [")
    assert label_a.endswith("]")
    assert len(label_a.split("[")[1].rstrip("]")) == 4


def test_stackable_job_identity_falls_back_when_display_is_blank():
    label, display = stackable_job_identity("   ")
    assert display == "3D model"
    assert label.startswith("3D model [")


def test_interactive_3d_enqueue_paths_use_stackable_identity():
    """FeatureQueue.submit dedups on label for the whole active lifetime.
    Using the source image name as the label locked a second model from the
    same reference behind 'A duplicate generation is already queued'.
    """
    for name, path in OPS.items():
        source = path.read_text(encoding="utf-8")
        assert "stackable_job_identity" in source, name
        assert "display_label=" in source or "display_label =" in source, name
    # Agent-direct / graph node paths keep their own already-running guards —
    # do not uniquify those labels and silently drop their duplicate refusal.
    node = (
        ROOT
        / "src/scripts/mixar/modules/moodboard/core/node_execution.py"
    ).read_text(encoding="utf-8")
    assert "stackable_job_identity" not in node
