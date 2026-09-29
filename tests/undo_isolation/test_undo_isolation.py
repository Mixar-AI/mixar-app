# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Runs the per-tab undo isolation lab inside a built Mixar bundle.

Skipped unless a bundle is found: ``MIXAR_APP`` (path to ``Mixar.app`` or
its ``MacOS/Mixar`` binary) or the repo's own ``build/Dev/bin/Mixar.app``.
The ``document`` contract is what the current build does and must keep
doing until the per-tab undo flag ships; the ``isolation`` contract is the
target and is expected to fail until then (``xfail``, not strict, so the day
it passes shows up as XPASS rather than breaking the run).
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
LAB = HERE / "undo_isolation_lab.py"


def _binary() -> pathlib.Path | None:
    candidates = []
    if os.environ.get("MIXAR_APP"):
        candidates.append(pathlib.Path(os.environ["MIXAR_APP"]))
    candidates.append(REPO / "build" / "Dev" / "bin" / "Mixar.app")
    for c in candidates:
        if c.is_dir() and c.suffix == ".app":
            c = c / "Contents" / "MacOS" / "Mixar"
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


BINARY = _binary()
pytestmark = pytest.mark.skipif(BINARY is None, reason="no Mixar bundle (set MIXAR_APP or build build/Dev)")


def run_lab(expect: str, tmp_path: pathlib.Path) -> dict:
    # MIXAR_PER_TAB_UNDO=1 turns on the M1 tagging/owner-map view so the lab's M1
    # probes run; the restore is unchanged by it until M2.
    env = dict(os.environ, MIXAR_UNDO_LAB_EXPECT=expect, MIXAR_UNDO_LAB_OUT=str(tmp_path),
               MIXAR_PER_TAB_UNDO="1")
    proc = subprocess.run(
        [str(BINARY), "--background", "--factory-startup", "--python", str(LAB)],
        env=env, capture_output=True, text=True, timeout=300,
    )
    lines = [l for l in proc.stdout.splitlines() if l.startswith(("M0 ", "M1 "))]
    sys.stdout.write("\n".join(lines) + "\n")
    report_path = tmp_path / "report.json"
    assert report_path.exists(), f"no report; rc={proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    report = json.loads(report_path.read_text())
    report["returncode"] = proc.returncode
    return report


def test_document_wide_undo_is_what_the_build_does_today(tmp_path):
    report = run_lab("document", tmp_path)
    failed = [v for v in report["verdicts"] if not v["ok"]]
    assert not failed, failed
    assert report["returncode"] == 0


@pytest.mark.xfail(reason="per-tab undo not built yet (design M2+)", strict=False)
def test_per_tab_isolation(tmp_path):
    report = run_lab("isolation", tmp_path)
    failed = [v for v in report["verdicts"] if not v["ok"]]
    assert not failed, failed
    assert report["returncode"] == 0
