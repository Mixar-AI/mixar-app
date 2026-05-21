# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Markdown preprocessor for Mixie Chat.

Converts markdown to clean, human-readable plain text for display.
Designed for real-time streaming - processes on every token.
"""

import re
from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def preprocess_markdown_to_text(text: str, streaming: bool = False) -> str:
    """
    Convert markdown to clean plain text for display.

    Transforms markdown syntax to human-readable format:
    - Headers: # Title → > Title, ## Title → >> Title
    - Code blocks: ``` → boxed format with language label and line numbers
    - Bold/italic: **text** → text, *text* → text
    - Links: [text](url) → text (url)
    - Lists: - item → • item
    - Inline code: `code` → code
    - Horizontal rules: --- → (removed)

    Args:
        text: Raw markdown text
        streaming: If True, handle incomplete markdown gracefully

    Returns:
        Human-readable plain text
    """
    if not text:
        return ""

    result = text

    # Process code blocks first (before other transformations)
    result = _process_code_blocks(result, streaming)

    # Process headers
    result = _process_headers(result)

    # Process inline formatting
    result = _process_inline_formatting(result)

    # Process links
    result = _process_links(result)

    # Process lists
    result = _process_lists(result)

    # Process horizontal rules
    result = _process_horizontal_rules(result)

    # Clean up extra blank lines
    result = _clean_blank_lines(result)

    return result


def _process_code_blocks(text: str, streaming: bool = False) -> str:
    """
    Process code blocks to boxed format with language label and line numbers.

    Input:
        ```python
        def hello():
            print("Hi")
        ```

    Output:
        [Python]
         1: def hello():
         2:     print("Hi")
    """
    # Pattern for complete code blocks
    code_block_pattern = re.compile(
        r'^```(\w*)\n(.*?)^```',
        re.MULTILINE | re.DOTALL
    )

    def format_code_block(match):
        lang = match.group(1).strip()
        code = match.group(2).rstrip('\n')

        lines = code.split('\n')
        # Calculate width for line numbers
        width = len(str(len(lines)))

        formatted_lines = []
        # Add language label if present
        if lang:
            formatted_lines.append(f"[{lang.capitalize()}]")

        for i, line in enumerate(lines, 1):
            formatted_lines.append(f"{i:>{width}}: {line}")

        return '\n'.join(formatted_lines)

    result = code_block_pattern.sub(format_code_block, text)

    # Handle unclosed code blocks during streaming
    if streaming:
        # Check for unclosed code block (odd number of fences)
        fence_count = len(re.findall(r'^```', result, re.MULTILINE))
        if fence_count % 2 == 1:
            # Find the last unclosed fence
            unclosed_match = re.search(
                r'^```(\w*)\n?([\s\S]*)$',
                result,
                re.MULTILINE
            )

            if unclosed_match:
                # Get everything before the unclosed fence
                fence_start = unclosed_match.start()
                prefix = result[:fence_start]

                lang = unclosed_match.group(1).strip()
                code = unclosed_match.group(2).rstrip('\n')

                formatted_lines = []
                if lang:
                    formatted_lines.append(f"[{lang.capitalize()}]")
                else:
                    formatted_lines.append("[Code]")

                if code:
                    lines = code.split('\n')
                    width = len(str(len(lines)))
                    for i, line in enumerate(lines, 1):
                        formatted_lines.append(f"{i:>{width}}: {line}")

                # Add indicator for incomplete block
                formatted_lines.append("...")

                result = prefix + '\n'.join(formatted_lines)

    return result


def _process_headers(text: str) -> str:
    """
    Process headers to Unicode symbol prefix format.

    # Title → ■ Title
    ## Title → ▸ Title
    ### Title → • Title
    #### Title → ◦ Title
    ##### Title → - Title
    ###### Title → - Title
    """
    # Unicode symbols for header levels (visual hierarchy)
    header_symbols = {
        1: '■',  # Black square - primary headers
        2: '▸',  # Black right-pointing triangle - secondary
        3: '•',  # Bullet - tertiary
        4: '◦',  # White bullet - quaternary
        5: '-',  # Dash - minor
        6: '-',  # Dash - minor
    }

    lines = text.split('\n')
    result_lines = []

    for line in lines:
        # Match header at start of line
        header_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if header_match:
            level = len(header_match.group(1))
            title = header_match.group(2)
            symbol = header_symbols.get(level, '-')
            result_lines.append(f"{symbol} {title}")
        else:
            result_lines.append(line)

    return '\n'.join(result_lines)


def _process_inline_formatting(text: str) -> str:
    """
    Remove inline formatting markers.

    **bold** → bold
    __bold__ → bold
    *italic* → italic
    _italic_ → italic
    ***both*** → both
    `code` → code
    ~~strikethrough~~ → strikethrough
    """
    result = text

    # Bold + italic (must process before bold/italic separately)
    result = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', result)
    result = re.sub(r'___(.+?)___', r'\1', result)

    # Bold
    result = re.sub(r'\*\*(.+?)\*\*', r'\1', result)
    result = re.sub(r'__(.+?)__', r'\1', result)

    # Italic
    result = re.sub(r'\*(.+?)\*', r'\1', result)
    result = re.sub(r'_(.+?)_', r'\1', result)

    # Inline code
    result = re.sub(r'`([^`]+)`', r'\1', result)

    # Strikethrough
    result = re.sub(r'~~(.+?)~~', r'\1', result)

    return result


def _process_links(text: str) -> str:
    """
    Process links to readable format.

    [text](url) → text (url)
    [text](url "title") → text (url)
    ![alt](url) → [Image: alt]
    """
    # Images
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'[Image: \1]', text)

    # Links with optional title
    text = re.sub(r'\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)', r'\1 (\2)', text)

    return text


def _process_lists(text: str) -> str:
    """
    Process lists to bullet format.

    - item → • item
    * item → • item
    + item → • item
    1. item → 1. item (keep numbered lists as-is)
    """
    lines = text.split('\n')
    result_lines = []

    for line in lines:
        # Unordered list items (preserve indentation)
        unordered_match = re.match(r'^(\s*)[-*+]\s+(.+)$', line)
        if unordered_match:
            indent = unordered_match.group(1)
            content = unordered_match.group(2)
            result_lines.append(f"{indent}\u2022 {content}")
        else:
            result_lines.append(line)

    return '\n'.join(result_lines)


def _process_horizontal_rules(text: str) -> str:
    """
    Remove horizontal rules.

    --- → (empty line)
    *** → (empty line)
    ___ → (empty line)
    """
    # Match horizontal rules (3+ of same character)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    return text


def _clean_blank_lines(text: str) -> str:
    """
    Clean up excessive blank lines.

    Reduce multiple consecutive blank lines to at most two.
    """
    # Replace 3+ consecutive newlines with 2
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text
