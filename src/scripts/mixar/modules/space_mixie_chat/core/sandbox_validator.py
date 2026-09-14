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
