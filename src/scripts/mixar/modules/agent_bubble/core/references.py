# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Remove the captured reference from its owning generation input, by identity."""


def remove_reference(scene, image_name, source):
    sidebar = scene.mixie_moodboard_sidebar
    if source == 'BOARD':
        removed = False
        for item in scene.mixie_moodboard_images:
            if item.selected and item.image and item.image.name == image_name:
                item.selected = False
                removed = True
        return removed
    if source == 'MEDIA_UPLOAD':
        refs = sidebar.tab_imagegen.reference_images
        for index, item in enumerate(refs):
            if item.image and item.image.name == image_name:
                refs.remove(index)
                return True
        return False
    owner = {'MODEL_UPLOAD': 'tab_image_to_3d', 'SPLAT_UPLOAD': 'tab_world_labs'}.get(source)
    if owner:
        tab = getattr(sidebar, owner)
        if tab.reference_image and tab.reference_image.name == image_name:
            tab.reference_image = None
            return True
    return False
