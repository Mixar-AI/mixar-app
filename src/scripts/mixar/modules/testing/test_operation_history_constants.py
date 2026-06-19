# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the operation_history.constants module."""

import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))  # -> src/scripts
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from mixar.modules.operation_history import constants as C


def test_kinds_and_sources_defined():
    assert C.KIND_OPERATION == "operation"
    assert C.KIND_QUERY == "query"
    assert C.KIND_META == "meta"
    assert C.SOURCE_AGENT == "AGENT"
    assert C.SOURCE_USER == "USER"


def test_read_only_and_history_tool_sets():
    assert "scene_overview" in C.READ_ONLY_TOOLS
    assert "get_scene_state" in C.READ_ONLY_TOOLS
    assert "get_operation_history" in C.HISTORY_TOOLS


def test_caps_are_positive_ints():
    assert C.MAX_LIST_RESULTS > 0
    assert C.MAX_SCRIPT_CHARS > 0
