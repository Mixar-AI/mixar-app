# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Sandbox builtins for safe script execution.

Provides a restricted builtins dict that excludes dangerous functions
(eval, exec, compile, __import__) and wraps getattr/hasattr to block
runtime dunder access.
"""

import builtins
import json
from typing import Any

from .sandbox_denylist import DENIED_ATTR_NAMES, attr_denial_reason
from .sandbox_validator import _BLOCKED_DUNDER_ATTRS

# Restricted builtins whitelist for safe script execution
# Excludes dangerous functions like: eval, exec, compile, __import__,
# globals, locals, input, breakpoint
# NOTE: `vars` is intentionally EXCLUDED. Unlike getattr, vars(obj) returns the
# raw obj.__dict__ without passing through the dunder guard, so `vars(json)`
# (or any injected module) exposes the real __builtins__ dict -> eval/exec.
# `dir` stays (returns attribute-name strings only, no object handles).
# `type` IS included: `class` statements remain impossible (`__build_class__` is
# absent) and a class object reached via type(x) exposes only `mro()` plus
# dunders the guard already blocks, so it grants no reach that x itself lacks.
# Still excluded: super, __build_class__, input, breakpoint, vars, eval, exec,
# compile, __import__, globals (a filtered snapshot is injected in executor.py).
SAFE_BUILTIN_NAMES = frozenset({
    # Type constructors
    'bool', 'bytearray', 'bytes', 'complex', 'dict', 'float', 'frozenset',
    'int', 'list', 'object', 'set', 'slice', 'str', 'tuple', 'type',
    # Iteration/sequences
    'all', 'any', 'enumerate', 'filter', 'iter', 'len', 'map', 'max',
    'min', 'next', 'range', 'reversed', 'sorted', 'sum', 'zip',
    # Math
    'abs', 'divmod', 'pow', 'round',
    # Attribute access / introspection
    'getattr', 'hasattr', 'setattr', 'isinstance', 'issubclass', 'dir',
    # Output (safe)
    'print', 'repr', 'format', 'ascii', 'bin', 'hex', 'oct', 'chr', 'ord',
    # Other safe functions
    'callable', 'hash', 'id', 'len', 'staticmethod', 'classmethod', 'property',
    # Exceptions -- agent scripts need these to write try/except at all.
    # Without them a script raising or catching anything failed with
    # "name 'ImportError' is not defined" and only learned it after a full
    # model round trip (Langfuse trace 9d8d834c burned ~115s on exactly this,
    # plus "name 'type' is not defined" for `type(x)` checks).
    'Exception', 'ValueError', 'KeyError', 'TypeError', 'IndexError',
    'AttributeError', 'RuntimeError', 'ImportError', 'ZeroDivisionError',
    'StopIteration', 'FileNotFoundError', 'OSError', 'PermissionError',
})


def get_safe_builtins() -> dict:
    """
    Create a restricted builtins dict for safer script execution.

    Returns a dict containing only whitelisted builtin functions.
    __import__ is NOT included -- scripts cannot import arbitrary modules.
    Safe modules are pre-injected into exec_namespace instead.
    """
    safe_builtins = {
        name: getattr(builtins, name)
        for name in SAFE_BUILTIN_NAMES
        if hasattr(builtins, name)
    }
    # Include essential constants
    safe_builtins['True'] = True
    safe_builtins['False'] = False
    safe_builtins['None'] = None
    # Exception classes come from SAFE_BUILTIN_NAMES above (single source of
    # truth) -- the comprehension picks them up like any other builtin.

    # __import__ is intentionally excluded from SAFE_BUILTIN_NAMES.
    # Instead, a restricted __import__ is injected in execute() that only
    # allows importing modules already pre-injected into exec_namespace.

    # Wrap getattr/hasattr to block runtime dunder access via string
    # concatenation (e.g. getattr(obj, '__sub'+'classes__')).
    # This closes the bypass where computed attribute names evade AST checks.
    _original_getattr = builtins.getattr

    # The code-execution names (sandbox_denylist.py) are refused the same way,
    # so getattr(text, "as_" + "module") cannot reach what the AST guard
    # rejects when spelled out. A denied name raises even with a default:
    # a silent default would read as "attribute absent" and hide the refusal.
    def _plain(name):
        # A str SUBCLASS made with type() can lie in __eq__/__hash__, so a
        # membership test would miss it while the real getattr still uses its
        # characters. Only exact str names are accepted.
        if isinstance(name, str) and type(name) is not str:
            raise TypeError("attribute name must be a plain str (sandbox restriction)")
        return name

    def _safe_getattr(obj, name, *default):
        name = _plain(name)
        if isinstance(name, str) and name in _BLOCKED_DUNDER_ATTRS:
            raise AttributeError(
                f"Access to '{name}' is blocked (sandbox restriction)"
            )
        if isinstance(name, str) and name in DENIED_ATTR_NAMES:
            raise AttributeError(attr_denial_reason(name))
        value = _original_getattr(obj, name, *default)
        if name == "from_mesh":
            from .sandbox_mesh import guard_from_mesh
            return guard_from_mesh(value)
        return value

    def _safe_hasattr(obj, name):
        name = _plain(name)
        if isinstance(name, str) and (
            name in _BLOCKED_DUNDER_ATTRS or name in DENIED_ATTR_NAMES
        ):
            return False
        try:
            _original_getattr(obj, name)
            return True
        except AttributeError:
            return False

    def _safe_setattr(obj, name, value):
        name = _plain(name)
        if isinstance(name, str) and name in _BLOCKED_DUNDER_ATTRS:
            raise AttributeError(
                f"Setting '{name}' is blocked (sandbox restriction)"
            )
        if isinstance(name, str) and name in DENIED_ATTR_NAMES:
            raise AttributeError(attr_denial_reason(name))
        return builtins.setattr(obj, name, value)

    safe_builtins['getattr'] = _safe_getattr
    safe_builtins['hasattr'] = _safe_hasattr
    safe_builtins['setattr'] = _safe_setattr

    return safe_builtins


def sanitize_value(value: Any) -> Any:
    """
    Recursively sanitize value for JSON serialization.

    Converts bpy objects and other non-serializable types to safe string
    representations to prevent crashes during JSON serialization.
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [sanitize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): sanitize_value(v) for k, v in value.items()}
    # Check for bpy types (have bl_rna attribute)
    if hasattr(value, "bl_rna"):
        name = getattr(value, "name", None)
        if name:
            return f"<{type(value).__name__}: {name}>"
        return f"<{type(value).__name__}>"
    # Try to verify JSON serializable, fall back to string
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)
