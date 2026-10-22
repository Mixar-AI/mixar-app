# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Undo Whole Document + per-tab redo + an edit keeps the redone step (2026-10-15)."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from test_undo_isolation import BINARY, HERE

SCRIPT = HERE / "undo_lab_whole_doc_redo_push.py"
pytestmark = pytest.mark.skipif(BINARY is None, reason="no Mixar bundle (set MIXAR_APP or build build/Dev)")


def test_a_push_never_frees_a_step_a_tab_redid_after_undo_whole_document(tmp_path):
    env = dict(os.environ, MIXAR_PER_TAB_UNDO="1", MIXAR_UNDO_LAB_OUT=str(tmp_path))
    proc = subprocess.run([str(BINARY), "--background", "--factory-startup", "--python", str(SCRIPT)],
                          env=env, capture_output=True, text=True, timeout=300)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("WDRP ")), None)
    assert line, f"no result; rc={proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    result = json.loads(line[5:])
    assert all(result.values()), result
