# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify glTF export handles filesystem PermissionError/OSError cleanly (#2091)."""
import ast
import datetime
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'src/scripts/addons_core/io_scene_gltf2/__init__.py'


def execute_method():
    tree = ast.parse(SOURCE.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ExportGLTF2_Base')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
    method.body = [n for n in method.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    return compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), 'exec')


class Operator:
    filepath = '/readonly/out.glb'
    export_vertex_color = 'NONE'
    export_loglevel = 0
    export_texture_dir = ''
    export_current_frame = False

    def __init__(self):
        self.check = Mock()
        self.report = Mock()

    def __getattr__(self, name):
        return False


def _run_execute(save, *, operator=None, context=None, post_hook=None):
    log = Mock()
    log.messages.return_value = []
    hooks = post_hook or Mock()
    env = dict(
        os=os,
        datetime=datetime,
        sys=sys,
        bpy=SimpleNamespace(
            app=SimpleNamespace(debug_value=0),
            context=SimpleNamespace(preferences=SimpleNamespace(addons={})),
        ),
        Log=Mock(return_value=log),
        set_debug_log=Mock(return_value=20),
        is_draco_available=lambda: False,
        is_meshopt_available=lambda: False,
        path_to_uri=lambda path: path,
        export_user_extensions=hooks,
        gltf2_blender_export=SimpleNamespace(save=save),
    )
    exec(execute_method(), env)
    op = operator or Operator()
    ctx = context or SimpleNamespace(
        space_data=None,
        window=SimpleNamespace(cursor_set=Mock()),
        scene=SimpleNamespace(frame_current=42, frame_set=Mock()),
    )
    result = env['execute'](op, ctx)
    return result, op, ctx, log, hooks


def test_execute_reports_permission_error_and_restores_state():
    err = PermissionError(13, 'Permission denied', '/readonly/out.glb')
    save = Mock(side_effect=err)

    result, op, ctx, log, hooks = _run_execute(save)

    assert result == {'CANCELLED'}
    op.report.assert_called_once()
    level, message = op.report.call_args.args
    assert level == {'ERROR'}
    assert 'Permission denied' in message
    assert '/readonly/out.glb' in message
    log.error.assert_called_once_with(message)
    log.flush.assert_called_once()
    ctx.window.cursor_set.assert_called_once_with('DEFAULT')
    ctx.scene.frame_set.assert_called_once_with(42)
    # Only pre_export_hook runs; post_export_hook is skipped on failure.
    assert [call.args[0] for call in hooks.call_args_list] == ['pre_export_hook']


def test_execute_does_not_overwrite_readonly_file_on_permission_error(tmp_path):
    if os.geteuid() == 0:
        pytest.skip('root bypasses POSIX write-permission checks')

    target = tmp_path / 'protected.glb'
    original = b'existing-glb-bytes'
    target.write_bytes(original)
    target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    try:
        def failing_save(_context, export_settings):
            with open(export_settings['gltf_filepath'], 'wb') as handle:
                handle.write(b'new-bytes')
            return {'FINISHED'}

        op = Operator()
        op.filepath = str(target)
        op.export_current_frame = True
        result, op, ctx, log, _hooks = _run_execute(failing_save, operator=op)

        assert result == {'CANCELLED'}
        assert target.read_bytes() == original
        op.report.assert_called_once()
        assert op.report.call_args.args[0] == {'ERROR'}
        assert 'Permission denied' in op.report.call_args.args[1]
        ctx.window.cursor_set.assert_called_once_with('DEFAULT')
        ctx.scene.frame_set.assert_not_called()
        log.flush.assert_called_once()
    finally:
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
