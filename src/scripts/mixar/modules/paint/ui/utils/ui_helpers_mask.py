# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing helper functions for Mask settings.

This module serves as a coordinator that provides the main draw_mask_settings
function, using helper functions from submodules.

Submodules:
- ui_helpers_mask_utils: Utility functions for mask operations
- ui_helpers_mask_sections: Section drawing helper functions
"""

# Re-export utility functions
from .ui_helpers_mask_utils import get_mask_mapping_node, get_node_drawing_functions

# Import section drawing helpers
from .ui_helpers_mask_sections import (
    draw_mask_channel_toggles_inline,
    draw_mask_core_settings_content,
    draw_mask_modifiers_section,
    draw_mask_source_props_box,
    draw_mask_type_specific_props,
)


def draw_mask_settings(layout, mask, _mask_index, layer):
    """Draw comprehensive settings for a single mask.

    Clean consolidated UI:
    - Main box: Channels (inline), Source, Blend+Intensity, Source Input
    - Source Properties box (separate, always expanded)
    - Type-specific settings (separate box if applicable)
    - Modifiers section (collapsible)
    - Mapping/Transform handled separately via unified transform panel

    Args:
        layout: UI layout
        mask: YMask instance
        _mask_index: Index of mask in layer.masks (unused but kept for API compatibility)
        layer: YLayer instance (needed for context pointer and channel info)
    """
    if not mask.enable:
        # Show disabled state
        disabled_box = layout.box()
        disabled_box.label(text="Mask is disabled", icon='HIDE_ON')
        return

    # Use column for vertical stacking
    col = layout.column(align=False)

    # ========== MAIN SETTINGS BOX ==========
    main_box = col.box()
    main_col = main_box.column(align=True)

    # --- Channel Toggles (inline at top, no dropdown) ---
    if len(mask.channels) > 0:
        draw_mask_channel_toggles_inline(main_col, mask, layer)
        main_col.separator(factor=0.5)

    # --- Core Settings: Source, Blend+Intensity, Source Input ---
    draw_mask_core_settings_content(main_col, mask, layer)

    # ========== SOURCE PROPERTIES BOX (separate, always expanded) ==========
    draw_mask_source_props_box(col, mask)

    # ========== TYPE-SPECIFIC PROPERTIES ==========
    draw_mask_type_specific_props(col, mask)

    # ========== MODIFIERS ==========
    draw_mask_modifiers_section(col, mask, layer)


# Define __all__ for explicit exports
__all__ = [
    'draw_mask_settings',
    'get_mask_mapping_node',
    'get_node_drawing_functions',
]
