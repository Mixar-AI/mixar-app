# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Markdown renderer for Mixie Chat using mistune.

Parses markdown to AST and renders using Blender's UI primitives.
Designed for streaming - handles incomplete markdown gracefully.
"""

from typing import Optional

import mistune

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Create AST parser (reused for performance)
_md = mistune.create_markdown(renderer='ast')


def parse_markdown(text: str) -> list:
    """
    Parse markdown text and return AST.

    Args:
        text: Markdown text to parse

    Returns:
        List of AST nodes from mistune
    """
    if not text:
        return []
    return _md(text)


def parse_markdown_streaming(text: str) -> list:
    """
    Parse markdown with streaming-friendly handling.

    Handles incomplete markdown (e.g., unclosed code blocks).
    """
    if not text:
        return []

    # Check for unclosed code block - add closing fence for parsing
    code_fence_count = text.count('```')
    if code_fence_count % 2 == 1:
        text = text + '\n```'

    return parse_markdown(text)


def draw_markdown(layout, text: str, max_width: int = 60, streaming: bool = False):
    """
    Draw markdown-formatted text in Blender UI.

    Args:
        layout: Blender UI layout
        text: Markdown text to render
        max_width: Maximum characters per line
        streaming: If True, handle incomplete markdown gracefully
    """
    if not text:
        return

    try:
        ast = parse_markdown_streaming(text) if streaming else parse_markdown(text)

        if not ast:
            # Fallback to plain text
            _draw_wrapped_lines(layout, text, max_width)
            return

        # Render AST nodes
        for node in ast:
            _render_node(layout, node, max_width)
    except Exception as e:
        # Log error and fallback to plain text
        logger.error(f"Markdown rendering failed: {e}")
        _draw_wrapped_lines(layout, text, max_width)


def _render_node(layout, node: dict, max_width: int):
    """Render a single AST node."""
    node_type = node.get('type', '')

    if node_type == 'heading':
        _draw_heading(layout, node, max_width)
    elif node_type == 'paragraph':
        _draw_paragraph(layout, node, max_width)
    elif node_type == 'block_code':
        _draw_code_block(layout, node)
    elif node_type == 'list':
        _draw_list(layout, node, max_width)
    elif node_type == 'block_quote':
        _draw_quote(layout, node, max_width)
    elif node_type == 'thematic_break':
        _draw_hr(layout, max_width)
    elif node_type == 'newline':
        layout.separator(factor=0.2)


def _extract_text(node) -> str:
    """Recursively extract plain text from AST node."""
    if isinstance(node, str):
        return node

    if isinstance(node, dict):
        node_type = node.get('type', '')

        # Raw text node
        if node_type == 'text':
            return node.get('raw', '')

        # Inline code
        if node_type == 'codespan':
            return f"`{node.get('raw', '')}`"

        # Link
        if node_type == 'link':
            children_text = _extract_text(node.get('children', []))
            return children_text

        # Strong/emphasis - just get inner text
        if node_type in ('strong', 'emphasis'):
            return _extract_text(node.get('children', []))

        # Recursively extract from children
        children = node.get('children', [])
        if children:
            return _extract_text(children)

        return node.get('raw', '')

    if isinstance(node, list):
        return ''.join(_extract_text(child) for child in node)

    return ''


def _draw_heading(layout, node: dict, max_width: int):
    """Draw a heading with visual emphasis and logical separators."""
    level = node.get('attrs', {}).get('level', 1)
    text = _extract_text(node.get('children', []))

    layout.separator(factor=0.5)
    
    if level == 1:
        layout.label(text=text.upper(), icon='BOOKMARKS')
        layout.separator(factor=0.2)
    elif level == 2:
        layout.label(text=text, icon='RIGHTARROW')
        layout.separator(factor=0.1)
    else:
        layout.label(text=text, icon='DOT')
        
    layout.separator(factor=0.2)


def _draw_paragraph(layout, node: dict, max_width: int):
    """Draw a regular paragraph."""
    text = _extract_text(node.get('children', []))
    if text.strip():
        col = layout.column(align=True)
        _draw_wrapped_lines(col, text, max_width)
        layout.separator(factor=0.4)


def _draw_code_block(layout, node: dict):
    """Draw a code block with distinct styling in a box."""
    code = node.get('raw', '')
    info = node.get('attrs', {}).get('info', '')
    language = info.strip() if info else None

    box = layout.box()
    col = box.column(align=True)

    if language:
        row = col.row()
        row.label(text=f" {language}", icon='TEXT')
        col.separator(factor=0.5)

    lines = code.rstrip('\n').split('\n')
    for line in lines:
        if len(line) > 70:
            line = line[:67] + "..."
        col.label(text=f"  {line}" if line else " ")
    layout.separator(factor=0.4)


def _draw_list(layout, node: dict, max_width: int):
    """Draw a list (ordered or unordered)."""
    ordered = node.get('attrs', {}).get('ordered', False)
    children = node.get('children', [])

    col = layout.column(align=True)
    for i, item in enumerate(children):
        if item.get('type') == 'list_item':
            text = _extract_text(item.get('children', []))

            row = col.row(align=True)
            if ordered:
                row.label(text=f"{i + 1}.")
            else:
                row.label(text="", icon='DOT')

            item_col = row.column(align=True)
            _draw_wrapped_lines(item_col, text, max_width - 4)
            item_col.separator(factor=0.2)
    layout.separator(factor=0.2)


def _draw_quote(layout, node: dict, max_width: int):
    """Draw a blockquote with visual indicator."""
    text = _extract_text(node.get('children', []))

    row = layout.row(align=True)
    row.label(text="", icon='QUOTE')
    col = row.column(align=True)
    _draw_wrapped_lines(col, text, max_width - 4)
    layout.separator(factor=0.4)


def _draw_hr(layout, max_width: int):
    """Draw a horizontal rule."""
    layout.separator()
    layout.label(text="─" * min(max_width, 50))
    layout.separator()


def _draw_wrapped_lines(layout, text: str, max_width: int):
    """Draw text with word wrapping."""
    if not text:
        layout.label(text=" ")
        return

    # Handle newlines within text
    paragraphs = text.split('\n')

    for para in paragraphs:
        if not para.strip():
            layout.label(text=" ")
            continue

        words = para.split()
        line = ""

        for word in words:
            test_line = f"{line} {word}".strip() if line else word
            if len(test_line) > max_width:
                if line:
                    layout.label(text=line)
                line = word
            else:
                line = test_line

        if line:
            layout.label(text=line)
