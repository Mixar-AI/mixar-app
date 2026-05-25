# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for space_mixie_chat.core.markdown_preprocessor module.

Tests markdown-to-plain-text conversion for Blender display.
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


class TestPreprocessMarkdownToText(unittest.TestCase):
    """Tests for preprocess_markdown_to_text() main function."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.markdown_preprocessor import (
            preprocess_markdown_to_text,
        )
        cls.preprocess = staticmethod(preprocess_markdown_to_text)

    def test_empty_string(self):
        self.assertEqual(self.preprocess(""), "")

    def test_plain_text_unchanged(self):
        self.assertEqual(self.preprocess("Hello world"), "Hello world")

    def test_combined_transforms(self):
        text = "# Title\n\n**Bold** and *italic*\n\n- item1\n- item2"
        result = self.preprocess(text)
        self.assertIn("\u25a0 Title", result)  # Black square header
        self.assertIn("Bold", result)
        self.assertNotIn("**", result)
        self.assertIn("\u2022 item1", result)


class TestProcessHeaders(unittest.TestCase):
    """Tests for _process_headers()."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.markdown_preprocessor import _process_headers
        cls.process = staticmethod(_process_headers)

    def test_h1(self):
        self.assertEqual(self.process("# Title"), "\u25a0 Title")

    def test_h2(self):
        self.assertEqual(self.process("## Subtitle"), "\u25b8 Subtitle")

    def test_h3(self):
        self.assertEqual(self.process("### Section"), "\u2022 Section")

    def test_h4(self):
        self.assertEqual(self.process("#### Sub-section"), "\u25e6 Sub-section")

    def test_h5(self):
        self.assertEqual(self.process("##### Minor"), "- Minor")

    def test_h6(self):
        self.assertEqual(self.process("###### Minor"), "- Minor")

    def test_non_header_unchanged(self):
        self.assertEqual(self.process("Just text"), "Just text")

    def test_header_in_multiline(self):
        text = "# Header\nNormal line\n## Sub"
        result = self.process(text)
        lines = result.split("\n")
        self.assertEqual(lines[0], "\u25a0 Header")
        self.assertEqual(lines[1], "Normal line")
        self.assertEqual(lines[2], "\u25b8 Sub")


class TestProcessInlineFormatting(unittest.TestCase):
    """Tests for _process_inline_formatting()."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.markdown_preprocessor import (
            _process_inline_formatting,
        )
        cls.process = staticmethod(_process_inline_formatting)

    def test_bold_asterisks(self):
        self.assertEqual(self.process("**bold**"), "bold")

    def test_bold_underscores(self):
        self.assertEqual(self.process("__bold__"), "bold")

    def test_italic_asterisk(self):
        self.assertEqual(self.process("*italic*"), "italic")

    def test_italic_underscore(self):
        self.assertEqual(self.process("_italic_"), "italic")

    def test_bold_italic(self):
        self.assertEqual(self.process("***both***"), "both")

    def test_inline_code(self):
        self.assertEqual(self.process("`code`"), "code")

    def test_strikethrough(self):
        self.assertEqual(self.process("~~deleted~~"), "deleted")

    def test_mixed_formatting(self):
        result = self.process("**bold** and *italic* and `code`")
        self.assertEqual(result, "bold and italic and code")

    def test_nested_bold_in_text(self):
        result = self.process("This is **very** important")
        self.assertEqual(result, "This is very important")


class TestProcessLinks(unittest.TestCase):
    """Tests for _process_links()."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.markdown_preprocessor import _process_links
        cls.process = staticmethod(_process_links)

    def test_basic_link(self):
        result = self.process("[Click here](https://example.com)")
        self.assertEqual(result, "Click here (https://example.com)")

    def test_link_with_title(self):
        result = self.process('[Link](https://example.com "Title")')
        self.assertEqual(result, "Link (https://example.com)")

    def test_image(self):
        result = self.process("![Alt text](https://example.com/img.png)")
        self.assertEqual(result, "[Image: Alt text]")

    def test_image_empty_alt(self):
        result = self.process("![](https://example.com/img.png)")
        self.assertEqual(result, "[Image: ]")


class TestProcessLists(unittest.TestCase):
    """Tests for _process_lists()."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.markdown_preprocessor import _process_lists
        cls.process = staticmethod(_process_lists)

    def test_dash_list(self):
        result = self.process("- item1\n- item2")
        self.assertIn("\u2022 item1", result)
        self.assertIn("\u2022 item2", result)

    def test_asterisk_list(self):
        result = self.process("* item1")
        self.assertIn("\u2022 item1", result)

    def test_plus_list(self):
        result = self.process("+ item1")
        self.assertIn("\u2022 item1", result)

    def test_numbered_list_unchanged(self):
        result = self.process("1. First\n2. Second")
        self.assertIn("1. First", result)
        self.assertIn("2. Second", result)

    def test_indented_list(self):
        result = self.process("  - nested item")
        self.assertIn("  \u2022 nested item", result)


class TestProcessCodeBlocks(unittest.TestCase):
    """Tests for _process_code_blocks()."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.markdown_preprocessor import _process_code_blocks
        cls.process = staticmethod(_process_code_blocks)

    def test_complete_code_block_with_lang(self):
        text = "```python\ndef hello():\n    print('hi')\n```"
        result = self.process(text)
        self.assertIn("[Python]", result)
        self.assertIn("1: def hello():", result)
        self.assertIn("2:     print('hi')", result)

    def test_complete_code_block_no_lang(self):
        text = "```\nline1\nline2\n```"
        result = self.process(text)
        self.assertIn("1: line1", result)
        self.assertIn("2: line2", result)
        self.assertNotIn("[", result.split("1:")[0].strip() or "x")  # No label for plain blocks

    def test_streaming_unclosed_block(self):
        text = "```python\ndef partial():"
        result = self.process(text, streaming=True)
        self.assertIn("[Python]", result)
        self.assertIn("...", result)  # Incomplete indicator

    def test_streaming_unclosed_no_lang(self):
        text = "```\nsome code"
        result = self.process(text, streaming=True)
        self.assertIn("[Code]", result)
        self.assertIn("...", result)

    def test_streaming_closed_block(self):
        text = "```python\ncomplete\n```"
        result = self.process(text, streaming=True)
        self.assertNotIn("...", result)

    def test_line_numbers_width(self):
        lines = "\n".join(f"line{i}" for i in range(15))
        text = f"```\n{lines}\n```"
        result = self.process(text)
        # With 15 lines, line numbers should be 2 digits wide
        self.assertIn(" 1: line0", result)
        self.assertIn("15: line14", result)


class TestProcessHorizontalRules(unittest.TestCase):
    """Tests for _process_horizontal_rules()."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.markdown_preprocessor import (
            _process_horizontal_rules,
        )
        cls.process = staticmethod(_process_horizontal_rules)

    def test_dashes_removed(self):
        result = self.process("text\n---\nmore")
        self.assertNotIn("---", result)

    def test_asterisks_removed(self):
        result = self.process("***")
        self.assertNotIn("***", result)

    def test_underscores_removed(self):
        result = self.process("___")
        self.assertNotIn("___", result)

    def test_long_rule_removed(self):
        result = self.process("----------")
        self.assertEqual(result.strip(), "")


class TestCleanBlankLines(unittest.TestCase):
    """Tests for _clean_blank_lines()."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.markdown_preprocessor import _clean_blank_lines
        cls.clean = staticmethod(_clean_blank_lines)

    def test_triple_newlines_reduced(self):
        result = self.clean("a\n\n\nb")
        self.assertEqual(result, "a\n\nb")

    def test_many_newlines_reduced(self):
        result = self.clean("a\n\n\n\n\n\nb")
        self.assertEqual(result, "a\n\nb")

    def test_double_newline_preserved(self):
        result = self.clean("a\n\nb")
        self.assertEqual(result, "a\n\nb")

    def test_single_newline_preserved(self):
        result = self.clean("a\nb")
        self.assertEqual(result, "a\nb")


if __name__ == "__main__":
    unittest.main()
