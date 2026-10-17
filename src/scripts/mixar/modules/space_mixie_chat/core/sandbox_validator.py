# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
AST-level sandbox validation for agent-generated scripts.

Provides defense-in-depth by scanning the AST before compile/exec to block
common Python sandbox escape patterns (introspection chains, dunder attribute
access). This complements the runtime sandbox (restricted builtins, module
wrappers) but is NOT a complete sandbox on its own — computed attribute names
like getattr(x, '__sub'+'classes__') bypass static analysis.
"""

import ast
import re
from mixar.config.logging_config import get_logger
from typing import Optional

from .sandbox_denylist import (
    DENIED_ATTR_NAMES,
    denied_ops_kwargs,
    is_denied_ops_namespace,
    op_denial_reason,
    types_denial_reason,
)

logger = get_logger(__name__)

# Attribute names that enable sandbox escape via introspection.
# The classic exploit chain is:
#   ().__class__.__bases__[0].__subclasses__()
# which walks the class hierarchy to find classes that import os, subprocess, etc.
_BLOCKED_DUNDER_ATTRS = frozenset({
    '__subclasses__',    # Class hierarchy walk → find importers
    '__bases__',         # Class hierarchy traversal
    '__mro__',           # Method resolution order (alternate hierarchy access)
    '__globals__',       # Function's global namespace (has real modules)
    '__code__',          # Code object manipulation (can create new functions)
    '__builtins__',      # Real builtins dict (bypasses whitelist)
    '__loader__',        # Module loader (can import arbitrary modules)
    '__spec__',          # Module spec (can import arbitrary modules)
    '__class__',         # Fundamental to class hierarchy escape chain
    '__dict__',          # Direct access to object namespaces
    '__init_subclass__', # Metaclass tricks via subclass hooks
    '__set_name__',      # Descriptor protocol abuse
    '__closure__',       # Closure cells → reach objects captured by a function
    '__self__',          # Bound method's instance → reach a wrapped object
    '__func__',          # Bound method's underlying function (→ __globals__ chain)
    # Raw attribute slots. object.__getattribute__(cls, '__subclasses__') is the
    # C-level lookup the wrapped getattr never sees, and `object` is an allowed
    # builtin — without these the whole denylist above is one hop from useless.
    '__getattribute__',  # Raw attribute lookup → every blocked name above
    '__getattr__',       # Same, on any object that defines the hook
    '__setattr__',       # Raw attribute write (bypasses the wrapped setattr)
    '__delattr__',       # Raw attribute delete
    '__reduce__',        # Pickle protocol → callable + args to rebuild objects
    '__reduce_ex__',     # Same
    '__subclasshook__',  # Bound to the class → another handle on the hierarchy
})

# Format strings do attribute access in C: '{0.__class__}'.format(x) never
# produces an Attribute node and never calls the wrapped getattr. The rendered
# result is only a repr (string.Formatter, which returns the real object, is not
# exposed — see sandbox_modules.RestrictedString), but a repr of __globals__
# still leaks process state, so a blocked dunder inside a replacement field is a
# violation wherever the literal is written.
_FORMAT_FIELD_RE = re.compile(r"\{([^{}]*)\}")
_FORMAT_ATTR_RE = re.compile(r"\.\s*(__\w+__)")


class _SandboxASTValidator(ast.NodeVisitor):
    """Validates script AST for sandbox escape patterns.

    Visits all AST nodes and collects violations for:
    - Attribute access to blocked dunder names
    - Blocked dunder names inside format-string replacement fields
    """

    def __init__(self):
        self.violations: list[str] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _BLOCKED_DUNDER_ATTRS:
            self.violations.append(
                f"Line {node.lineno}: access to '{node.attr}' is blocked "
                f"(sandbox restriction)"
            )
        elif node.attr in DENIED_ATTR_NAMES:
            self.violations.append(
                f"Line {node.lineno}: '{node.attr}' is blocked (sandbox "
                f"restriction): it runs code outside the sandbox"
            )
        else:
            reason = _ops_chain_denial(node) or _types_chain_denial(node)
            if reason:
                self.violations.append(f"Line {node.lineno}: {reason}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # bpy.ops.node.add_node(settings=[...]) eval()s each setting value.
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Attribute)
            and isinstance(func.value.value, ast.Attribute)
            and func.value.value.attr == "ops"
        ):
            denied = denied_ops_kwargs(func.value.attr)
            for keyword in node.keywords:
                if keyword.arg in denied:
                    self.violations.append(
                        f"Line {node.lineno}: bpy.ops.{func.value.attr}."
                        f"{func.attr}({keyword.arg}=...) is blocked (sandbox "
                        f"restriction): the operator eval()s it"
                    )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # `from bpy.utils import execfile` binds the name without an
        # Attribute node.
        for alias in node.names:
            if alias.name in DENIED_ATTR_NAMES:
                self.violations.append(
                    f"Line {node.lineno}: importing '{alias.name}' is blocked "
                    f"(sandbox restriction): it runs code outside the sandbox"
                )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            for field in _FORMAT_FIELD_RE.findall(node.value):
                for attr in _FORMAT_ATTR_RE.findall(field):
                    if attr in _BLOCKED_DUNDER_ATTRS:
                        self.violations.append(
                            f"Line {node.lineno}: format string reaches "
                            f"'{attr}' (sandbox restriction)"
                        )
        self.generic_visit(node)


def _ops_chain_denial(node: ast.Attribute):
    """Reason ``<x>.ops.<ns>`` or ``<x>.ops.<ns>.<op>`` is refused, or None.

    Only the static spelling; computed names are refused at runtime by the
    bpy.ops proxy (sandbox_bpy.py), which enforces the same set.
    """
    value = node.value
    if isinstance(value, ast.Attribute) and value.attr == "ops":
        if is_denied_ops_namespace(node.attr):
            return op_denial_reason(node.attr, "")
        return None
    if (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Attribute)
        and value.value.attr == "ops"
        and not is_denied_ops_namespace(value.attr)  # reported one level up
    ):
        return op_denial_reason(value.attr, node.attr)
    return None


def _types_chain_denial(node: ast.Attribute):
    """Reason ``<x>.types.<X_OT_y>`` is refused, or None.

    Only the operator-struct spelling is decidable statically; whether a
    class was registered from Python is checked at runtime by the bpy.types
    proxy (sandbox_bpy.py), which enforces the same rule.
    """
    value = node.value
    if isinstance(value, ast.Attribute) and value.attr == "types":
        return types_denial_reason(node.attr)
    return None


def validate_script_ast(script: str) -> Optional[str]:
    """Validate script AST for sandbox safety before compilation.

    Parses the script and walks the AST to detect patterns that could
    be used to escape the execution sandbox.

    Args:
        script: Python source code to validate

    Returns:
        None if the script passes validation, or an error message
        string describing the violations found.
    """
    try:
        tree = ast.parse(script, filename="<agent_script>", mode='exec')
    except SyntaxError as e:
        return f"Syntax error: {e}"

    validator = _SandboxASTValidator()
    validator.visit(tree)

    if validator.violations:
        msg = "Script blocked by sandbox:\n" + "\n".join(
            f"  - {v}" for v in validator.violations
        )
        logger.warning(msg)
        return msg

    return None
