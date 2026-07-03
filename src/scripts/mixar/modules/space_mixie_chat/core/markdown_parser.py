# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Markdown parser for Mixie Chat using mistune.

Parses markdown to structured segments for C++ rendering.
Designed for streaming - handles incomplete markdown gracefully.
"""

import json
from mixar.config.logging_config import get_logger
import re

import mistune

logger = get_logger(__name__)

# Create AST parser with table plugin (reused for performance)
_md = mistune.create_markdown(renderer='ast', plugins=['table'])


def _extract_text(node) -> str:
    """Recursively extract plain text from AST node."""
    if isinstance(node, str):
        return node

    if isinstance(node, dict):
        node_type = node.get('type', '')

        if node_type == 'text':
            return node.get('raw', '')

        if node_type == 'codespan':
            return node.get('raw', '')

        if node_type == 'softbreak':
            return ' '

        if node_type == 'linebreak':
            return '\n'

        if node_type in ('strong', 'emphasis', 'link'):
            return _extract_text(node.get('children', []))

        children = node.get('children', [])
        if children:
            return _extract_text(children)

        return node.get('raw', '')

    if isinstance(node, list):
        return ''.join(_extract_text(child) for child in node)

    return ''


def _extract_inline(node) -> str:
    """Extract text while PRESERVING lightweight inline markdown markers.

    Unlike `_extract_text` (which flattens everything to plain text), this
    keeps `**bold**`, `*italic*` and `` `code` `` markers in the string so the
    C++ rich-text renderer can style inline runs. Used for paragraph / heading
    / list-item / quote text; tables still use the plain extractor.
    """
    if isinstance(node, str):
        return node

    if isinstance(node, dict):
        node_type = node.get('type', '')

        if node_type == 'text':
            return node.get('raw', '')
        if node_type == 'codespan':
            return '`' + node.get('raw', '') + '`'
        if node_type == 'strong':
            return '**' + _extract_inline(node.get('children', [])) + '**'
        if node_type == 'emphasis':
            return '*' + _extract_inline(node.get('children', [])) + '*'
        if node_type == 'softbreak':
            return ' '
        if node_type == 'linebreak':
            return '\n'
        if node_type == 'link':
            # Render the link's visible text only (URL dropped for now).
            return _extract_inline(node.get('children', []))

        children = node.get('children', [])
        if children:
            return _extract_inline(children)
        return node.get('raw', '')

    if isinstance(node, list):
        return ''.join(_extract_inline(child) for child in node)

    return ''


def _process_ast_node(node: dict) -> dict:
    """Convert AST node to segment format for C++ rendering."""
    node_type = node.get('type', '')

    if node_type == 'heading':
        level = node.get('attrs', {}).get('level', 1)
        text = _extract_inline(node.get('children', []))
        return {'type': 'heading', 'text': text, 'level': level}

    elif node_type == 'paragraph':
        text = _extract_inline(node.get('children', []))
        return {'type': 'paragraph', 'text': text}

    elif node_type == 'block_code':
        code = node.get('raw', '')
        info = node.get('attrs', {}).get('info', '')
        lang = info.strip() if info else None
        return {'type': 'code_block', 'text': code.rstrip('\n'), 'lang': lang}

    elif node_type == 'list':
        attrs = node.get('attrs', {})
        ordered = attrs.get('ordered', False)
        start = attrs.get('start', 1)
        return _process_list_node(node.get('children', []), ordered, start)

    elif node_type == 'table':
        return _process_table_node(node)

    elif node_type == 'block_quote':
        text = _extract_inline(node.get('children', []))
        return {'type': 'quote', 'text': text}

    elif node_type == 'thematic_break':
        return {'type': 'hr'}

    elif node_type == 'newline':
        return {'type': 'newline'}

    return None


def _process_list_node(children: list, ordered: bool, start: int = 1):
    """Process a list AST node, handling nested sub-lists.

    Nested sub-lists are separated into their own segments emitted after
    the parent list. The C++ renderer uses start_index for numbering,
    so ordered sub-lists render correctly (e.g. starting at 1 independently).

    Each item's text is capped at 256 chars to fit C++ item buffers.

    Returns:
        A single list segment dict, or a list of segments when nesting exists.
    """
    items = []
    nested_after = []  # Sub-lists collected in document order

    for child in children:
        if child.get('type') != 'list_item':
            continue

        item_children = child.get('children', [])
        text_parts = []

        for sub in item_children:
            if sub.get('type') == 'list':
                sub_attrs = sub.get('attrs', {})
                nested = _process_list_node(
                    sub.get('children', []),
                    sub_attrs.get('ordered', False),
                    sub_attrs.get('start', 1),
                )
                if nested:
                    if isinstance(nested, list):
                        nested_after.extend(nested)
                    else:
                        nested_after.append(nested)
            else:
                part = _extract_inline(sub).strip()
                if part:
                    text_parts.append(part)

        item_text = ' — '.join(text_parts) if len(text_parts) > 1 else (
            text_parts[0] if text_parts else ''
        )
        if item_text:
            # C++ items buffer is char[256]; truncate with ellipsis
            if len(item_text) > 252:
                item_text = item_text[:251] + '\u2026'
            items.append(item_text)

    if not items and not nested_after:
        return None

    result = []
    if items:
        seg = {'type': 'list', 'items': items, 'ordered': ordered}
        if ordered:
            seg['start'] = start
        result.append(seg)
    result.extend(nested_after)

    if len(result) == 1:
        return result[0]
    return result


def _process_table_node(node: dict) -> dict:
    """Convert table AST node to tab/newline-delimited text for C++ rendering.

    Format: first line = header (tab-separated), subsequent lines = rows.
    Cell content is sanitized (tabs/newlines replaced with spaces).
    """
    headers = []
    rows = []
    max_rows = 20  # Cap rows to fit in C++ text buffer (8192 bytes)
    max_cell = 60  # Truncate individual cells

    for child in node.get('children', []):
        child_type = child.get('type', '')
        if child_type == 'table_head':
            # mistune 3.x: table_head has table_cell children directly (no table_row wrapper)
            for cell_or_row in child.get('children', []):
                if cell_or_row.get('type') == 'table_cell':
                    text = _extract_text(cell_or_row.get('children', []))
                    text = _sanitize_cell(text, max_cell)
                    headers.append(text)
                elif cell_or_row.get('type') == 'table_row':
                    for cell in cell_or_row.get('children', []):
                        if cell.get('type') == 'table_cell':
                            text = _extract_text(cell.get('children', []))
                            text = _sanitize_cell(text, max_cell)
                            headers.append(text)
        elif child_type == 'table_body':
            for row_node in child.get('children', []):
                if row_node.get('type') == 'table_row' and len(rows) < max_rows:
                    row_cells = []
                    for cell in row_node.get('children', []):
                        if cell.get('type') == 'table_cell':
                            text = _extract_text(cell.get('children', []))
                            text = _sanitize_cell(text, max_cell)
                            row_cells.append(text)
                    if row_cells:
                        rows.append(row_cells)

    if not headers:
        return None

    # Build tab-delimited text: header line + row lines
    lines = ['\t'.join(headers)]
    for row in rows:
        # Pad row to match header column count
        while len(row) < len(headers):
            row.append('')
        lines.append('\t'.join(row[:len(headers)]))

    return {'type': 'table', 'text': '\n'.join(lines)}


def _sanitize_cell(text: str, max_len: int) -> str:
    """Clean cell text for tab-delimited encoding."""
    text = text.strip().replace('\t', ' ').replace('\n', ' ')
    if len(text) > max_len:
        text = text[:max_len - 1] + '\u2026'  # ellipsis
    return text


def parse_markdown_to_segments(text: str, streaming: bool = False) -> list:
    """
    Parse markdown text to structured segments.

    Args:
        text: Markdown text to parse
        streaming: If True, handle incomplete markdown (unclosed code blocks)

    Returns:
        List of segment dicts:
        - {'type': 'paragraph', 'text': '...'}
        - {'type': 'heading', 'text': '...', 'level': 1-6}
        - {'type': 'code_block', 'text': '...', 'lang': 'python' or None}
        - {'type': 'list', 'items': ['...', '...'], 'ordered': False}
        - {'type': 'quote', 'text': '...'}
        - {'type': 'hr'}
    """
    if not text:
        return []

    # Handle unclosed code blocks for streaming.
    # Match fences at line start (with optional indent), which handles
    # language specifiers like ```python and avoids false positives
    # from inline triple-backticks.
    if streaming:
        code_fence_count = len(re.findall(r'^[ ]{0,3}```', text, re.MULTILINE))
        if code_fence_count % 2 == 1:
            text = text + '\n```'

    try:
        ast = _md(text)
    except Exception as e:
        logger.error(f"Markdown parsing failed: {e}")
        # Fallback: return as single paragraph
        return [{'type': 'paragraph', 'text': text}]

    if not ast:
        return [{'type': 'paragraph', 'text': text}]

    segments = []
    for node in ast:
        result = _process_ast_node(node)
        if result:
            if isinstance(result, list):
                segments.extend(result)
            else:
                segments.append(result)

    return segments


# =============================================================================
# Incremental Markdown Parsing Cache
# =============================================================================

# Per-bubble cache: bubble_id -> (boundary_offset, stable_segments, prefix_text, in_fence)
# stable_segments covers text[:boundary_offset]. On each append, we scan only
# the new text to find block boundaries, then re-parse only the tail.
_incremental_cache: dict[str, tuple[int, list, str, bool]] = {}
_MAX_CACHE_ENTRIES = 50  # Evict oldest entries beyond this to bound memory


def _find_last_block_boundary(text: str, start_offset: int = 0, start_in_fence: bool = False) -> tuple[int, bool]:
    """Find the character offset where the last complete markdown block ends.

    A block boundary is a blank line (two consecutive newlines) that is NOT
    inside a fenced code block.

    Args:
        text: Full text to scan
        start_offset: Character offset to start scanning from (optimization)
        start_in_fence: Whether we're inside a code fence at start_offset

    Returns:
        Tuple of (boundary_offset, in_code_fence_at_end).
        boundary_offset is 0 if no boundary found.
    """
    in_code_fence = start_in_fence
    last_boundary = start_offset if start_offset > 0 else 0

    # Split only the portion we need to scan
    scan_text = text[start_offset:]
    lines = scan_text.split('\n')
    offset = start_offset

    for i, line in enumerate(lines):
        offset += len(line) + 1  # +1 for the newline

        # Check for code fence toggle
        stripped = line.lstrip()
        if stripped.startswith('```'):
            in_code_fence = not in_code_fence
            continue

        # A blank line outside a code fence is a block boundary
        if not in_code_fence and line.strip() == '' and (start_offset > 0 or i > 0):
            last_boundary = offset

    return last_boundary, in_code_fence


def parse_markdown_incremental(
    text: str, bubble_id: str, is_append: bool = True
) -> list:
    """Parse markdown with incremental caching for streaming performance.

    During streaming appends, only the trailing (potentially incomplete)
    block is re-parsed. Stable prefix segments are served from cache.

    Args:
        text: Full markdown content of the bubble
        bubble_id: Unique bubble identifier for cache keying
        is_append: True if this is a streaming append (enables caching)

    Returns:
        List of segment dicts (same format as parse_markdown_to_segments)
    """
    if not text:
        _incremental_cache.pop(bubble_id, None)
        return []

    if not is_append:
        # Full set/clear - invalidate cache, do full parse
        _incremental_cache.pop(bubble_id, None)
        return parse_markdown_to_segments(text, streaming=False)

    # Check cache hit: if we have cached segments for a prefix of this text
    cached = _incremental_cache.get(bubble_id)
    if cached:
        cached_boundary, stable_segments, cached_prefix, cached_in_fence = cached
        # Cache valid if text starts with the same stable prefix
        if (cached_boundary > 0
                and len(text) >= cached_boundary
                and text[:cached_boundary] == cached_prefix):
            # Scan only NEW text (after cached boundary) for block boundaries
            new_boundary, in_fence = _find_last_block_boundary(
                text, start_offset=cached_boundary, start_in_fence=cached_in_fence
            )

            if new_boundary > cached_boundary:
                # New blocks completed — parse only the NEW stable region + tail
                new_stable_text = text[cached_boundary:new_boundary]
                new_stable_segs = parse_markdown_to_segments(new_stable_text, streaming=False)
                all_stable = stable_segments + new_stable_segs

                tail_text = text[new_boundary:]
                tail_segs = parse_markdown_to_segments(tail_text, streaming=True) if tail_text.strip() else []

                # Update cache with extended stable prefix
                _incremental_cache[bubble_id] = (
                    new_boundary, all_stable, text[:new_boundary], in_fence
                )
                return all_stable + tail_segs
            else:
                # No new blocks completed — reuse cached segments, re-parse only tail
                tail_text = text[cached_boundary:]
                tail_segs = parse_markdown_to_segments(tail_text, streaming=True) if tail_text.strip() else []
                return stable_segments + tail_segs

    # No usable cache - full parse
    segments = parse_markdown_to_segments(text, streaming=True)

    # Evict oldest entries if cache is full (prevent unbounded growth)
    if len(_incremental_cache) >= _MAX_CACHE_ENTRIES and bubble_id not in _incremental_cache:
        oldest_key = next(iter(_incremental_cache))
        del _incremental_cache[oldest_key]

    # Cache: find block boundary for stable prefix
    boundary, in_fence = _find_last_block_boundary(text)
    if boundary > 0:
        stable_text = text[:boundary]
        stable_segs = parse_markdown_to_segments(stable_text, streaming=False)
        _incremental_cache[bubble_id] = (boundary, stable_segs, stable_text, in_fence)
    else:
        _incremental_cache[bubble_id] = (0, [], "", False)

    return segments


def clear_incremental_cache(bubble_id: str = None) -> None:
    """Clear incremental parsing cache.

    Args:
        bubble_id: Clear cache for specific bubble, or all if None.
    """
    if bubble_id:
        _incremental_cache.pop(bubble_id, None)
    else:
        _incremental_cache.clear()


def segments_to_json(segments: list) -> str:
    """Convert segments list to JSON string for storage in metadata."""
    return json.dumps({'markdown_segments': segments}, ensure_ascii=False)


def parse_markdown_to_json(text: str, streaming: bool = False) -> str:
    """
    Parse markdown and return JSON string for metadata storage.

    Args:
        text: Markdown text to parse
        streaming: If True, handle incomplete markdown

    Returns:
        JSON string with markdown_segments array
    """
    segments = parse_markdown_to_segments(text, streaming)
    return segments_to_json(segments)


