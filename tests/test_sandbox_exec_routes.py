# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Every code-execution route out of the agent sandbox stays refused.

The denied set lives in ``space_mixie_chat/core/sandbox_denylist.py`` and is
enforced twice: by the AST validator before a script runs, and at runtime by
the wrapped getattr/hasattr/setattr and the ``bpy.ops`` / driver-namespace
proxies. ``test_the_denied_set_is_pinned`` pins it in full, so adding or
removing a route is a deliberate, reviewed diff. The escape tests run each
route through the real ``ScriptExecutor`` (real numpy, stubbed bpy).
"""

import builtins
import importlib.util
from pathlib import Path
import sys
import types
from types import ModuleType
from unittest.mock import MagicMock

import pytest

_SRC_ROOT = Path(__file__).parents[1] / "src" / "scripts"
_MIXAR_ROOT = _SRC_ROOT / "mixar"
_MODULES_ROOT = _MIXAR_ROOT / "modules"
_CHAT_ROOT = _MODULES_ROOT / "space_mixie_chat"
_CORE_ROOT = _CHAT_ROOT / "core"


def _load(monkeypatch, leaf):
    packages = (
        ("mixar", _MIXAR_ROOT),
        ("mixar.modules", _MODULES_ROOT),
        ("mixar.modules.space_mixie_chat", _CHAT_ROOT),
        ("mixar.modules.space_mixie_chat.core", _CORE_ROOT),
    )
    for name, path in packages:
        package = ModuleType(name)
        package.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, package)
    module_name = f"mixar.modules.space_mixie_chat.core.{leaf}"
    spec = importlib.util.spec_from_file_location(module_name, _CORE_ROOT / f"{leaf}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def denylist(monkeypatch):
    return _load(monkeypatch, "sandbox_denylist")


class _NativeMesh:
    """An RNA struct built by bpy_rna.cc (``__module__`` is ``bpy.types``)."""
    __module__ = "bpy.types"


class _NativeScene:
    __module__ = "bpy.types"


class _PyOperator:
    """Stands for ``bl_operators.wm.WM_OT_context_set_value``: the registered
    class itself, whose ``execute`` exec()s its own properties with the real
    builtins. Reaching it from a script is the escape; the body is a tame
    stand-in for Blender's."""
    __module__ = "bl_operators.wm"
    bl_idname = "wm.context_set_value"

    def execute(self, context):
        # Mirrors Blender's `exec("context.%s = %s" % (self.data_path, self.value))`.
        exec(f"context.{self.data_path} = {self.value}", {"context": context})  # noqa: S102 - test double
        return {"FINISHED"}


class _OperatorBase:
    """``bpy.types.Operator`` (shipped in ``bpy_types``)."""
    __module__ = "bpy_types"

    @classmethod
    def bl_rna_get_subclass_py(cls, idname, default=None):
        return _PyOperator if idname == "WM_OT_context_set_value" else default


class _MacroBase:
    __module__ = "bpy_types"


class _MixarPanel:
    """A first-party class registered from Python."""
    __module__ = "mixar.modules.paint.ui.panels.layers"

    def draw(self, context):
        return "drawn"


@pytest.fixture
def executor(monkeypatch):
    for module_name in ("bmesh", "mathutils", "bpy_extras", "imbuf"):
        monkeypatch.setitem(sys.modules, module_name, MagicMock(name=module_name))
    module = _load(monkeypatch, "executor")
    # bpy.types as the real module hands it out: C structs, Blender's own
    # Python wrappers, and Python-registered classes (a stock operator and a
    # Mixar panel). A plain namespace, not a ModuleType: the mocked bpy has no
    # package name, so safe_module would refuse any module attribute on it.
    monkeypatch.setattr(
        module.bpy,
        "types",
        types.SimpleNamespace(
            Mesh=_NativeMesh,
            Scene=_NativeScene,
            Operator=_OperatorBase,
            Macro=_MacroBase,
            WM_OT_context_set_value=_PyOperator,
            MIXAR_PT_layers=_MixarPanel,
        ),
        raising=False,
    )
    # bpy.context.copy() carries the screen-context members, active_operator
    # (the last registered operator INSTANCE) among them.
    registered_operator = _PyOperator()
    registered_operator.data_path = "scene"
    registered_operator.value = "1"
    module.bpy.context.active_operator = registered_operator
    module.bpy.context.copy = lambda: {
        "scene": module.bpy.context.scene,
        "window_manager": module.bpy.context.window_manager,
        "active_operator": registered_operator,
    }
    # The real driver namespace holds the real builtins and the real bpy
    # (bpy_driver.cc); the Mixar operators leave render receipts beside them.
    monkeypatch.setattr(
        module.bpy.app,
        "driver_namespace",
        {
            "__builtins__": builtins.__dict__,
            "bpy": ModuleType("bpy"),
            "noise": ModuleType("mathutils.noise"),
            "mixie_scene_render": {"job-1": {"status": "done"}},
        },
        raising=False,
    )
    return module.ScriptExecutor()


def _run(executor, script):
    return executor.execute(script, push_undo=False)


def test_the_denied_set_is_pinned(denylist):
    assert denylist.DENIED_ATTR_NAMES == frozenset({
        "as_module", "use_module",
        "execfile", "keyconfig_set", "keyconfig_init", "load_scripts",
        "load_scripts_extensions", "modules_from_path", "register_submodule_factory",
        "python_file_run", "run_script", "execute_preset", "addon_install", "addon_enable",
        "define",
        "use_scripts_auto_execute", "script_directories", "image_editor",
        "text_editor", "text_editor_args", "animation_player",
        "tofile", "ctypes", "_ctypes",
        "bl_rna_get_subclass_py", "active_operator", "operators", "path_resolve",
    })
    assert denylist.NATIVE_TYPE_MODULES == frozenset({"bpy.types", "bpy_types"})
    assert denylist.OPERATOR_IDNAME_MARK == "_OT_"
    assert denylist.DENIED_OPS_NAMESPACES == frozenset({
        "script", "text", "console", "preferences", "extensions",
    })
    assert denylist.DENIED_OPS == frozenset({
        "wm.open_mainfile", "wm.revert_mainfile", "wm.recover_last_session",
        "wm.recover_auto_save", "wm.path_open", "wm.url_open", "wm.url_open_preset",
        "file.external_operation",
    })
    assert denylist.DENIED_OPS_PREFIXES == ("wm.context_", "wm.properties_")
    assert denylist.DENIED_OPS_KWARGS == {"node": frozenset({"settings"})}


def test_the_numpy_identity_list_is_pinned(monkeypatch):
    for module_name in ("bmesh", "mathutils", "bpy_extras", "imbuf"):
        monkeypatch.setitem(sys.modules, module_name, MagicMock(name=module_name))
    modules = _load(monkeypatch, "sandbox_modules")
    assert modules._NUMPY_DENIED_PATHS == (
        "load", "save", "savez", "savez_compressed", "savetxt", "loadtxt",
        "genfromtxt", "fromfile", "fromregex", "memmap",
        "lib.npyio.DataSource", "lib.format.open_memmap", "lib.format.read_array",
        "lib.format.write_array", "rec.fromfile",
    )
    for denied in (
        "numpy.lib.format", "numpy.lib.npyio", "numpy.lib._npyio_impl",
        "numpy.lib._datasource", "numpy.lib._format_impl",
        "mixar.modules.addon_project",
    ):
        assert modules.is_denied_module(denied)
        assert modules.is_denied_module(denied + ".child")
    assert not modules.is_denied_module("numpy.linalg")
    assert not modules.is_denied_module("mixar.modules.addon_projects")


ESCAPES = {
    # Text datablocks
    "text_as_module": "t = bpy.data.texts.new('t')\nt.as_module()",
    "text_as_module_computed": "t = bpy.data.texts.new('t')\ngetattr(t, 'as_' + 'module')()",
    "text_use_module": "bpy.data.texts['t'].use_module = True",
    "text_use_module_computed": "setattr(bpy.data.texts['t'], 'use_' + 'module', True)",
    # bpy.ops routes
    "script_run_file": "bpy.ops.script.python_file_run(filepath='/tmp/x.py')",
    "script_computed": "getattr(bpy.ops, 'scr' + 'ipt').reload()",
    "script_aliased": "o = bpy.ops\no.script.execute_preset(filepath='/tmp/x.py')",
    "text_run_script": "bpy.ops.text.run_script()",
    "text_computed": "getattr(getattr(bpy.ops, 'te' + 'xt'), 'run_' + 'script')()",
    "console_execute": "bpy.ops.console.execute()",
    "addon_install": "bpy.ops.preferences.addon_install(filepath='/tmp/x.zip')",
    "addon_enable_computed": "getattr(bpy.ops, 'prefer' + 'ences')",
    "extension_install": "bpy.ops.extensions.package_install_files(filepath='/tmp/x.zip')",
    "wm_context_exec": "bpy.ops.wm.context_set_value(data_path='scene', value='1')",
    "wm_context_computed": "getattr(bpy.ops.wm, 'context_' + 'toggle')(data_path='x')",
    "wm_properties_eval": "bpy.ops.wm.properties_edit(data_path='x')",
    "open_with_autoexec": "bpy.ops.wm.open_mainfile(filepath='/tmp/x.blend', use_scripts=True)",
    "revert_with_autoexec": "bpy.ops.wm.revert_mainfile(use_scripts=True)",
    "recover_with_autoexec": "getattr(bpy.ops.wm, 'recover_' + 'auto_save')()",
    "os_path_open": "bpy.ops.wm.path_open(filepath='/tmp/x.command')",
    "os_url_open": "bpy.ops.wm.url_open(url='file:///tmp/x.command')",
    "win_external_operation": "bpy.ops.file.external_operation(filepath='/tmp/x.bat')",
    "node_settings_eval": "bpy.ops.node.add_node(type='ShaderNodeMath', settings=[{'name': 'x', 'value': '1'}])",
    "node_settings_computed": "op = bpy.ops.node.add_node\nop(type='X', **{'sett' + 'ings': []})",
    "ops_private_factory": "bpy.ops._op_create_function('script', 'python_file_run')",
    "ops_private_submodule": "getattr(bpy.ops, '_bpy_ops_' + 'submodule')('script')",
    "macro_define": "M = type('M', (object,), {})\nM.define('SCRIPT_OT_python_file_run')",
    "macro_define_computed": "getattr(bpy.types.Macro, 'def' + 'ine')('SCRIPT_OT_python_file_run')",
    # bpy.types: Python-registered operator classes exec() their properties
    # with the real builtins on any `self` they are handed
    "types_py_operator_class": "F = type('F', (), {'data_path': 'scene', 'value': '1'})\nbpy.types.WM_OT_context_set_value.execute(F(), bpy.context)",
    "types_py_operator_computed": "F = type('F', (), {'data_path': 'scene', 'value': '1'})\ngetattr(bpy.types, 'WM_OT_' + 'context_set_value').execute(F(), bpy.context)",
    "types_py_operator_aliased": "T = bpy.types\nF = type('F', (), {'data_path': 'scene', 'value': '1'})\nT.WM_OT_context_set_value.execute(F(), bpy.context)",
    "types_registered_class": "bpy.types.MIXAR_PT_layers.draw(None, bpy.context)",
    "types_registered_class_computed": "getattr(bpy.types, 'MIXAR_PT_' + 'layers').draw(None, bpy.context)",
    "types_subclass_lookup": "bpy.types.Operator.bl_rna_get_subclass_py('WM_OT_context_set_value')",
    "types_subclass_lookup_computed": "getattr(bpy.types.Operator, 'bl_rna_get_' + 'subclass_py')('WM_OT_context_set_value')",
    # registered operator INSTANCES: writable properties + the same methods
    "context_active_operator": "op = bpy.context.active_operator\nop.value = '1'\nop.execute(bpy.context)",
    "context_active_operator_computed": "getattr(bpy.context, 'active_' + 'operator').execute(bpy.context)",
    "context_copy_active_operator": "bpy.context.copy()['active_operator'].execute(bpy.context)",
    "wm_operators": "bpy.context.window_manager.operators[-1].execute(bpy.context)",
    "wm_operators_computed": "getattr(bpy.data.window_managers[0], 'opera' + 'tors')",
    "path_resolve_operators": "bpy.context.window_manager.path_resolve('operators')",
    "path_resolve_computed": "getattr(bpy.context.preferences, 'path_' + 'resolve')('filepaths.script_directories')",
    # bpy.utils loaders
    "utils_execfile": "bpy.utils.execfile('/tmp/x.py')",
    "utils_execfile_computed": "getattr(bpy.utils, 'exec' + 'file')('/tmp/x.py')",
    "utils_keyconfig_set": "bpy.utils.keyconfig_set('/tmp/x.py')",
    "utils_import_from": "from bpy.utils import execfile",
    # preferences that enable execution
    "pref_autoexec": "bpy.context.preferences.filepaths.use_scripts_auto_execute = True",
    "pref_image_editor": "setattr(bpy.context.preferences.filepaths, 'image_' + 'editor', '/bin/sh')",
    "pref_script_dirs": "bpy.context.preferences.filepaths.script_directories.new()",
    # driver namespace: real builtins + real bpy behind a string subscript
    "driver_builtins": "bpy.app.driver_namespace['__builtins__']['exec']('1')",
    "driver_real_bpy": "bpy.app.driver_namespace['bpy'].utils",
    "driver_noise_module": "bpy.app.driver_namespace['noise']",
    "driver_overwrite": "bpy.app.driver_namespace['__builtins__'] = {}",
    # str subclass that lies to the membership test
    "str_subclass_name": "S = type('S', (str,), {'__hash__': lambda s: 1, '__eq__': lambda s, o: False})\ngetattr(bpy.data.texts.new('t'), S('as_module'))",
    # numpy file / pickle IO
    "numpy_load_pickle": "numpy.load('/tmp/x.npy', allow_pickle=True)",
    "numpy_load_import": "import numpy as np\nnp.load('/tmp/x.npy', allow_pickle=True)",
    "numpy_save": "numpy.save('/tmp/x', numpy.zeros(1))",
    "numpy_savez": "numpy.savez('/tmp/x', a=numpy.zeros(1))",
    "numpy_savetxt": "numpy.savetxt('/tmp/x', numpy.zeros(1))",
    "numpy_loadtxt": "numpy.loadtxt('/etc/hosts')",
    "numpy_genfromtxt": "numpy.genfromtxt('https://example.com/x')",
    "numpy_fromfile": "numpy.fromfile('/etc/hosts', dtype='u1')",
    "numpy_fromregex": "numpy.fromregex('/etc/hosts', '(.)', [('a', 'U1')])",
    "numpy_memmap": "numpy.memmap('/tmp/x', mode='w+', shape=(1,))",
    "numpy_rec_fromfile": "numpy.rec.fromfile('/etc/hosts', formats='u1')",
    "numpy_private_alias": "numpy._core.multiarray.fromfile('/etc/hosts')",
    "numpy_npyio_module": "numpy.lib.npyio.load('/tmp/x.npy', allow_pickle=True)",
    "numpy_npyio_from": "from numpy.lib.npyio import load",
    "numpy_npyio_impl_from": "from numpy.lib._npyio_impl import load",
    "numpy_format": "numpy.lib.format.open_memmap('/tmp/x', mode='w+')",
    "numpy_datasource": "from numpy.lib._datasource import DataSource",
    "numpy_tester": "numpy.test()",
    "numpy_ctypeslib_leaf": "from numpy.ctypeslib import load_library",
    "numpy_tofile": "numpy.zeros(3).tofile('/tmp/x')",
    "numpy_tofile_computed": "getattr(numpy.zeros(3), 'to' + 'file')('/tmp/x')",
    "numpy_ctypes_module": "numpy.zeros(1).ctypes._ctypes.CDLL(None)",
    "numpy_ctypes_computed": "getattr(getattr(numpy.zeros(1), 'cty' + 'pes'), '_cty' + 'pes')",
    # operator namespace spelled in another case: Blender uppercases it into
    # the idname, so bpy.ops.SCRIPT is bpy.ops.script
    "ops_namespace_uppercase": "bpy.ops.SCRIPT.python_file_run(filepath='/tmp/x.py')",
    "ops_namespace_uppercase_computed": "getattr(bpy.ops, 'SCR' + 'IPT').python_file_run(filepath='/tmp/x.py')",
    "ops_mixedcase_denied_operator": "bpy.ops.Wm.open_mainfile(filepath='/tmp/x.blend', use_scripts=True)",
    "ops_mixedcase_denied_prefix": "bpy.ops.WM.context_set_value(data_path='x', value='1')",
    "ops_mixedcase_denied_kwarg": "bpy.ops.NODE.add_node(settings=[{'name': 'x', 'value': '1'}])",
    # the add-on workspace (writes, installs and enables add-ons)
    "addon_project_import": "import mixar.modules.addon_project.service",
    "addon_project_from": "from mixar.modules.addon_project.installer import set_addon_enabled",
}


@pytest.mark.parametrize("name", sorted(ESCAPES))
def test_every_escape_is_refused(executor, name):
    result = _run(executor, ESCAPES[name])
    assert result.success is False, name
    # Refused BY the sandbox, not failing for some incidental reason.
    assert "sandbox" in (result.error or ""), (name, result.error)


def test_refusals_are_silent_where_a_probe_expects_absence(executor):
    result = _run(executor, "\n".join((
        "t = bpy.data.texts.new('t')",
        "ns = bpy.app.driver_namespace",
        "__RESULT__ = {",
        "    'hasattr_as_module': hasattr(t, 'as_module'),",
        "    'hasattr_tofile': hasattr(numpy.zeros(1), 'to' + 'file'),",
        "    'get_builtins': ns.get('__builtins__'),",
        "    'get_bpy': ns.get('bpy', 'absent'),",
        "    'dict_values': [type(v).__name__ for v in ns.values()],",
        "    'items': [k for k, _ in ns.items()],",
        "}",
    )))
    assert result.success, result.error
    assert result.return_value == {
        "hasattr_as_module": False,
        "hasattr_tofile": False,
        "get_builtins": None,
        "get_bpy": "absent",
        "dict_values": ["dict"],
        "items": ["mixie_scene_render"],
    }


def test_ast_rejections_name_the_route(monkeypatch):
    validator = _load(monkeypatch, "sandbox_validator")
    msg = validator.validate_script_ast("t.as_module()")
    assert "'as_module' is blocked" in msg
    msg = validator.validate_script_ast("bpy.ops.script.python_file_run()")
    assert "bpy.ops.script is not available" in msg
    msg = validator.validate_script_ast("bpy.ops.SCRIPT.python_file_run()")
    assert "bpy.ops.script is not available" in msg
    msg = validator.validate_script_ast("bpy.ops.Wm.open_mainfile(use_scripts=True)")
    assert "bpy.ops.wm.open_mainfile is not available" in msg
    msg = validator.validate_script_ast("bpy.ops.NODE.add_node(settings=[])")
    assert "settings=...) is blocked" in msg
    msg = validator.validate_script_ast("bpy.ops.wm.context_toggle(data_path='x')")
    assert "bpy.ops.wm.context_toggle is not available" in msg
    msg = validator.validate_script_ast("bpy.ops.node.add_node(settings=[])")
    assert "settings=...) is blocked" in msg
    msg = validator.validate_script_ast("from bpy.utils import execfile")
    assert "importing 'execfile' is blocked" in msg
    msg = validator.validate_script_ast("bpy.types.WM_OT_context_set_value.execute(None, None)")
    assert "bpy.types.WM_OT_context_set_value is not available" in msg
    msg = validator.validate_script_ast("bpy.context.active_operator.execute(None)")
    assert "'active_operator' is blocked" in msg
    # Ordinary scripts are untouched.
    assert validator.validate_script_ast(
        "import json\njson.dump({}, open('/tmp/x.json', 'w'))\n"
        "bpy.ops.wm.obj_export(filepath='/tmp/x.obj')\n"
        "bpy.ops.node.add_node(type='ShaderNodeMath')\n"
        "bpy.ops.MESH.primitive_cube_add(size=2)\n"
        "isinstance(bpy.context.object.data, bpy.types.Mesh)\n"
        "bpy.types.Scene.my_prop = bpy.props.IntProperty()\n"
    ) is None


def test_native_types_and_context_still_forward(executor):
    result = _run(executor, "\n".join((
        "bpy.types.Scene.mixar_probe = 7",
        "ctx = bpy.context.copy()",
        "__RESULT__ = {",
        "    'mesh_is_class': isinstance(bpy.types.Mesh, type),",
        "    'scene_prop': bpy.types.Scene.mixar_probe,",
        "    'operator_base': bpy.types.Operator.__name__,",
        "    'scene_forwarded': ctx['scene'] is bpy.context.scene,",
        "    'copy_keys': sorted(ctx),",
        "    'copy_get_absent': ctx.get('active_operator', 'absent'),",
        "    'temp_override': callable(bpy.context.temp_override),",
        "    'dir_has_mesh': 'Mesh' in dir(bpy.types),",
        "    'dir_hides_operator': 'WM_OT_context_set_value' in dir(bpy.types),",
        "    'dir_hides_registered': 'MIXAR_PT_layers' in dir(bpy.types),",
        "    'dir_hides_active_operator': 'active_operator' in dir(bpy.context),",
        "}",
    )))
    assert result.success, result.error
    assert result.return_value == {
        "mesh_is_class": True,
        "scene_prop": 7,
        "operator_base": "_OperatorBase",
        "scene_forwarded": True,
        "copy_keys": ["scene", "window_manager"],
        "copy_get_absent": "absent",
        "temp_override": True,
        "dir_has_mesh": True,
        "dir_hides_operator": False,
        "dir_hides_registered": False,
        "dir_hides_active_operator": False,
    }


def test_numpy_math_still_works(executor):
    result = _run(executor, "\n".join((
        "import numpy as np",
        "from numpy.linalg import norm",
        "a = np.arange(6, dtype=float).reshape(2, 3)",
        "__RESULT__ = {",
        "    'norm': round(float(norm(a)), 6),",
        "    'sum': float(a.sum()),",
        "    'dot': np.dot(a, a.T).tolist(),",
        "    'mean': float(numpy.mean(a)),",
        "    'buf': len(a.tobytes()),",
        "    'json_dump': callable(json.dump),",
        "}",
    )))
    assert result.success, result.error
    assert result.return_value == {
        "norm": round(float((sum(x * x for x in range(6))) ** 0.5), 6),
        "sum": 15.0,
        "dot": [[5.0, 14.0], [14.0, 50.0]],
        "mean": 2.5,
        "buf": 48,
        "json_dump": True,
    }


def test_driver_namespace_mailbox_still_works(executor):
    result = _run(executor, "\n".join((
        "ns = bpy.app.driver_namespace",
        "res = (ns.get('mixie_scene_render') or {}).pop('job-1', None)",
        "ns.setdefault('mixar_scene_render_response', {'ok': 1})",
        "resp = ns.pop('mixar_scene_render_response', None)",
        "ns['mixie_agent_preview_response'] = {'status': 'running'}",
        "__RESULT__ = {",
        "    'res': res, 'resp': resp,",
        "    'keys': sorted(ns.keys()),",
        "    'has_builtins': '__builtins__' in ns,",
        "    'has_bpy': 'bpy' in ns,",
        "    'missing': ns.get('__builtins__', 'none'),",
        "}",
    )))
    assert result.success, result.error
    assert result.return_value == {
        "res": {"status": "done"},
        "resp": {"ok": 1},
        "keys": ["mixie_agent_preview_response", "mixie_scene_render"],
        "has_builtins": False,
        "has_bpy": False,
        "missing": "none",
    }


def test_allowed_operators_still_forward(executor):
    result = _run(executor, "\n".join((
        "bpy.ops.wm.obj_export(filepath='/tmp/x.obj')",
        "bpy.ops.node.add_node(type='ShaderNodeMath')",
        "bpy.ops.mesh.primitive_cube_add()",
        "__RESULT__ = {'ok': hasattr(bpy.ops, 'object')}",
    )))
    assert result.success, result.error
    assert result.return_value == {"ok": True}


def test_material_registry_uses_the_same_guarded_bpy():
    source = (_MODULES_ROOT / "paint/procedural_materials/material_registry.py").read_text()
    assert "make_sandboxed_bpy(safe_module(bpy))" in source
    executor_source = (_CORE_ROOT / "executor.py").read_text()
    assert '"bpy": make_sandboxed_bpy(safe_module(bpy))' in executor_source
    assert "make_restricted_import(" in executor_source
