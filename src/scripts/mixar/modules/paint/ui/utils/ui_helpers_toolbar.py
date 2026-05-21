# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer toolbar UI drawing helpers."""


def draw_top_toolbar(context, layout):
    """Substance 3D Painter-style layer creation toolbar.

    Draws a compact toolbar with essential layer operations:
    - Fill Layer (uniform color fill)
    - Paint Layer (image-based)
    - Smart Material (procedural materials library)
    - Patterns (procedural textures)
    - Folder (layer groups)
    - Delete

    Args:
        context: Blender context containing active object and scene data.
        layout: Blender UI layout to draw the toolbar into.
    """
    from ...core.node.node_utils import get_active_mpaint_node

    # Check if layers exist (for enabling/disabling buttons)
    node = get_active_mpaint_node()
    has_layers = node and node.node_tree and len(node.node_tree.mp.layers) > 0

    # Main toolbar row
    toolbar = layout.row(align=True)
    toolbar.scale_x = 1.4
    toolbar.scale_y = 1.4

    # === 1. FILL LAYER (uniform color fill) ===
    toolbar.operator("wm.m_new_fill_layer", text="", icon='COLOR')
    toolbar.separator(factor=0.3)

    # === 2. PAINT LAYER (image-based) ===
    toolbar.operator("wm.m_new_paint_layer", text="", icon='BRUSHES_ALL')
    toolbar.separator(factor=0.3)

    # === 2b. OPEN IMAGES AS LAYER (import multiple textures) ===
    toolbar.operator("layers.open_images_to_layer", text="", icon='FILE_IMAGE')
    toolbar.separator(factor=0.3)

    # === 3. SMART MATERIAL (procedural materials library) ===
    toolbar.operator("layers.procedural_material_library_popup", text="", icon='NODE_MATERIAL')
    toolbar.separator(factor=0.3)

    # === 4. PATTERNS (procedural textures menu) ===
    # toolbar.menu("LAYERS_MT_procedural_layer_menu", text="", icon='TEXTURE')
    # toolbar.separator(factor=0.3)

    # === 5. MASK (add mask to active layer) ===
    mask_row = toolbar.row(align=True)
    mask_row.menu("MASKS_MT_add_mask_menu", text="", icon='MOD_MASK')
    mask_row.enabled = has_layers
    toolbar.separator(factor=0.3)

    # === 6. FOLDER (layer group) ===
    # toolbar.operator("layers.add_layer_group", text="", icon='FILE_FOLDER')

    # Separator between creation and edit operations
    toolbar.separator(factor=2.0)

    # === 7. COPY LAYER ===
    copy_row = toolbar.row(align=True)
    copy_row.operator("wm.m_copy_layer", text="", icon='COPYDOWN')
    copy_row.enabled = has_layers
    toolbar.separator(factor=0.3)

    # === 8. PASTE LAYER ===
    paste_row = toolbar.row(align=True)
    paste_row.operator("wm.m_paste_layer", text="", icon='PASTEDOWN')
    # Paste enabled based on poll (clipboard content)
    toolbar.separator(factor=0.3)

    # === 9. DELETE ===
    del_row = toolbar.row(align=True)
    del_row.operator("layers.remove_active_layer", text="", icon='TRASH')
    del_row.enabled = has_layers
