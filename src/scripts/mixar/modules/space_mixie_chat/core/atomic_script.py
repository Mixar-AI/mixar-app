# SPDX-License-Identifier: GPL-3.0-or-later
"""One undo boundary for synchronous sandbox scripts on Blender's main thread.

Blender's undo stack is global, not per scene. Suppress operator auto-pushes,
then push the final state and undo once on failure. Never run without a usable
checkpoint. Async/modal operators cannot participate in this transaction.
"""

import ast

import bpy


class AtomicScriptError(RuntimeError):
    pass


class AtomicOps:
    def __init__(self, target, path="", failures=None):
        self._target = target
        self._path = path
        self._failures = failures if failures is not None else []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        target = getattr(self._target, name)
        path = f"{self._path}.{name}".strip(".")
        if self._path:

            def call(*args, **kwargs):
                if path.startswith(("ed.undo", "ed.redo", "wm.")):
                    raise AtomicScriptError(
                        f"Operator {path} cannot run inside an atomic script"
                    )
                if args and args[0] != "EXEC_DEFAULT":
                    raise AtomicScriptError(
                        "Atomic scripts require synchronous EXEC_DEFAULT operators"
                    )
                result = target("EXEC_DEFAULT", False, **kwargs)
                if "CANCELLED" in result or "RUNNING_MODAL" in result:
                    self._failures.append(path)
                    raise AtomicScriptError(
                        f"Operator {path} did not finish: {sorted(result)}"
                    )
                return result

            return call
        return AtomicOps(target, path, self._failures)


class AtomicBpy:
    def __init__(self):
        self._failures = []
        self.ops = AtomicOps(bpy.ops, failures=self._failures)

    def __getattr__(self, name):
        return getattr(bpy, name)


def validate_atomic_source(script):
    """Reject imports that bypass the operator facade or launch deferred work."""
    tree = ast.parse(script)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise AtomicScriptError("Atomic scripts cannot access private attributes")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            if any(n.startswith(("mixar", "bpy.")) for n in names):
                raise AtomicScriptError(
                    "Atomic scripts cannot import add-on internals or bpy submodules"
                )
        if isinstance(node, ast.Attribute) and node.attr in {
            "timers",
            "handlers",
            "use_global_undo",
            "undo_steps",
            "undo_memory_limit",
        }:
            raise AtomicScriptError(f"Atomic scripts cannot modify {node.attr}")


def checkpoint(label):
    if not bpy.context.preferences.edit.use_global_undo:
        raise AtomicScriptError("Enable Global Undo before running an atomic script")
    if getattr(bpy.context, "mode", "OBJECT") != "OBJECT":
        raise AtomicScriptError("Switch to Object Mode before running an atomic script")
    if "FINISHED" not in bpy.ops.ed.undo_push(message=label):
        raise AtomicScriptError(
            "Could not create an undo checkpoint; script was not executed"
        )


def finish(success):
    if bpy.context.mode != "OBJECT" and "FINISHED" not in bpy.ops.object.mode_set(
        "EXEC_DEFAULT", False, mode="OBJECT"
    ):
        raise AtomicScriptError("Could not leave Edit Mode for rollback")
    checkpoint("Mixie atomic result")
    if not success and "FINISHED" not in bpy.ops.ed.undo():
        raise AtomicScriptError(
            "Atomic rollback failed; inspect the scene before continuing"
        )
