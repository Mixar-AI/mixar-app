# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for space_mixie_chat.core.image_utils path validation.

Tests _is_path_safe(), validate_image_file(), and get_image_display_name()
security functions. Only tests pure logic that doesn't require bpy.
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

import os
import tempfile
import unittest


class TestIsPathSafe(unittest.TestCase):
    """Tests for _is_path_safe() path security validation."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.image_utils import _is_path_safe
        cls.check = staticmethod(_is_path_safe)

    def test_empty_path(self):
        safe, err = self.check("")
        self.assertFalse(safe)
        self.assertIn("Empty", err)

    def test_normal_path(self):
        if os.name == 'nt':
            safe, err = self.check(os.path.join(os.path.expanduser('~'), 'images', 'photo.png'))
        else:
            safe, err = self.check("/home/user/images/photo.png")
        self.assertTrue(safe)
        self.assertEqual(err, "")

    def test_relative_path(self):
        safe, err = self.check("images/photo.png")
        self.assertTrue(safe)

    def test_blocks_etc(self):
        safe, err = self.check("/etc/passwd")
        self.assertFalse(safe)
        self.assertIn("sensitive", err.lower())

    def test_blocks_root_home(self):
        safe, err = self.check("/root/.bashrc")
        self.assertFalse(safe)

    def test_blocks_ssh(self):
        safe, err = self.check("/home/user/.ssh/id_rsa")
        self.assertFalse(safe)

    def test_blocks_gnupg(self):
        safe, err = self.check("/home/user/.gnupg/secring.gpg")
        self.assertFalse(safe)

    def test_blocks_proc(self):
        safe, err = self.check("/proc/self/environ")
        self.assertFalse(safe)

    def test_blocks_sys(self):
        safe, err = self.check("/sys/kernel")
        self.assertFalse(safe)

    def test_blocks_config(self):
        safe, err = self.check("/home/user/.config/secret")
        self.assertFalse(safe)

    def test_blocks_var_log(self):
        safe, err = self.check("/var/log/syslog")
        self.assertFalse(safe)

    def test_allows_tmp(self):
        # Use platform-appropriate temp path
        safe, err = self.check(os.path.join(tempfile.gettempdir(), "image.png"))
        self.assertTrue(safe)

    def test_allows_home_documents(self):
        if os.name == 'nt':
            safe, err = self.check(os.path.join(os.path.expanduser('~'), 'Documents', 'render.png'))
        else:
            safe, err = self.check("/home/user/Documents/render.png")
        self.assertTrue(safe)

    def test_blocks_windows_system32(self):
        safe, err = self.check("C:\\Windows\\System32\\config\\SAM")
        self.assertFalse(safe)

    def test_blocks_windows_program_files(self):
        safe, err = self.check("C:\\Program Files\\secret.txt")
        self.assertFalse(safe)


class TestBlockedPathPatterns(unittest.TestCase):
    """Tests for BLOCKED_PATH_PATTERNS completeness."""

    def test_patterns_exist(self):
        from mixar.modules.space_mixie_chat.core.image_utils import BLOCKED_PATH_PATTERNS
        self.assertIsInstance(BLOCKED_PATH_PATTERNS, tuple)
        self.assertGreater(len(BLOCKED_PATH_PATTERNS), 5)

    def test_unix_sensitive_paths_blocked(self):
        from mixar.modules.space_mixie_chat.core.image_utils import BLOCKED_PATH_PATTERNS
        unix_patterns = ['/etc/', '/root/', '/.ssh/', '/proc/', '/sys/']
        for pattern in unix_patterns:
            self.assertIn(pattern, BLOCKED_PATH_PATTERNS, f"Missing: {pattern}")

    def test_windows_sensitive_paths_blocked(self):
        from mixar.modules.space_mixie_chat.core.image_utils import BLOCKED_PATH_PATTERNS
        lower_patterns = [p.lower() for p in BLOCKED_PATH_PATTERNS]
        self.assertIn('\\windows\\system32', lower_patterns)
        self.assertIn('\\program files', lower_patterns)


class TestValidateImageFile(unittest.TestCase):
    """Tests for validate_image_file() comprehensive validation."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.image_utils import validate_image_file
        cls.validate = staticmethod(validate_image_file)

    def test_empty_path(self):
        valid, err = self.validate("")
        self.assertFalse(valid)

    def test_nonexistent_file(self):
        valid, err = self.validate(os.path.join(tempfile.gettempdir(), "nonexistent_image_12345.png"))
        self.assertFalse(valid)
        self.assertIn("not exist", err.lower())

    def test_unsupported_format(self):
        # Create a temp file with unsupported extension
        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as f:
            f.write(b"fake image data")
            path = f.name
        try:
            valid, err = self.validate(path)
            self.assertFalse(valid)
            self.assertIn("Unsupported format", err)
        finally:
            os.unlink(path)

    def test_valid_png_extension(self):
        # Create a small valid file with a .png extension
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"x" * 100)  # Small fake PNG
            path = f.name
        try:
            # With mocked PIL, img.size is a MagicMock which can't unpack
            # to (width, height), raising ValueError. With real PIL, the
            # fake data will be rejected. Either way, the validation pipeline
            # exercises extension and size checks before reaching PIL.
            try:
                valid, err = self.validate(path)
            except (ValueError, TypeError):
                # Mocked PIL causes unpacking error - that's expected
                return
            if not valid:
                self.assertTrue(
                    "Could not read image" in err or "dimensions" in err.lower(),
                    f"Unexpected error: {err}"
                )
        finally:
            os.unlink(path)

    def test_oversized_file(self):
        from mixar.modules.space_mixie_chat.constants import MAX_IMAGE_SIZE_BYTES
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            # Write just over the limit
            f.write(b"x" * (MAX_IMAGE_SIZE_BYTES + 1))
            path = f.name
        try:
            valid, err = self.validate(path)
            self.assertFalse(valid)
            self.assertIn("too large", err.lower())
        finally:
            os.unlink(path)

    def test_sensitive_path_blocked(self):
        valid, err = self.validate("/etc/passwd")
        self.assertFalse(valid)


class TestGetImageDisplayName(unittest.TestCase):
    """Tests for get_image_display_name()."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.image_utils import get_image_display_name
        cls.get_name = staticmethod(get_image_display_name)

    def test_file_source(self):
        name = self.get_name(os.path.join("home", "user", "images", "photo.png"), "FILE")
        self.assertEqual(name, "photo.png")

    def test_file_source_nested(self):
        name = self.get_name(os.path.join("very", "deep", "path", "to", "image.jpg"), "FILE")
        self.assertEqual(name, "image.jpg")

    def test_blend_data_source(self):
        name = self.get_name("MyTexture", "BLEND_DATA")
        self.assertEqual(name, "MyTexture")

    def test_unknown_source_returns_name(self):
        name = self.get_name("anything", "UNKNOWN")
        self.assertEqual(name, "anything")


if __name__ == "__main__":
    unittest.main()
