# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The one list of code-execution routes the agent sandbox refuses.

Every entry below runs Python (or a native binary) OUTSIDE the sandbox: with
the real builtins, from a file on disk, or through the OS shell. Each was
checked against Blender 5.2's own implementation, not guessed from its name.
The same sets are enforced in two places so neither is a single point of
failure:

- ``sandbox_validator.py`` rejects the script before it runs (attribute
  names, ``bpy.ops.<ns>.<op>`` chains, ``from x import <name>``);
- ``sandbox_builtins.py`` (the wrapped ``getattr``/``hasattr``/``setattr``)
  and ``sandbox_bpy.py`` (the ``bpy.ops`` / ``bpy.types`` / ``bpy.context``
  proxies) refuse the same names at runtime, so ``getattr(t, "as_" +
  "module")`` and ``getattr(bpy.ops, "scr" + "ipt")`` are caught too.

``tests/test_sandbox_exec_routes.py`` pins the complete set: a new route has
to be added here on purpose and shows up as a test diff.
"""

# Attribute names that are refused on ANY object. The names are specific
# enough that no ordinary agent script uses them.
DENIED_ATTR_NAMES = frozenset({
    # Text datablocks. as_module() exec()s the text with the REAL builtins
    # (_bpy_types.Text.as_module); use_module registers the text to run on
    # the next file load / script reload.
    "as_module",
    "use_module",
    # bpy.utils loaders: each exec()s a .py file from disk (keyconfig_set and
    # keyconfig_init go through execfile), and restricted_open lets a script
    # write that file into the temp directory first.
    "execfile",
    "keyconfig_set",
    "keyconfig_init",
    "load_scripts",
    "load_scripts_extensions",
    "modules_from_path",
    "register_submodule_factory",
    # Operator names that run Python from a file or a Text (also refused by
    # namespace in the bpy.ops proxy below).
    "python_file_run",
    "run_script",
    "execute_preset",
    "addon_install",
    "addon_enable",
    # Macro.define(idname) adds ANY operator, denied ones included, as a step
    # of a Macro the script registers itself, sidestepping the ops proxy.
    "define",
    # Python-registered operators are plain classes: their execute()/invoke()
    # run with the REAL builtins on whatever `self` they are given, and
    # several exec()/eval() their own properties (wm.context_*, wm.properties_
    # edit_value, node.add_node's settings, script.execute_preset's filepath).
    # The bpy.types proxy refuses the classes (sandbox_bpy.py); these are the
    # remaining handles on them:
    # - bl_rna_get_subclass_py(idname) returns the registered class;
    # - Context.active_operator / SpaceFileBrowser.active_operator and
    #   WindowManager.operators hold INSTANCES, whose properties a script can
    #   set before calling the method (bpy.ops.<op>(undo=True) registers one);
    # - bpy_struct.path_resolve("operators") reaches any property by string,
    #   past every attribute denial above (script_directories included).
    "bl_rna_get_subclass_py",
    "active_operator",
    "operators",
    "path_resolve",
    # Preferences that turn on code execution or name an executable that an
    # operator later launches (image.external_edit, text editor jump,
    # render.play_rendered_anim) or add a startup-scripts directory.
    "use_scripts_auto_execute",
    "script_directories",
    "image_editor",
    "text_editor",
    "text_editor_args",
    "animation_player",
    # numpy: ndarray.tofile writes anywhere on disk; ndarray.ctypes._ctypes
    # is the real ctypes module (a native-code escape through a plain object
    # attribute, which the module proxy cannot see).
    "tofile",
    "ctypes",
    "_ctypes",
})

# Whole operator namespaces refused through bpy.ops. Namespaces match in ANY
# case: Blender uppercases the namespace into the operator idname (bpy/ops.py
# ``BPyOpsSubModOp.idname`` is ``module.upper() + "_OT_" + func``, and
# ``WM_operator_bl_idname`` does the same for a call), so ``bpy.ops.SCRIPT.
# python_file_run`` and ``bpy.ops.Script.python_file_run`` both run
# ``SCRIPT_OT_python_file_run``. The operator NAME is copied as typed, so it
# needs no folding. Every check goes through the helpers below.
DENIED_OPS_NAMESPACES = frozenset({
    "script",       # python_file_run, reload, execute_preset: files with real builtins
    "text",         # run_script execs a Text; jump_to_file_at_point launches an editor
    "console",      # console.execute runs a line in the real interactive namespace
    "preferences",  # addon_install / addon_enable / keyconfig_import / app_template_install
    "extensions",   # extension package install / enable
})

# Single operators refused through bpy.ops ("namespace.name").
DENIED_OPS = frozenset({
    # Loading a file with use_scripts=True turns on auto-exec, so the loaded
    # file's registered Texts and Python driver expressions run unrestricted.
    "wm.open_mainfile",
    "wm.revert_mainfile",
    "wm.recover_last_session",
    "wm.recover_auto_save",
    # Hand a path or URL to the OS, which may execute it (.command/.bat/.app).
    "wm.path_open",
    "wm.url_open",
    "wm.url_open_preset",
    "file.external_operation",
})

# Operator name prefixes refused through bpy.ops. Every wm.context_* and
# wm.properties_* operator exec()s/eval()s its data_path / value strings with
# the real builtins (bl_operators/wm.py).
DENIED_OPS_PREFIXES = ("wm.context_", "wm.properties_")

# Keyword arguments refused on every operator of a namespace. The node add /
# swap operators eval() each ``settings`` value (bl_operators/node.py,
# NodeOperator.apply_node_settings).
DENIED_OPS_KWARGS = {
    "node": frozenset({"settings"}),
}

# Classes that ``bpy.types`` may hand out. An RNA struct defined in C is built
# by bpy_rna.cc with ``__module__ == "bpy.types"``; the Python wrappers Blender
# ships for a few of them (Operator, Macro, Panel, Text, Object, ...) live in
# ``bpy_types``. Every OTHER class on ``bpy.types`` was registered from Python
# (bl_operators, bl_ui, add-ons, Mixar) and is the class object itself, so its
# methods are ordinary functions with the real builtins that run on whatever
# ``self`` a script passes. Operator structs carry ``_OT_`` in their RNA
# identifier whether they are C or Python, so the spelled-out form is also
# refused statically by the AST validator.
NATIVE_TYPE_MODULES = frozenset({"bpy.types", "bpy_types"})
OPERATOR_IDNAME_MARK = "_OT_"


def types_denial_reason(name: str, value=None):
    """Why ``bpy.types.<name>`` is refused, or None when allowed.

    ``value`` is the resolved attribute when the caller has it (runtime); the
    name-only check is what the AST validator can apply before the script runs.
    """
    if OPERATOR_IDNAME_MARK in name:
        return (
            f"bpy.types.{name} is not available in the sandbox: operator classes "
            f"run their methods outside it"
        )
    if isinstance(value, type) and getattr(value, "__module__", None) not in NATIVE_TYPE_MODULES:
        return (
            f"bpy.types.{name} is not available in the sandbox: a Python-registered "
            f"class runs its methods outside it"
        )
    return None


def ops_namespace_key(namespace: str) -> str:
    """The denylist spelling of a ``bpy.ops`` namespace: lowercase, which is
    how Blender resolves it (see ``DENIED_OPS_NAMESPACES``)."""
    return namespace.lower()


def is_denied_ops_namespace(namespace: str) -> bool:
    """True when the whole ``bpy.ops.<namespace>`` is refused, in any case."""
    return ops_namespace_key(namespace) in DENIED_OPS_NAMESPACES


def denied_ops_kwargs(namespace: str) -> frozenset:
    """Keyword arguments refused on every operator of ``bpy.ops.<namespace>``."""
    return DENIED_OPS_KWARGS.get(ops_namespace_key(namespace), frozenset())


def op_denial_reason(namespace: str, name: str):
    """Why ``bpy.ops.<namespace>.<name>`` is refused, or None when allowed.

    The namespace matches in any case; the reported route is the canonical
    lowercase spelling.
    """
    namespace = ops_namespace_key(namespace)
    if namespace in DENIED_OPS_NAMESPACES:
        return f"bpy.ops.{namespace} is not available in the sandbox: it runs Python outside it"
    idname = f"{namespace}.{name}"
    if idname in DENIED_OPS or idname.startswith(DENIED_OPS_PREFIXES):
        return f"bpy.ops.{idname} is not available in the sandbox: it runs code outside it"
    return None


def attr_denial_reason(name) -> str:
    """The error text for a denied attribute name (callers check membership)."""
    return (
        f"'{name}' is blocked (sandbox restriction): it runs code outside "
        f"the sandbox"
    )
