# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image editor space related utility functions.

This module contains functions for interacting with Blender's image editor spaces,
including finding unpinned editors and retrieving images from them.
"""


def get_edit_image_editor_space(context):
    """
    Get the image editor space used for editing.

    Retrieves the image editor area/space based on stored indices in the MPaint
    window manager properties.

    Parameters:
        context: Blender context

    Returns:
        Space: Image editor space if found and valid, None otherwise
    """
    ypwm = context.window_manager.mpprops
    area_index = ypwm.edit_image_editor_area_index
    window_index = ypwm.edit_image_editor_window_index
    if window_index >= 0 and window_index < len(context.window_manager.windows):
        window = context.window_manager.windows[window_index]
        if area_index >= 0 and area_index < len(window.screen.areas):
            area = window.screen.areas[area_index]
            if area.type == 'IMAGE_EDITOR' and area.spaces[0].mode == 'UV':
                return area.spaces[0]

    return None


def get_first_unpinned_image_editor_space(context, return_index=False, uv_edit=False):
    """
    Get the first unpinned image editor space.

    Searches through all windows and areas to find the first unpinned image editor
    that is not displaying a render result or compositing image.

    Parameters:
        context: Blender context
        return_index (bool): If True, return space along with window and area indices.
                           Default is False.
        uv_edit (bool): If True, only return image editors in UV editing mode.
                       Default is False.

    Returns:
        Space: Image editor space if return_index is False
        tuple: (space, window_index, area_index) if return_index is True
    """
    space = None
    area_index = -1
    window_index = -1
    for i, window in enumerate(context.window_manager.windows):
        for j, area in enumerate(window.screen.areas):
            if area.type == 'IMAGE_EDITOR':
                if not uv_edit or area.spaces[0].mode == 'UV':
                    img = area.spaces[0].image
                    if not area.spaces[0].use_image_pin and (not img or img.type not in {'RENDER_RESULT', 'COMPOSITING'}):
                        space = area.spaces[0]
                        window_index = i
                        area_index = j
                        break

    if return_index:
        return space, window_index, area_index

    return space


def get_first_image_editor_image(context):
    """
    Get the image from the first unpinned image editor.

    Parameters:
        context: Blender context

    Returns:
        Image: The image displayed in the first unpinned image editor, or None if no space found
    """
    space = get_first_unpinned_image_editor_space(context)
    if space:
        return space.image
    return None
