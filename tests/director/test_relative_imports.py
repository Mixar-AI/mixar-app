# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every relative import in the module resolves to a real module.

Moving a file changes what `...` means, and the callbacks in
`core/property_updates.py` are all wrapped in `try/except Exception` because a
property update must never raise into Blender's file loader. Those two facts
together are silent: a wrong depth raises ImportError, the except swallows it,
and the feature simply stops happening — tracking, handheld, interpolation and
the Speed slider all went quiet that way at once when the callbacks moved out
of `ui/properties/` into `core/`.

`bpy` is a MagicMock here, so importing the modules proves nothing about the
paths; the check is static.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src/scripts/mixar"
MODULE = PACKAGE / "modules/director"


def _unresolved(path: Path) -> list[tuple[int, str]]:
    package_parts = list(path.relative_to(PACKAGE.parent).parts[:-1])
    problems = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        climb = node.level - 1
        if climb > len(package_parts):
            problems.append((node.lineno, f"{'.' * node.level}{node.module or ''}"))
            continue
        base = package_parts[: len(package_parts) - climb]
        target = base + (node.module.split(".") if node.module else [])
        candidate = PACKAGE.parent.joinpath(*target)
        if candidate.with_suffix(".py").exists() or candidate.is_dir():
            continue
        problems.append((node.lineno, f"{'.' * node.level}{node.module or ''}"))
    return problems


def test_every_relative_import_in_director_resolves():
    broken = [
        f"{path.relative_to(ROOT)}:{line}  from {spec}"
        for path in sorted(MODULE.rglob("*.py"))
        for line, spec in _unresolved(path)
    ]
    assert not broken, "unresolved relative imports:\n  " + "\n  ".join(broken)


def test_the_checker_catches_the_depth_that_broke():
    """`core/property_updates.py` reaching for `...core.tracking` resolves to
    `modules.core.tracking`, which does not exist."""
    source = (MODULE / "core/property_updates.py").read_text(encoding="utf-8")
    assert "from ...core." not in source
    assert "from ...core import" not in source
    # The lazy imports are still lazy (they break an import cycle), just at
    # the right depth.
    for module in ("beat_sync", "handheld", "interpolation", "retime", "tracking"):
        assert f"from .{module} import" in source or f"from . import {module}" in source


# -------------------------------------------------------------------------
# Names a module uses but never binds.
#
# The sibling failure mode: an import that resolves, removed or renamed while
# a use of it stays behind. Nothing in the source-level suite sees it, because
# it is a NameError at CALL time, in a branch a test may never take — and
# Director wraps its property callbacks in `except Exception`, which swallows
# exactly this.


def _unbound(path: Path) -> list[str]:
    """Names loaded in *path* that nothing in it binds, or ``[]``.

    A module using ``import *`` cannot be checked this way and is skipped
    rather than guessed at.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    bound = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__", "__path__"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    return []
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Global):
            bound.update(node.names)
    used = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    return sorted(used - bound)


def test_every_name_director_uses_is_bound_in_its_module():
    broken = [
        f"{path.relative_to(ROOT)}: {', '.join(names)}"
        for path in sorted(MODULE.rglob("*.py"))
        for names in [_unbound(path)]
        if names
    ]
    assert not broken, "names used but never bound:\n  " + "\n  ".join(broken)
