# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Apply shared canvas colors and remove per-viewport background overrides."""

from ..constants import FOREST_MOODBOARD_RGB, FOREST_VIEWPORT_RGB


def apply_forest_backgrounds(theme, screens):
    gradients = theme.view_3d.space.gradients
    gradients.background_type = 'SINGLE_COLOR'
    gradients.high_gradient = FOREST_VIEWPORT_RGB
    gradients.gradient = FOREST_VIEWPORT_RGB
    theme.mixie.space.back = FOREST_MOODBOARD_RGB

    use_theme_backgrounds(screens)


def use_theme_backgrounds(screens):
    """Honor the current theme without replacing its imported colors or gradient."""

    # Include inactive spaces: switching back to a saved viewport must agree too.
    for screen in screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.background_type = 'THEME'
                    # Material Preview otherwise composites the HDRI over the theme.
                    # This controls only its backdrop; HDRI lighting is unchanged.
                    space.shading.studiolight_background_alpha = 0.0
            area.tag_redraw()
