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
})


class _SandboxASTValidator(ast.NodeVisitor):
    """Validates script AST for sandbox escape patterns.

    Visits all AST nodes and collects violations for:
    - Attribute access to blocked dunder names
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
