# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the bundled operator's execute with isolated Blender/export dependencies."""
import ast
import datetime
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'src/scripts/addons_core/io_scene_gltf2/__init__.py'


def execute_method():
    tree = ast.parse(SOURCE.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ExportGLTF2_Base')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
    # Substitute only imports; execute the entire real settings/control flow.
    method.body = [n for n in method.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    return compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), 'exec')


class Operator:
    filepath = 'fixture.glb'
    export_vertex_color = 'NONE'
    check = Mock()

    def __getattr__(self, name):
        return False


@pytest.mark.parametrize('level', [-1, -10, 0, 10, 20, 30, 40, 50])
@pytest.mark.parametrize('automatic', [10, 20, 50])
def test_execute_initializes_logger_and_reaches_save(level, automatic):
    log = Mock()
    log.messages.return_value = []
    factory = Mock(return_value=log)
    debug = Mock(return_value=automatic)
    save = Mock(return_value={'FINISHED'})
    env = dict(os=os, datetime=datetime, sys=sys,
               bpy=SimpleNamespace(app=SimpleNamespace(debug_value=0),
                                   context=SimpleNamespace(preferences=SimpleNamespace(addons={}))),
               Log=factory, set_debug_log=debug,
               is_draco_available=lambda: False, is_meshopt_available=lambda: False,
               path_to_uri=lambda path: path, export_user_extensions=Mock(),
               gltf2_blender_export=SimpleNamespace(save=save))
    exec(execute_method(), env)
    operator = Operator()
    operator.export_loglevel = level
    operator.export_texture_dir = ''
    context = SimpleNamespace(space_data=None, scene=SimpleNamespace())
    assert env['execute'](operator, context) == {'FINISHED'}
    factory.assert_called_once_with(automatic if level < 0 else level)
    assert debug.call_count == (1 if level < 0 else 0)
    save.assert_called_once()
    assert save.call_args.args[1]['gltf_loglevel'] == level
    log.flush.assert_called_once()
