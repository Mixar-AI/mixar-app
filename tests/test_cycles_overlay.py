# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drift pins for the Cycles addon overlay.

``src/intern/cycles/blender/addon/properties.py`` is a whole-file overlay of
the upstream Cycles addon whose ONLY intended divergence is the scene
``device`` default ('CPU' → 'GPU') plus its Mixar marker comment and the
added SPDX line. A whole-file overlay silently reverts every upstream change
to that file on the next Blender bump, so the divergence must stay minimal
and auditable — this test fails if anything else creeps in, and the
``.overlay_manifest`` build check flags the upstream side.

Skipped when ``upstream/`` is absent (linked worktrees don't carry the
multi-GB submodule).
"""

import difflib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src" / "intern" / "cycles" / "blender" / "addon" / "properties.py"
UPSTREAM = ROOT / "upstream" / "intern" / "cycles" / "blender" / "addon" / "properties.py"

pytestmark = pytest.mark.skipif(
    not UPSTREAM.exists(), reason="upstream/ not present in this checkout"
)


def _divergence():
    diff = difflib.unified_diff(
        UPSTREAM.read_text().splitlines(),
        OVERLAY.read_text().splitlines(),
        lineterm="",
        n=0,
    )
    added, removed = [], []
    for line in diff:
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added.append(line[1:].strip())
        elif line.startswith("-"):
            removed.append(line[1:].strip())
    return added, removed


def test_overlay_diverges_only_in_device_default():
    added, removed = _divergence()

    assert removed == ["default='CPU',"], (
        "unexpected upstream lines removed by the Cycles overlay: %r" % removed
    )

    assert "default='GPU'," in added
    for line in added:
        ok = (
            line == "default='GPU',"
            or line.startswith("# Mixar")
            or line.startswith("#")  # continuation lines of the marker comment
            or line.startswith("# SPDX-FileCopyrightText: 2026 Adeveda")
        )
        assert ok, "unexpected line added by the Cycles overlay: %r" % line


def test_overlay_is_tracked_by_conflict_manifest_finder():
    """The overlay must live where check_overlay_conflicts.sh's src/ scan and
    overlay.sh's whole-tree rsync both pick it up (src mirrors the Blender
    tree root — intern/, not source/)."""
    assert OVERLAY.exists()
    assert (ROOT / "src" / "intern").is_dir()
