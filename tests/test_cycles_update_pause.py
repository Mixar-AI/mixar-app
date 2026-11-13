# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the shipped callback without importing Blender's RNA types."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = 'intern/cycles/blender/addon/properties.py'


def callback():
    path = ROOT / 'src' / RELATIVE
    tree = ast.parse(path.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == 'update_pause')
    namespace = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['update_pause']


def test_update_pause_without_editor_area():
    assert callback()(None, SimpleNamespace(area=None)) is None


def test_update_pause_redraws_existing_area():
    area = SimpleNamespace(tag_redraw=Mock())
    callback()(None, SimpleNamespace(area=area))
    area.tag_redraw.assert_called_once_with()


def test_overlay_only_changes_update_pause():
    def without_callback(path):
        tree = ast.parse(path.read_text())
        tree.body = [n for n in tree.body if not (
            isinstance(n, ast.FunctionDef) and n.name == 'update_pause')]
        return ast.dump(tree)
    assert without_callback(ROOT / 'src' / RELATIVE) == without_callback(
        ROOT / 'upstream' / RELATIVE)
