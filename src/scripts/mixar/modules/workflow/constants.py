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

# Workspace to land on when the user flips into Engine mode for the
# first time.
PRO_DEFAULT_WORKSPACE_NAME = "Modeling"
