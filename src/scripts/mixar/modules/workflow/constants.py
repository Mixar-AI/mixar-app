# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Workflow module constants — dual-mode UI."""

# Workspace shipped in startup.mixar that holds the original "AI Mode"
# layout. In the new dual-mode design this is just a regular Engine
# workspace tab — the user can rename, edit, or delete it without
# breaking Zen Mode. Used as the seed template the first time we
# materialize the Zen Mode workspace.
AI_WORKSPACE_NAME = "AI Mode"

# Dedicated workspace backing the Zen UI mode. Created lazily by
# ensure_basic_workspace() on first activation — independent from
# AI_WORKSPACE_NAME so layout edits in one don't bleed into the other.
#
# Legacy users may still have the older "Basic Mode" workspace baked
# into their startup file; the C++ workspace-tab filter in
# ``interface_template_id.cc`` hides both names so the rename is
# visually transparent.
BASIC_WORKSPACE_NAME = "Zen Mode"

# Workspace to land on when the user flips into Engine mode. "Layout" is
# Blender's stock default first tab, so Engine mode opens where a Blender
# user expects (mirrors the startup.blend's default active workspace).
PRO_DEFAULT_WORKSPACE_NAME = "Layout"

# The only tools Zen Mode's left strip surfaces, in design order (top to
# bottom). Shared with the strip's toggle logic so the buttons and the
# "is this a transform tool?" test cannot drift apart.
ZEN_TRANSFORM_TOOL_IDS = ("builtin.move", "builtin.rotate", "builtin.scale")

# Deliberately small Zen quick-edit menu; full modifier authoring stays in Engine.
ZEN_MODIFIER_ITEMS = (
    ("BEVEL", "Bevel", "Round the mesh's edges"),
    ("SUBSURF", "Subdivision", "Smooth the mesh with subdivision"),
    ("MIRROR", "Mirror", "Mirror the mesh along an axis"),
)
ZEN_MODIFIER_TYPES = frozenset(item[0] for item in ZEN_MODIFIER_ITEMS)

ZEN_TEXTURE_CHANNELS = (
    ('Base Color', 'Base Color', 'Color texture (sRGB)'),
    ('Roughness', 'Roughness', 'Roughness texture (Non-Color)'),
    ('Metallic', 'Metallic', 'Metallic texture (Non-Color)'),
    ('Normal', 'Normal', 'Tangent-space normal texture (Non-Color; requires UVs)'),
)
ZEN_TEXTURE_ROLE = 'mixar_zen_texture_role'
