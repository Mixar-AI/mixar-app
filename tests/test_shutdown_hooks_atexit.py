# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pin the atexit shutdown contract.

Python finalization (`BPY_python_end`) runs AFTER `BKE_blender_free()` in
`WM_exit_ex`, so the atexit mirror of `_run_all_cleanups` executes with
`bpy.data` and the spacetype draw-handler registries already freed. Any
RNA/ID-property write or draw-handler removal on that path is a
use-after-free segfault on quit. These tests pin the two halves of the
guard at source level (bpy is a MagicMock here, so behaviour cannot be
exercised end-to-end).
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "scripts" / "mixar"

TOAST_TIMER = SRC / "modules" / "common" / "notifications" / "toast_timer.py"
SHUTDOWN_HOOKS = SRC / "bootstrap" / "shutdown_hooks.py"


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


class TestToastTimerAppExitGuard:
    def test_cleanup_accepts_app_exit(self):
        tree = ast.parse(TOAST_TIMER.read_text())
        fn = _function(tree, "cleanup_toast_timer")
        assert "app_exit" in [a.arg for a in fn.args.args], (
            "cleanup_toast_timer must take app_exit so the atexit path can "
            "skip freed-data access"
        )

    def test_rna_write_and_draw_handler_are_gated(self):
        """The WM flag write and draw-handler removal must sit under a
        `not app_exit` branch — both dereference freed data at atexit."""
        tree = ast.parse(TOAST_TIMER.read_text())
        fn = _function(tree, "cleanup_toast_timer")

        guarded_calls = set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            is_not_app_exit = (
                isinstance(test, ast.UnaryOp)
                and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Name)
                and test.operand.id == "app_exit"
            )
            if not is_not_app_exit:
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    guarded_calls.add(sub.func.id)

        assert "_set_toasts_visible_flag" in guarded_calls
        assert "remove_draw_handler" in guarded_calls


class TestShutdownHooksPassReason:
    def test_atexit_reason_reaches_toast_cleanup(self):
        """_run_all_cleanups must forward app_exit=(reason == "atexit") to
        cleanup_toast_timer via _safe."""
        tree = ast.parse(SHUTDOWN_HOOKS.read_text())
        fn = _function(tree, "_run_all_cleanups")

        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_safe"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "cleanup_toast_timer"
            ):
                kw = {k.arg: k for k in node.keywords}
                assert "app_exit" in kw, "cleanup_toast_timer must get app_exit"
                expr = ast.unparse(kw["app_exit"].value)
                assert "atexit" in expr and "reason" in expr
                return
        raise AssertionError("_safe('cleanup_toast_timer', ...) call not found")
