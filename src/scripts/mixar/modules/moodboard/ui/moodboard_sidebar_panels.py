# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compatibility entry point for the retired Moodboard N-panel.

The standalone Moodboard editor has no right-sidebar panels, including before
login and after catalog refresh. Generation belongs to canvas nodes and the
Agent island. Shared drawer functions, scene properties and submit operators
remain available to those surfaces and existing scripts.

Keep these imports for callers that still resolve legacy category names. An
empty capability mapping also prevents catalog refresh from registering tabs.
"""

from .moodboard_tab_labels import (
    get_tab_category,
    init_capability_tabs as _init_capability_tabs,
    refresh_tab_labels,
)

_init_capability_tabs({})
classes = ()
