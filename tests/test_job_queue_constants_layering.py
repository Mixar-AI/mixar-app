# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The job-queue framework's constants own their values; no feature imports.

``common/job_queue/constants.py`` once re-exported its poll constants from
``hunyuan.constants``, so loading the shared queue ran ``hunyuan/__init__``
(and its UI properties) first, and a broken or renamed feature module took the
whole queue down. The dependency must point feature -> common, never back.
"""

import ast
from pathlib import Path

CONSTANTS = (Path(__file__).resolve().parents[1] / "src" / "scripts" / "mixar"
             / "modules" / "common" / "job_queue" / "constants.py")


def test_constants_import_no_mixar_module():
    tree = ast.parse(CONSTANTS.read_text())
    imported = [
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    assert not [m for m in imported if m and m.startswith("mixar.modules")]


def test_poll_constants_defined_here():
    names = {
        target.id
        for node in ast.parse(CONSTANTS.read_text()).body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert {"MAX_POLL_DURATION", "MAX_CONSECUTIVE_POLL_ERRORS"} <= names
