# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Who opened the tour, and why it stopped, reach the tour telemetry.

Operators and menus cannot be imported outside Blender (their base classes
are mocks), so their wiring is pinned at source level."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "scripts" / "mixar" / "modules"
ONBOARDING = ROOT / "onboarding"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _calls_with(path: Path, func_name: str) -> list:
    tree = ast.parse(_source(path))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", None)) == func_name]


def test_auto_start_callers_name_their_source():
    auth = ROOT / "auth" / "core" / "auth_hooks.py"
    mode = ROOT / "workflow" / "ui" / "operators" / "ui_mode_ops.py"
    for path, source in ((auth, "START_SOURCE_AUTO_SIGNIN"), (mode, "START_SOURCE_AUTO_MODE")):
        calls = _calls_with(path, "maybe_show_tour")
        assert calls and all(any(getattr(a, "id", None) == source for a in c.args)
                             for c in calls), path.name


def test_the_help_menu_entry_is_a_help_menu_start():
    text = _source(ONBOARDING / "ui" / "menus" / "help_menu.py")
    assert "op.start_source = START_SOURCE_HELP_MENU" in text


def test_the_modal_carries_the_source_and_a_quit_aware_cancel():
    op = ONBOARDING / "ui" / "operators" / "tour_modal_op.py"
    text = _source(op)
    assert "start_source: EnumProperty(" in text
    assert "start_source=self.start_source" in text
    cancel = next(n for n in ast.walk(ast.parse(text))
                  if isinstance(n, ast.FunctionDef) and n.name == "cancel")
    assert "session_lifecycle.cancel_reason()" in ast.unparse(cancel)
    # The tour events carry the source, so the modal stays out of
    # product.operator noise.
    from mixar.modules.common.analytics.constants import IGNORED_OPERATORS
    assert "mixar.onboarding_tour" in IGNORED_OPERATORS


def test_exit_pre_marks_the_app_as_exiting():
    text = _source(ONBOARDING / "ui" / "properties" / "tour_props.py")
    assert "bpy.app.handlers.exit_pre.append(_on_exit_pre)" in text
    assert "bpy.app.handlers.exit_pre.remove(_on_exit_pre)" in text
    assert "session_lifecycle.note_app_exiting()" in text
