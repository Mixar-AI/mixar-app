# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for common.utils.platform_utils module.

Tests platform detection and keyboard shortcut formatting.
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

import sys
import unittest
from unittest.mock import patch


class TestPlatformDetection(unittest.TestCase):
    """Tests for is_macos(), is_windows(), is_linux()."""

    def test_is_macos_on_darwin(self):
        from mixar.modules.common.utils.platform_utils import is_macos
        with patch.object(sys, 'platform', 'darwin'):
            self.assertTrue(is_macos())

    def test_is_macos_on_linux(self):
        from mixar.modules.common.utils.platform_utils import is_macos
        with patch.object(sys, 'platform', 'linux'):
            self.assertFalse(is_macos())

    def test_is_windows_on_win32(self):
        from mixar.modules.common.utils.platform_utils import is_windows
        with patch.object(sys, 'platform', 'win32'):
            self.assertTrue(is_windows())

    def test_is_windows_on_linux(self):
        from mixar.modules.common.utils.platform_utils import is_windows
        with patch.object(sys, 'platform', 'linux'):
            self.assertFalse(is_windows())

    def test_is_linux_on_linux(self):
        from mixar.modules.common.utils.platform_utils import is_linux
        with patch.object(sys, 'platform', 'linux'):
            self.assertTrue(is_linux())

    def test_is_linux_on_darwin(self):
        from mixar.modules.common.utils.platform_utils import is_linux
        with patch.object(sys, 'platform', 'darwin'):
            self.assertFalse(is_linux())

    def test_exactly_one_platform_is_true(self):
        from mixar.modules.common.utils import platform_utils as pu
        # On the current platform, exactly one should be true
        results = [pu.is_macos(), pu.is_windows(), pu.is_linux()]
        self.assertEqual(sum(results), 1, "Exactly one platform check should be True")


class TestCommandModifier(unittest.TestCase):
    """Tests for get_command_modifier()."""

    def test_macos_returns_cmd(self):
        from mixar.modules.common.utils.platform_utils import get_command_modifier
        with patch.object(sys, 'platform', 'darwin'):
            self.assertEqual(get_command_modifier(), "Cmd")

    def test_linux_returns_ctrl(self):
        from mixar.modules.common.utils.platform_utils import get_command_modifier
        with patch.object(sys, 'platform', 'linux'):
            self.assertEqual(get_command_modifier(), "Ctrl")

    def test_windows_returns_ctrl(self):
        from mixar.modules.common.utils.platform_utils import get_command_modifier
        with patch.object(sys, 'platform', 'win32'):
            self.assertEqual(get_command_modifier(), "Ctrl")


class TestKeymapModifier(unittest.TestCase):
    """Tests for get_keymap_modifier()."""

    def test_macos_uses_oskey(self):
        from mixar.modules.common.utils.platform_utils import get_keymap_modifier
        with patch.object(sys, 'platform', 'darwin'):
            result = get_keymap_modifier()
            self.assertTrue(result.get('oskey'))
            self.assertFalse(result.get('ctrl'))

    def test_linux_uses_ctrl(self):
        from mixar.modules.common.utils.platform_utils import get_keymap_modifier
        with patch.object(sys, 'platform', 'linux'):
            result = get_keymap_modifier()
            self.assertTrue(result.get('ctrl'))
            self.assertFalse(result.get('oskey'))


class TestFormatShortcut(unittest.TestCase):
    """Tests for format_shortcut()."""

    def test_simple_shortcut_linux(self):
        from mixar.modules.common.utils.platform_utils import format_shortcut
        with patch.object(sys, 'platform', 'linux'):
            result = format_shortcut("P")
            self.assertEqual(result, "Ctrl+P")

    def test_simple_shortcut_macos(self):
        from mixar.modules.common.utils.platform_utils import format_shortcut
        with patch.object(sys, 'platform', 'darwin'):
            result = format_shortcut("P")
            self.assertEqual(result, "Cmd+P")

    def test_with_shift(self):
        from mixar.modules.common.utils.platform_utils import format_shortcut
        with patch.object(sys, 'platform', 'linux'):
            result = format_shortcut("P", shift=True)
            self.assertEqual(result, "Ctrl+Shift+P")

    def test_with_alt_linux(self):
        from mixar.modules.common.utils.platform_utils import format_shortcut
        with patch.object(sys, 'platform', 'linux'):
            result = format_shortcut("C", alt=True)
            self.assertEqual(result, "Ctrl+Alt+C")

    def test_with_alt_macos(self):
        from mixar.modules.common.utils.platform_utils import format_shortcut
        with patch.object(sys, 'platform', 'darwin'):
            result = format_shortcut("C", alt=True)
            self.assertEqual(result, "Cmd+Option+C")

    def test_no_command_modifier(self):
        from mixar.modules.common.utils.platform_utils import format_shortcut
        result = format_shortcut("F5", use_command=False)
        self.assertEqual(result, "F5")

    def test_all_modifiers(self):
        from mixar.modules.common.utils.platform_utils import format_shortcut
        with patch.object(sys, 'platform', 'linux'):
            result = format_shortcut("Z", shift=True, alt=True)
            self.assertEqual(result, "Ctrl+Shift+Alt+Z")


if __name__ == "__main__":
    unittest.main()
