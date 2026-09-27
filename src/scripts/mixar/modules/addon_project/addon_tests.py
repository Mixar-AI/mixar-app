# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The add-on's own unittest package, run inside Blender with bpy live."""

import contextlib
import importlib
import io
import sys
import unittest
from pathlib import Path

from .checks import _with_console, project_frames

def _import_root(root: Path, entrypoint: str) -> Path:
    top_level = entrypoint.split(".", 1)[0]
    if top_level == root.name and (root / "__init__.py").is_file():
        return root.parent
    return root


class _Result(unittest.TestResult):
    """One record per test: id, status, the first line of the failure and
    its project frames."""

    def __init__(self, root: Path, entrypoint: str):
        super().__init__()
        self.root, self.prefix, self.records = root, entrypoint + ".", []

    def _record(self, test, status, err=None):
        item = {"id": test.id().removeprefix(self.prefix), "status": status}
        if err is not None:
            kind, value, tb = err
            lines = [line for line in f"{kind.__name__}: {value}".splitlines() if line.strip()]
            # A module that failed to import arrives wrapped by the loader with
            # the real exception on its last line.
            item["message"] = (lines[-1] if "Failed to import test module" in lines[0] else lines[0])[:500]
            item["frames"] = project_frames(tb, self.root)
        self.records.append(item)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failed", err)

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", err)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records.append({"id": test.id().removeprefix(self.prefix), "status": "skipped", "message": reason})

    def addSubTest(self, test, subtest, err):
        # The base class files a failing subtest straight into failures /
        # errors without addFailure / addError, and the parent never gets
        # addSuccess — so record it here, under the subtest's own id.
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._record(subtest, "error" if issubclass(err[0], Exception) and not issubclass(err[0], test.failureException) else "failed", err)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.records.append({"id": test.id().removeprefix(self.prefix), "status": "failed",
                             "message": "unexpected success (marked expectedFailure)"})


# The datablock kinds a test typically creates. Whatever a test run adds to
# them is removed afterwards, so tests never leave meshes, materials or
# objects behind in the user's file (orphans would be saved with it).
_DATA_KINDS = (
    "objects", "meshes", "materials", "collections", "images", "textures",
    "node_groups", "curves", "cameras", "lights", "actions", "armatures",
    "worlds", "texts",
)


def _data_snapshot(bpy) -> dict:
    snap = {}
    for kind in _DATA_KINDS:
        try:
            snap[kind] = {block.as_pointer() for block in getattr(bpy.data, kind)}
        except Exception:
            continue
    return snap


def _remove_new_data(bpy, before: dict) -> int:
    """Remove every datablock of ``_DATA_KINDS`` created since ``before``."""
    created = []
    for kind, pointers in before.items():
        try:
            created.extend(
                block for block in getattr(bpy.data, kind)
                if block.as_pointer() not in pointers
            )
        except Exception:
            continue
    if not created:
        return 0
    try:
        bpy.data.batch_remove(created)
    except Exception:
        return 0
    return len(created)


@contextlib.contextmanager
def _fresh_scene(cleanup: dict | None = None):
    """Run tests in their own scene so they never touch the user's; restored
    and removed afterwards, together with every datablock the tests created
    (the count lands in ``cleanup["removed"]``). Without a window
    (background) the scene is only created and removed."""
    try:
        import bpy
        before = _data_snapshot(bpy)
        scene = bpy.data.scenes.new("mixar_addon_tests")
        window = bpy.context.window
    except Exception:
        yield
        return
    previous = getattr(window, "scene", None) if window else None
    try:
        if window:
            window.scene = scene
        yield
    finally:
        try:
            if window and previous is not None:
                window.scene = previous
            bpy.data.scenes.remove(scene)
        except Exception:
            pass
        removed = _remove_new_data(bpy, before)
        if cleanup is not None:
            cleanup["removed"] = removed


def run_addon_tests(root: Path, entrypoint: str, *, pattern: str = "test*.py") -> dict:
    """unittest discovery over ``<entrypoint>/tests`` (a package, so a test can
    ``from .. import ops``), on Blender's main thread with bpy live. Every test
    module is re-imported so an edited test runs as edited. Output is the
    per-test record list plus the console tail."""
    if not entrypoint:
        return {"success": False, "check": "tests", "message": "Set an entrypoint first", "tests": []}
    root = root.resolve(strict=True)
    import_root = _import_root(root, entrypoint)
    # A standalone project whose folder IS the package keeps its tests at
    # <root>/tests; a workspace add-on at <root>/<entrypoint>/tests.
    package_dir = root if import_root == root.parent else root / entrypoint
    tests_dir = package_dir / "tests"
    if not (tests_dir / "__init__.py").is_file():
        return {"success": False, "check": "tests", "tests": [],
                "message": f"No {entrypoint}/tests package (a tests/__init__.py beside test_*.py files)"}
    original_path = list(sys.path)
    console = io.StringIO()
    try:
        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))
        for name in list(sys.modules):
            if name == f"{entrypoint}.tests" or name.startswith(f"{entrypoint}.tests."):
                del sys.modules[name]
        importlib.invalidate_caches()
        result = _Result(root, entrypoint)
        with contextlib.redirect_stdout(console), contextlib.redirect_stderr(console):
            suite = unittest.TestLoader().discover(str(tests_dir), pattern=pattern, top_level_dir=str(import_root))
            cleanup = {}
            with _fresh_scene(cleanup):
                suite.run(result)
        counts = {status: sum(1 for r in result.records if r["status"] == status)
                  for status in ("passed", "failed", "error", "skipped")}
        ran = result.testsRun
        response = {
            "success": ran > 0 and result.wasSuccessful(),
            "check": "tests",
            "ran": ran,
            **counts,
            "tests": result.records,
            "cleaned_up": cleanup.get("removed", 0),
            "message": (", ".join(f"{n} {status}" for status, n in counts.items() if n) if ran
                        else f"No tests found under {entrypoint}/tests matching {pattern}"),
        }
        _with_console(response, console)
        return response
    except Exception as exc:
        response = {"success": False, "check": "tests", "tests": [],
                    "message": f"{type(exc).__name__}: {exc}", "frames": project_frames(exc, root)}
        _with_console(response, console)
        return response
    finally:
        sys.path[:] = original_path
