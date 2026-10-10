# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AI Provider Settings must not stack: invoke() refuses while it is open."""

import ast
from pathlib import Path

SRC = Path("src/scripts/mixar/modules/byok/ui/operators/byok_ops.py")


def _method(name):
    tree = ast.parse(SRC.read_text())
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "MIXAR_BYOK_OT_open_dialog":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == name:
                    return ast.get_source_segment(SRC.read_text(), fn)
    raise AssertionError(name)


def test_invoke_guards_and_sets_flag():
    src = _method("invoke")
    assert src.index("if _dialog_open") < src.index("byok_dialog_host.open_dialog")
    assert "_dialog_open = True" in src


def test_execute_and_cancel_clear_flag():
    assert "_dialog_open = False" in _method("execute")
    assert "_dialog_open = False" in _method("cancel")


def test_close_paths_give_the_island_back():
    """The dialog minimises an open island while it is up (the island is an
    always-on-top window and would cover it); both close paths owe a restore."""
    assert "byok_dialog_host.dialog_closed()" in _method("execute")
    assert "byok_dialog_host.dialog_closed()" in _method("cancel")
