# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for space_mixie_chat.core.sandbox_validator module.

Tests AST-level sandbox validation for agent-generated scripts.
"""

# Install bpy mock before any mixar imports
import sys, os
_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
try:
    import bpy
except ImportError:
    import importlib.util
    _mock_spec = importlib.util.spec_from_file_location(
        "mock_bpy", os.path.join(_test_dir, "mock_bpy.py"))
    _mock_mod = importlib.util.module_from_spec(_mock_spec)
    _mock_spec.loader.exec_module(_mock_mod)

import unittest


class TestValidateScriptAST(unittest.TestCase):
    """Tests for validate_script_ast() sandbox validation."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.sandbox_validator import validate_script_ast
        cls.validate = staticmethod(validate_script_ast)

    # ------------------------------------------------------------------
    # Safe scripts (should pass)
    # ------------------------------------------------------------------

    def test_safe_script_passes(self):
        script = "x = 1 + 2\nprint(x)"
        self.assertIsNone(self.validate(script))

    def test_safe_function_def(self):
        script = "def hello():\n    return 'hi'"
        self.assertIsNone(self.validate(script))

    def test_safe_class_def(self):
        script = "class Foo:\n    def bar(self):\n        pass"
        self.assertIsNone(self.validate(script))

    def test_safe_list_comprehension(self):
        script = "[x**2 for x in range(10)]"
        self.assertIsNone(self.validate(script))

    def test_safe_import(self):
        script = "import math\nresult = math.sqrt(4)"
        self.assertIsNone(self.validate(script))

    def test_safe_string_dunder(self):
        # String containing dunder names is fine (not attribute access)
        script = "name = '__subclasses__'"
        self.assertIsNone(self.validate(script))

    def test_safe_regular_attributes(self):
        script = "obj.name\nobj.data\nobj.type"
        self.assertIsNone(self.validate(script))

    def test_safe_dunder_init(self):
        # __init__ is NOT in the blocked list
        script = "class Foo:\n    def __init__(self):\n        pass"
        self.assertIsNone(self.validate(script))

    def test_safe_dunder_str(self):
        script = "class Foo:\n    def __str__(self):\n        return ''"
        self.assertIsNone(self.validate(script))

    def test_empty_script(self):
        self.assertIsNone(self.validate(""))

    # ------------------------------------------------------------------
    # Blocked scripts (should fail)
    # ------------------------------------------------------------------

    def test_blocks_subclasses(self):
        script = "x = ().__class__.__bases__[0].__subclasses__()"
        result = self.validate(script)
        self.assertIsNotNone(result)
        self.assertIn("__subclasses__", result)

    def test_blocks_bases(self):
        script = "x = ().__class__.__bases__"
        result = self.validate(script)
        self.assertIsNotNone(result)
        self.assertIn("__bases__", result)

    def test_blocks_mro(self):
        script = "x = int.__mro__"
        result = self.validate(script)
        self.assertIsNotNone(result)
        self.assertIn("__mro__", result)

    def test_blocks_globals(self):
        script = "x = print.__globals__"
        result = self.validate(script)
        self.assertIsNotNone(result)
        self.assertIn("__globals__", result)

    def test_blocks_code(self):
        script = "x = print.__code__"
        result = self.validate(script)
        self.assertIsNotNone(result)
        self.assertIn("__code__", result)

    def test_blocks_builtins(self):
        script = "x = print.__builtins__"
        result = self.validate(script)
        self.assertIsNotNone(result)
        self.assertIn("__builtins__", result)

    def test_blocks_loader(self):
        script = "import sys; x = sys.__loader__"
        result = self.validate(script)
        self.assertIsNotNone(result)
        self.assertIn("__loader__", result)

    def test_blocks_spec(self):
        script = "import sys; x = sys.__spec__"
        result = self.validate(script)
        self.assertIsNotNone(result)
        self.assertIn("__spec__", result)

    def test_multiple_violations_reported(self):
        script = "x = ().__class__.__bases__[0].__subclasses__()"
        result = self.validate(script)
        self.assertIsNotNone(result)
        # Should contain both violations
        self.assertIn("__bases__", result)
        self.assertIn("__subclasses__", result)

    def test_classic_sandbox_escape(self):
        # Classic Python sandbox escape chain
        script = """
classes = ().__class__.__bases__[0].__subclasses__()
for c in classes:
    if 'os' in c.__name__:
        c.system('whoami')
"""
        result = self.validate(script)
        self.assertIsNotNone(result)

    def test_nested_attribute_access(self):
        script = "x.y.z.__globals__['os']"
        result = self.validate(script)
        self.assertIsNotNone(result)

    # ------------------------------------------------------------------
    # Syntax errors
    # ------------------------------------------------------------------

    def test_syntax_error_returns_message(self):
        script = "def incomplete(:"
        result = self.validate(script)
        self.assertIsNotNone(result)
        self.assertIn("Syntax error", result)

    def test_indentation_error(self):
        script = "def foo():\nreturn 1"
        result = self.validate(script)
        self.assertIsNotNone(result)

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_blocked_attr_in_method_call(self):
        script = "result = obj.__subclasses__()"
        result = self.validate(script)
        self.assertIsNotNone(result)

    def test_blocked_attr_in_assignment_target(self):
        # Even in assignment target, accessing __globals__ is blocked
        script = "func.__globals__ = {}"
        result = self.validate(script)
        self.assertIsNotNone(result)


class TestBlockedDunderAttrs(unittest.TestCase):
    """Tests for _BLOCKED_DUNDER_ATTRS completeness."""

    def test_all_blocked_attrs_present(self):
        # Sync check: forces a conscious test update whenever the blocklist
        # changes. Keep identical to sandbox_validator._BLOCKED_DUNDER_ATTRS.
        from mixar.modules.space_mixie_chat.core.sandbox_validator import _BLOCKED_DUNDER_ATTRS
        expected = {
            '__subclasses__', '__bases__', '__mro__', '__globals__',
            '__code__', '__builtins__', '__loader__', '__spec__',
            '__class__', '__dict__', '__init_subclass__', '__set_name__',
            '__closure__', '__self__', '__func__',
        }
        self.assertEqual(_BLOCKED_DUNDER_ATTRS, expected)

    def test_blocked_attrs_is_frozenset(self):
        from mixar.modules.space_mixie_chat.core.sandbox_validator import _BLOCKED_DUNDER_ATTRS
        self.assertIsInstance(_BLOCKED_DUNDER_ATTRS, frozenset)


if __name__ == "__main__":
    unittest.main()
