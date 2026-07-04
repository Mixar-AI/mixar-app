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

from .sandbox_validator import _BLOCKED_DUNDER_ATTRS

# Restricted builtins whitelist for safe script execution
# Excludes dangerous functions like: eval, exec, compile, __import__,
# globals, locals, input, breakpoint
# NOTE: vars and dir are included (guarded by sandbox dunder checks)
SAFE_BUILTIN_NAMES = frozenset({
    # Type constructors
    'bool', 'bytearray', 'bytes', 'complex', 'dict', 'float', 'frozenset',
    'int', 'list', 'object', 'set', 'slice', 'str', 'tuple',
    # Iteration/sequences
    'all', 'any', 'enumerate', 'filter', 'iter', 'len', 'map', 'max',
    'min', 'next', 'range', 'reversed', 'sorted', 'sum', 'zip',
    # Math
    'abs', 'divmod', 'pow', 'round',
    # Attribute access / introspection
    'getattr', 'hasattr', 'setattr', 'isinstance', 'issubclass', 'dir', 'vars',
    # Output (safe)
    'print', 'repr', 'format', 'ascii', 'bin', 'hex', 'oct', 'chr', 'ord',
    # Other safe functions
    'callable', 'hash', 'id', 'len', 'staticmethod', 'classmethod', 'property',
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
    # Include common exceptions for error handling
    safe_builtins['Exception'] = Exception
    safe_builtins['ValueError'] = ValueError
    safe_builtins['TypeError'] = TypeError
    safe_builtins['KeyError'] = KeyError
    safe_builtins['IndexError'] = IndexError
    safe_builtins['AttributeError'] = AttributeError
    safe_builtins['RuntimeError'] = RuntimeError
    safe_builtins['StopIteration'] = StopIteration
    safe_builtins['FileNotFoundError'] = FileNotFoundError
    safe_builtins['OSError'] = OSError
    safe_builtins['PermissionError'] = PermissionError

    # __import__ is intentionally excluded from SAFE_BUILTIN_NAMES.
    # Instead, a restricted __import__ is injected in execute() that only
    # allows importing modules already pre-injected into exec_namespace.

    # Wrap getattr/hasattr to block runtime dunder access via string
    # concatenation (e.g. getattr(obj, '__sub'+'classes__')).
    # This closes the bypass where computed attribute names evade AST checks.
    _original_getattr = builtins.getattr

    def _safe_getattr(obj, name, *default):
        if isinstance(name, str) and name in _BLOCKED_DUNDER_ATTRS:
            raise AttributeError(
                f"Access to '{name}' is blocked (sandbox restriction)"
            )
        return _original_getattr(obj, name, *default)

    def _safe_hasattr(obj, name):
        if isinstance(name, str) and name in _BLOCKED_DUNDER_ATTRS:
            return False
        try:
            _original_getattr(obj, name)
            return True
        except AttributeError:
            return False

    def _safe_setattr(obj, name, value):
        if isinstance(name, str) and name in _BLOCKED_DUNDER_ATTRS:
            raise AttributeError(
                f"Setting '{name}' is blocked (sandbox restriction)"
            )
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
