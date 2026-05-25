# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for space_mixie_chat.core.markdown_parser module.

Tests markdown-to-segment parsing for C++ rendering pipeline.
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

import json
import unittest


class TestExtractText(unittest.TestCase):
    """Tests for _extract_text() AST text extraction."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.markdown_parser import _extract_text
        cls.extract = staticmethod(_extract_text)

    def test_plain_string(self):
        self.assertEqual(self.extract("hello"), "hello")

    def test_text_node(self):
        self.assertEqual(self.extract({"type": "text", "raw": "hello"}), "hello")

    def test_codespan_node(self):
        self.assertEqual(self.extract({"type": "codespan", "raw": "code"}), "code")

    def test_softbreak(self):
        self.assertEqual(self.extract({"type": "softbreak"}), " ")

    def test_linebreak(self):
        self.assertEqual(self.extract({"type": "linebreak"}), "\n")

    def test_strong_node(self):
        node = {
            "type": "strong",
            "children": [{"type": "text", "raw": "bold"}],
        }
        self.assertEqual(self.extract(node), "bold")

    def test_emphasis_node(self):
        node = {
            "type": "emphasis",
            "children": [{"type": "text", "raw": "italic"}],
        }
        self.assertEqual(self.extract(node), "italic")

    def test_list_of_nodes(self):
        nodes = [
            {"type": "text", "raw": "hello "},
            {"type": "text", "raw": "world"},
        ]
        self.assertEqual(self.extract(nodes), "hello world")

    def test_nested_children(self):
        node = {
            "type": "paragraph",
            "children": [
                {"type": "text", "raw": "start "},
                {"type": "strong", "children": [{"type": "text", "raw": "bold"}]},
                {"type": "text", "raw": " end"},
            ],
        }
        self.assertEqual(self.extract(node), "start bold end")

    def test_empty_list(self):
        self.assertEqual(self.extract([]), "")

    def test_none_raw(self):
        self.assertEqual(self.extract({"type": "text"}), "")

    def test_int_input(self):
        self.assertEqual(self.extract(42), "")


class TestProcessASTNode(unittest.TestCase):
    """Tests for _process_ast_node() segment generation."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.markdown_parser import _process_ast_node
        cls.process = staticmethod(_process_ast_node)

    def test_heading(self):
        node = {
            "type": "heading",
            "attrs": {"level": 2},
            "children": [{"type": "text", "raw": "Title"}],
        }
        seg = self.process(node)
        self.assertEqual(seg["type"], "heading")
        self.assertEqual(seg["text"], "Title")
        self.assertEqual(seg["level"], 2)

    def test_paragraph(self):
        node = {
            "type": "paragraph",
            "children": [{"type": "text", "raw": "Hello world"}],
        }
        seg = self.process(node)
        self.assertEqual(seg["type"], "paragraph")
        self.assertEqual(seg["text"], "Hello world")

    def test_code_block(self):
        node = {
            "type": "block_code",
            "raw": "print('hi')\n",
            "attrs": {"info": "python"},
        }
        seg = self.process(node)
        self.assertEqual(seg["type"], "code_block")
        self.assertEqual(seg["text"], "print('hi')")
        self.assertEqual(seg["lang"], "python")

    def test_code_block_no_lang(self):
        node = {"type": "block_code", "raw": "code\n", "attrs": {}}
        seg = self.process(node)
        self.assertIsNone(seg["lang"])

    def test_unordered_list(self):
        node = {
            "type": "list",
            "attrs": {"ordered": False},
            "children": [
                {"type": "list_item", "children": [{"type": "paragraph", "children": [{"type": "text", "raw": "Item 1"}]}]},
                {"type": "list_item", "children": [{"type": "paragraph", "children": [{"type": "text", "raw": "Item 2"}]}]},
            ],
        }
        seg = self.process(node)
        self.assertEqual(seg["type"], "list")
        self.assertFalse(seg["ordered"])
        self.assertEqual(len(seg["items"]), 2)
        self.assertEqual(seg["items"][0], "Item 1")

    def test_ordered_list(self):
        node = {
            "type": "list",
            "attrs": {"ordered": True},
            "children": [
                {"type": "list_item", "children": [{"type": "paragraph", "children": [{"type": "text", "raw": "First"}]}]},
            ],
        }
        seg = self.process(node)
        self.assertTrue(seg["ordered"])

    def test_block_quote(self):
        node = {
            "type": "block_quote",
            "children": [{"type": "paragraph", "children": [{"type": "text", "raw": "Quote text"}]}],
        }
        seg = self.process(node)
        self.assertEqual(seg["type"], "quote")
        self.assertEqual(seg["text"], "Quote text")

    def test_thematic_break(self):
        seg = self.process({"type": "thematic_break"})
        self.assertEqual(seg["type"], "hr")

    def test_newline(self):
        seg = self.process({"type": "newline"})
        self.assertEqual(seg["type"], "newline")

    def test_unknown_type_returns_none(self):
        seg = self.process({"type": "unknown_thing"})
        self.assertIsNone(seg)


class TestParseMarkdownToSegments(unittest.TestCase):
    """Tests for parse_markdown_to_segments()."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.markdown_parser import parse_markdown_to_segments
        cls.parse = staticmethod(parse_markdown_to_segments)

    def test_empty_text(self):
        self.assertEqual(self.parse(""), [])

    def test_simple_paragraph(self):
        segs = self.parse("Hello world")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["type"], "paragraph")
        self.assertEqual(segs[0]["text"], "Hello world")

    def test_heading(self):
        segs = self.parse("# Main Title")
        self.assertEqual(segs[0]["type"], "heading")
        self.assertEqual(segs[0]["level"], 1)
        self.assertEqual(segs[0]["text"], "Main Title")

    def test_multiple_heading_levels(self):
        text = "# H1\n\n## H2\n\n### H3"
        segs = self.parse(text)
        levels = [s["level"] for s in segs if s["type"] == "heading"]
        self.assertEqual(levels, [1, 2, 3])

    def test_code_block(self):
        text = "```python\ndef foo():\n    pass\n```"
        segs = self.parse(text)
        code_segs = [s for s in segs if s["type"] == "code_block"]
        self.assertEqual(len(code_segs), 1)
        self.assertEqual(code_segs[0]["lang"], "python")
        self.assertIn("def foo():", code_segs[0]["text"])

    def test_mixed_content(self):
        text = "# Title\n\nSome text.\n\n```\ncode\n```\n\n- item1\n- item2"
        segs = self.parse(text)
        types = [s["type"] for s in segs]
        self.assertIn("heading", types)
        self.assertIn("paragraph", types)
        self.assertIn("code_block", types)
        self.assertIn("list", types)

    def test_streaming_unclosed_code_block(self):
        text = "Some text\n\n```python\ndef partial():"
        segs = self.parse(text, streaming=True)
        code_segs = [s for s in segs if s["type"] == "code_block"]
        self.assertEqual(len(code_segs), 1)
        self.assertIn("def partial():", code_segs[0]["text"])

    def test_streaming_closed_code_block(self):
        text = "```python\ndef complete():\n    pass\n```"
        segs = self.parse(text, streaming=True)
        code_segs = [s for s in segs if s["type"] == "code_block"]
        self.assertEqual(len(code_segs), 1)

    def test_streaming_false_does_not_close_blocks(self):
        text = "```python\ndef partial():"
        segs = self.parse(text, streaming=False)
        # Without streaming mode, unclosed block may not parse as code_block
        # It depends on mistune behavior but it should not crash
        self.assertIsInstance(segs, list)


class TestShouldFlushBuffer(unittest.TestCase):
    """Tests for should_flush_buffer() streaming boundary detection."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.markdown_parser import should_flush_buffer
        cls.should_flush = staticmethod(should_flush_buffer)

    def test_empty_text(self):
        self.assertFalse(self.should_flush(""))

    def test_sentence_end_period(self):
        self.assertTrue(self.should_flush("Hello world."))

    def test_sentence_end_exclamation(self):
        self.assertTrue(self.should_flush("Wow!"))

    def test_sentence_end_question(self):
        self.assertTrue(self.should_flush("How?"))

    def test_sentence_with_trailing_space(self):
        self.assertTrue(self.should_flush("Done.   "))

    def test_newline_triggers_flush(self):
        self.assertTrue(self.should_flush("line1\nline2"))

    def test_code_block_fence_triggers_flush(self):
        self.assertTrue(self.should_flush("```python"))

    def test_long_text_triggers_flush(self):
        from mixar.modules.space_mixie_chat.constants import STREAMING_BUFFER_FLUSH_LENGTH
        text = "x" * STREAMING_BUFFER_FLUSH_LENGTH
        self.assertTrue(self.should_flush(text))

    def test_short_text_no_boundary(self):
        self.assertFalse(self.should_flush("Hi"))


class TestSegmentsToJson(unittest.TestCase):
    """Tests for segments_to_json() serialization."""

    def test_round_trip(self):
        from mixar.modules.space_mixie_chat.core.markdown_parser import (
            segments_to_json, parse_markdown_to_segments,
        )
        segments = parse_markdown_to_segments("# Hello\n\nWorld")
        json_str = segments_to_json(segments)
        parsed = json.loads(json_str)
        self.assertIn("markdown_segments", parsed)
        self.assertEqual(len(parsed["markdown_segments"]), len(segments))

    def test_unicode_preserved(self):
        from mixar.modules.space_mixie_chat.core.markdown_parser import segments_to_json
        segments = [{"type": "paragraph", "text": "Unicode: \u2022 \u25b8 \u25a0"}]
        json_str = segments_to_json(segments)
        self.assertIn("\u2022", json_str)


class TestParseMarkdownToJson(unittest.TestCase):
    """Tests for parse_markdown_to_json() convenience function."""

    def test_returns_valid_json(self):
        from mixar.modules.space_mixie_chat.core.markdown_parser import parse_markdown_to_json
        result = parse_markdown_to_json("Hello world")
        parsed = json.loads(result)
        self.assertIn("markdown_segments", parsed)
        self.assertGreater(len(parsed["markdown_segments"]), 0)


if __name__ == "__main__":
    unittest.main()
