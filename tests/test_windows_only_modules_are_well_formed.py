# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows-only test modules are skipped everywhere else, so a mistake in
their wiring shows up only on the Windows box: a ``parametrize`` mark on a
helper is silently dropped, and the test that needed it then asks for a
fixture that does not exist. Read their source here instead, on every host.
"""

import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
BUILTIN_FIXTURES = {
    "tmp_path", "tmp_path_factory", "tmpdir", "monkeypatch", "capsys", "capfd", "caplog",
    "recwarn", "request", "pytestconfig",
}


def _skips_off_windows(node) -> bool:
    text = ast.unparse(node).replace('"', "'")
    return "skipif" in text and ("!= 'win32'" in text or "!= 'nt'" in text)


def _is_windows_only(tree) -> bool:
    """The whole module (``pytestmark``) or one of its tests runs on Windows only."""
    for node in tree.body:
        if (isinstance(node, ast.Assign) and _skips_off_windows(node.value)
                and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)):
            return True
        if isinstance(node, ast.FunctionDef) and any(
                _skips_off_windows(d) for d in node.decorator_list):
            return True
    return False


def _mark(decorator, name):
    call = decorator.func if isinstance(decorator, ast.Call) else decorator
    return ast.unparse(call).endswith(name)


def _fixtures(tree) -> set:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if _mark(decorator, "fixture"):
                    names.add(node.name)
                    for keyword in getattr(decorator, "keywords", ()):
                        if keyword.arg == "name":
                            names.add(ast.literal_eval(keyword.value))
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _argnames(decorator) -> set:
    first = decorator.args[0]
    value = ast.literal_eval(first)
    if isinstance(value, str):
        return {name.strip() for name in value.split(",")}
    return set(value)


WINDOWS_ONLY = sorted(
    path for path in TESTS.glob("test_*.py")
    if _is_windows_only(ast.parse(path.read_text(encoding="utf-8"))))


def test_the_windows_only_modules_are_found():
    names = {path.name for path in WINDOWS_ONLY}
    assert {"test_windows_update_process.py", "test_windows_toolchain.py",
            "test_windows_overlay.py"} <= names


@pytest.mark.parametrize("path", WINDOWS_ONLY, ids=lambda path: path.name)
def test_every_parametrize_mark_feeds_a_test(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    known = (BUILTIN_FIXTURES | _fixtures(tree)
             | _fixtures(ast.parse((TESTS / "conftest.py").read_text(encoding="utf-8")))
             | _fixtures(ast.parse((TESTS.parent / "conftest.py").read_text(encoding="utf-8"))))
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        marks = [d for d in node.decorator_list if _mark(d, "parametrize")]
        assert not marks or node.name.startswith("test_"), (
            f"{node.name}: parametrize on a helper is dropped")
        if not node.name.startswith("test_"):
            continue
        params = {arg.arg for arg in node.args.args}
        given = set().union(*(_argnames(mark) for mark in marks)) if marks else set()
        assert given <= params, (node.name, given - params)
        missing = params - given - known
        assert not missing, f"{node.name} asks for {sorted(missing)}, which nothing provides"
