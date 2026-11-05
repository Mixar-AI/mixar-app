# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pre-processor for AI-generated material scripts.

Fixes common mistakes before the script is exec'd in Blender:
- RGB 3-tuples to RGBA 4-tuples for color sockets
- Indexed socket assignments to _safe_set_default_value() calls
"""
import re

_FLOAT = r'-?[\d]+\.?[\d]*(?:e[+-]?\d+)?'
_THREE_TUPLE = rf'\(\s*({_FLOAT})\s*,\s*({_FLOAT})\s*,\s*({_FLOAT})\s*\)'
# Negative lookahead: not already a 4-component tuple
_NOT_FOUR = rf'(?!\s*,\s*{_FLOAT}\s*\))'

# Patterns that indicate a COLOR socket (not a Vector/XYZ socket)
_COLOR_PATTERNS = re.compile(
    rf'('
    # e.g.  BASE_COLOR = (r, g, b)  /  COLOR_DARK = (...)
    rf'(?:BASE_COLOR|COLOR_\w+|EMISSION_COLOR|TINT\w*)\s*='
    rf'|'
    # e.g.  base_color=(r, g, b)  in function signatures
    rf'\b(?:base_color|emission_color|color\w*)\s*='
    rf'|'
    # e.g.  inputs[Base Color].default_value = (r, g, b)
    rf"['\"].*?[Cc]olor.*?['\"]\]\.default_value\s*="
    rf'|'
    # e.g.  NodeSocketColor  ...  .default_value = (r, g, b)
    rf"NodeSocketColor.*?\.default_value\s*="
    rf')',
    re.DOTALL,
)

# Matches indexed node input assignments: SomeNode.inputs[N].default_value = (r, g, b)
_INDEXED_INPUT_RE = re.compile(
    r'(\w+\.inputs\[\d+\])\.default_value\s*=\s*(' + _THREE_TUPLE + _NOT_FOUR + r')'
)

# Matches socket_type='SomeType' declarations (module-level to avoid recompile per call)
_SOCKET_TYPE_RE = re.compile(r"socket_type\s*=\s*['\"](\w+)['\"]")


def _fix_rgb_to_rgba(script: str) -> str:
    """Auto-fix 3-component RGB color tuples to RGBA in generated material scripts.

    Targets color-named variables and NodeSocketColor default_value assignments.
    Handles both single-line and two-line patterns:
      - Single: inputs[Base Color].default_value = (r, g, b)
      - Two-line: new_socket(..., socket_type=NodeSocketColor)  line N
                  _s.default_value = (r, g, b)                    line N+1
    Does NOT touch Vector (XYZ) sockets which legitimately use 3-tuples.

    For indexed inputs (node.inputs[N].default_value), transforms to
    _safe_set_default_value() calls for runtime Color vs Vector disambiguation.
    """
    def _replacer(m):
        full = m.group(0)
        return full[:-1] + ', 1.0)'

    script = _INDEXED_INPUT_RE.sub(r'_safe_set_default_value(\1, \2)', script)

    lines = script.split('\n')
    fixed_lines = []
    pending_color_fix = False

    for line in lines:
        type_match = _SOCKET_TYPE_RE.search(line)
        if type_match:
            pending_color_fix = (type_match.group(1) == 'NodeSocketColor')

        is_color_line = re.search(r'(?:color|Color|COLOR)', line) and '=' in line
        is_pending_default = pending_color_fix and 'default_value' in line and '=' in line

        if is_color_line or is_pending_default:
            line = re.sub(_THREE_TUPLE + _NOT_FOUR, _replacer, line)

        if pending_color_fix and 'default_value' in line:
            pending_color_fix = False

        fixed_lines.append(line)
    return '\n'.join(fixed_lines)


def _safe_set_default_value(socket, val):
    """Set socket.default_value, auto-promoting RGB to RGBA for Color sockets.

    Injected into exec_globals so generated scripts can call it without import.
    Tries the original value first (preserving correct Vector/float assignments),
    then retries with alpha=1.0 if Blender raises ValueError.
    """
    if not isinstance(val, (tuple, list)) or len(val) != 3:
        socket.default_value = val
        return
    try:
        socket.default_value = val
    except (ValueError, TypeError):
        try:
            socket.default_value = (*val, 1.0)
        except Exception:
            pass
