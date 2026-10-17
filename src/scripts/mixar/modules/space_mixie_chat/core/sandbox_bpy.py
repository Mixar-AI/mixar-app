# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Sandboxed bpy surface for script execution.

SCRIPT_OT_python_file_run (stock Blender's ``bpy.ops.script.python_file_run``,
also registered by the Mixar fork) executes an arbitrary .py file with REAL
builtins — a single call bypasses every sandbox layer below it (restricted
builtins, restricted __import__, AST validation, restricted_open). It is one
of a family: the operators and namespaces listed in ``sandbox_denylist.py``
all run code outside the sandbox. The sandbox therefore never hands out the
real bpy.ops object: scripts get a forwarding proxy that refuses them.

Three more holes are closed here:

- ``bpy.ops._op_create_function`` / ``bpy.ops._bpy_ops_submodule`` build an
  operator callable from a name, walking straight past a namespace check, so
  the ops proxy refuses every ``_``-prefixed name. A namespace is matched in
  any case (``bpy.ops.SCRIPT`` is ``bpy.ops.script`` to Blender, which
  uppercases it into the idname).
- ``bpy.types`` hands out Python-registered operator CLASSES
  (``bpy.types.WM_OT_context_set_value`` is the ``bl_operators.wm`` class
  itself), whose ``execute`` is a plain function with the real builtins that
  a script can call with a ``type()``-made ``self`` carrying any
  ``data_path`` / ``value`` -- the ops denial never runs. The types proxy
  refuses operator structs and every class not defined by Blender's own
  ``bpy.types`` / ``bpy_types``; ``bpy.context.copy()`` drops the denied
  ``active_operator`` member (an operator INSTANCE with writable properties).
- ``bpy.app.driver_namespace`` holds the REAL ``__builtins__`` dict and the
  real, unwrapped ``bpy`` module (``bpy_driver.cc``), reachable with a plain
  string subscript that neither the AST guard nor the wrapped getattr sees.
  The Mixar operators still use it as a result mailbox (render receipts), so
  scripts get a guarded view: dunder keys and module values are refused.

Legit operator access (mesh.*, object.*, ed.*, wm.obj_export, ...), the RNA
structs (``bpy.types.Mesh``, ``bpy.types.Scene.prop = ...``, ``isinstance``)
and the rest of bpy are forwarded untouched.
"""

import types

from .sandbox_denylist import (
    DENIED_ATTR_NAMES,
    denied_ops_kwargs,
    is_denied_ops_namespace,
    op_denial_reason,
    types_denial_reason,
)


def _guard_op(op, namespace, name, denied_kwargs):
    """Wrap an operator callable so the denied keyword arguments are refused."""

    class _GuardedOp:
        __slots__ = ()

        def __call__(self, *args, **kwargs):
            for key in kwargs:
                if key in denied_kwargs:
                    raise PermissionError(
                        f"bpy.ops.{namespace}.{name}({key}=...) is not "
                        f"available in the sandbox: the operator eval()s it"
                    )
            return op(*args, **kwargs)

        def __getattr__(self, attr):
            if attr.startswith("__"):
                raise AttributeError(attr)
            return getattr(op, attr)

        def __repr__(self):
            return repr(op)

    return _GuardedOp()


def _sandboxed_ops_namespace(real_ns, namespace):
    denied_kwargs = denied_ops_kwargs(namespace)

    class _SandboxedOpsNamespace:
        __slots__ = ()

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(
                    f"bpy.ops.{namespace}.{name} is not available in the sandbox"
                )
            reason = op_denial_reason(namespace, name)
            if reason:
                raise PermissionError(reason)
            op = getattr(real_ns, name)
            if denied_kwargs:
                return _guard_op(op, namespace, name, denied_kwargs)
            return op

        def __dir__(self):
            return [
                n for n in dir(real_ns)
                if not n.startswith("_") and op_denial_reason(namespace, n) is None
            ]

        def __repr__(self):
            return f"<sandboxed bpy.ops.{namespace}>"

    return _SandboxedOpsNamespace()


def _is_denied_driver_key(key):
    return isinstance(key, str) and key.startswith("__")


def _sandboxed_driver_namespace(real_bpy):
    """A dict-like view of ``bpy.app.driver_namespace`` for scripts."""

    def _ns():
        # Fetched on every use: the namespace is rebuilt on file load.
        return real_bpy.app.driver_namespace

    def _check_key(key):
        if _is_denied_driver_key(key):
            raise KeyError(
                f"driver_namespace[{key!r}] is not available in the sandbox"
            )

    def _check_value(key, value):
        if isinstance(value, types.ModuleType):
            raise KeyError(
                f"driver_namespace[{key!r}] is a module and is not available "
                f"in the sandbox"
            )
        return value

    def _visible():
        return [
            k for k, v in list(_ns().items())
            if not _is_denied_driver_key(k) and not isinstance(v, types.ModuleType)
        ]

    _missing = object()

    class _SandboxedDriverNamespace:
        __slots__ = ()

        def __getitem__(self, key):
            _check_key(key)
            return _check_value(key, _ns()[key])

        def __setitem__(self, key, value):
            _check_key(key)
            _check_value(key, _ns().get(key))
            _check_value(key, value)
            _ns()[key] = value

        def __delitem__(self, key):
            _check_key(key)
            _check_value(key, _ns().get(key))
            del _ns()[key]

        def __contains__(self, key):
            return key in _visible()

        def __iter__(self):
            return iter(_visible())

        def __len__(self):
            return len(_visible())

        def get(self, key, default=None):
            if _is_denied_driver_key(key):
                return default
            value = _ns().get(key, _missing)
            if value is _missing or isinstance(value, types.ModuleType):
                return default
            return value

        def pop(self, key, *default):
            if _is_denied_driver_key(key) or key not in _visible():
                if default:
                    return default[0]
                raise KeyError(key)
            return _ns().pop(key)

        def setdefault(self, key, default=None):
            _check_key(key)
            _check_value(key, default)
            return _check_value(key, _ns().setdefault(key, default))

        def keys(self):
            return list(_visible())

        def values(self):
            ns = _ns()
            return [ns[k] for k in _visible()]

        def items(self):
            ns = _ns()
            return [(k, ns[k]) for k in _visible()]

        def __repr__(self):
            return "<sandboxed driver_namespace>"

    return _SandboxedDriverNamespace()


def _sandboxed_types(real_types):
    """``bpy.types`` minus operator structs and Python-registered classes."""

    class _SandboxedTypes:
        __slots__ = ()

        def __getattr__(self, name):
            # The name check needs no fetch; the class check does.
            reason = types_denial_reason(name)
            if reason:
                raise PermissionError(reason)
            value = getattr(real_types, name)
            reason = types_denial_reason(name, value)
            if reason:
                raise PermissionError(reason)
            return value

        def __dir__(self):
            return [
                n for n in dir(real_types)
                if types_denial_reason(n, getattr(real_types, n, None)) is None
            ]

        def __repr__(self):
            return "<sandboxed bpy.types>"

    return _SandboxedTypes()


def _sandboxed_context(real_bpy):
    """``bpy.context`` whose ``copy()`` omits the denied members.

    ``active_operator`` is refused as an attribute name everywhere, but
    ``bpy.context.copy()`` returns the same member under a string key.
    Everything else -- ``temp_override``, ``scene``, ``evaluated_depsgraph_get``
    -- is the real context's own attribute.
    """

    class _ContextCopy(dict):
        """The copied members; a denied key reads as a sandbox refusal, not as
        a plain absence (``get`` still returns its default)."""

        __slots__ = ()

        def __missing__(self, key):
            if key in DENIED_ATTR_NAMES:
                raise KeyError(f"context.copy()[{key!r}] is not available in the sandbox")
            raise KeyError(key)

    def _copy():
        return _ContextCopy(
            (key, value) for key, value in real_bpy.context.copy().items()
            if key not in DENIED_ATTR_NAMES
        )

    class _SandboxedContext:
        __slots__ = ()

        def __getattr__(self, name):
            if name == "copy":
                return _copy
            return getattr(real_bpy.context, name)

        def __dir__(self):
            return [n for n in dir(real_bpy.context) if n not in DENIED_ATTR_NAMES]

        def __repr__(self):
            return "<sandboxed bpy.context>"

    return _SandboxedContext()


def make_sandboxed_bpy(real_bpy):
    """Return a proxy over ``real_bpy`` with guarded ``ops``, ``types``,
    ``context`` and ``app``.

    The real module and its ops object are captured in the ``__getattr__``
    closures only — no instance or class attribute ever references them, so a
    script cannot reach the real ops through ``bpy._real_bpy``-style attribute
    access. Reaching them through the closure/class machinery (``__closure__``,
    ``__class__``, ``__dict__``) is blocked by the AST validator and the
    wrapped getattr (see sandbox_validator.py / sandbox_builtins.py).
    """
    real_ops = real_bpy.ops
    namespaces = {}

    class _SandboxedOps:
        """Forwards operator namespaces; denies the listed ones."""

        __slots__ = ()

        def __getattr__(self, name):
            if is_denied_ops_namespace(name):
                raise PermissionError(op_denial_reason(name, ""))
            if name.startswith("_"):
                # _op_create_function / _bpy_ops_submodule build any operator
                # from a string, past every check above.
                raise AttributeError(f"bpy.ops.{name} is not available in the sandbox")
            proxy = namespaces.get(name)
            if proxy is None:
                proxy = namespaces[name] = _sandboxed_ops_namespace(
                    getattr(real_ops, name), name
                )
            return proxy

        def __dir__(self):
            return [
                n for n in dir(real_ops)
                if not is_denied_ops_namespace(n) and not n.startswith("_")
            ]

    driver_namespace = _sandboxed_driver_namespace(real_bpy)

    class _SandboxedApp:
        """Forwards bpy.app; swaps driver_namespace for the guarded view."""

        __slots__ = ()

        def __getattr__(self, name):
            if name == "driver_namespace":
                return driver_namespace
            return getattr(real_bpy.app, name)

        def __dir__(self):
            return dir(real_bpy.app)

    class _SandboxedBpy:
        """Forwards attribute access to the real bpy module, swapping the
        guarded children in."""

        __slots__ = ()

        def __getattr__(self, name):
            swapped = guarded.get(name)
            if swapped is not None:
                return swapped
            return getattr(real_bpy, name)

        def __dir__(self):
            return dir(real_bpy)

    guarded = {
        "ops": _SandboxedOps(),
        "app": _SandboxedApp(),
        "types": _sandboxed_types(real_bpy.types),
        "context": _sandboxed_context(real_bpy),
    }
    return _SandboxedBpy()
