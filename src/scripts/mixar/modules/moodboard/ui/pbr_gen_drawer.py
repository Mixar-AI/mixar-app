# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PBR Generation Tab Drawer — Tripo texture-model texturing.

Renders the PBR Generation sidebar tab from the generation catalog's
``pbr_generation`` capability (single service ``tripo_texture`` — the Mode
dropdown auto-hides). Textures the SELECTED untextured mesh: the mesh is
exported as GLB, optional guidance (prompt and/or reference images) is
attached, and the resulting textured GLB imports as a new object.

Catalog-only (like AI Render / Auto Rig): the panel's ``poll()`` hides the
tab when the loaded catalog has no ``pbr_generation`` services, so this
drawer can assume the catalog is loaded.

Guidance mirrors Tripo's mutually-exclusive ``texture_prompt``:
- ``multi_view`` OFF → one reference image (moodboard-selected or picked/
  uploaded), optionally style-only, plus the prompt.
- ``multi_view`` ON  → four positional views (front / left / back / right),
  all required, submitted together as Tripo ``images``.
"""

from mixar.modules.moodboard.constants import SEP_INTRA
from mixar.modules.common.job_queue.constants import FEATURE_PBR_GEN

from .sidebar_ui_helpers import (
    draw_section_box, draw_section_separator, draw_prompt_section,
    draw_moodboard_image_toggle, draw_generate_footer, draw_hint,
    draw_mesh_info, draw_toggle,
)

# Four positional views, in the ORDER the backend/Tripo expects
# (front, left, back, right — see TripoAdapter._build_texture_prompt).
_VIEW_SLOTS = (
    ("front_image", "Front"),
    ("left_image", "Left"),
    ("back_image", "Back"),
    ("right_image", "Right"),
)


def _draw_multi_view(box, tab):
    """Four positional view slots (each: pick existing OR upload)."""
    draw_hint(box, "All four views are used together", icon='INFO')
    missing = [label for prop, label in _VIEW_SLOTS
               if getattr(tab, prop, None) is None]
    grid = box.grid_flow(
        row_major=True, columns=2, even_columns=True, even_rows=False)
    for prop, label in _VIEW_SLOTS:
        col = grid.column()
        col.label(text=label)
        # template_ID gives browse-existing + open-new-file + unlink in one.
        col.template_ID(tab, prop, open="image.open")
    if missing:
        box.separator(factor=SEP_INTRA)
        draw_hint(box, f"Missing: {', '.join(missing)}", icon='ERROR')


def _draw_single_view(box, tab, context):
    """Single reference image (moodboard-selected or picked/uploaded)."""
    draw_toggle(box, tab, "style_only",
                text="Use image only as style reference")
    box.separator(factor=SEP_INTRA)
    draw_moodboard_image_toggle(box, tab, context)
    if not tab.use_selected_image:
        box.template_ID(tab, "reference_image", open="image.open")


def _draw_pbr_gen(layout, context):
    """Draw the catalog-driven PBR Generation tab."""
    scene = context.scene
    sidebar = getattr(scene, "mixie_moodboard_sidebar", None)
    tab = getattr(sidebar, "tab_pbr_gen", None) if sidebar else None
    if tab is None:
        draw_hint(layout, "PBR Generation tab not available", icon='ERROR')
        return

    from mixar.modules.common.generation_params import draw_capability_selector

    # --- Mesh info ---
    col = draw_section_box(layout, "Mesh Info", icon='MESH_DATA')
    draw_mesh_info(col, context, max_mb=150)
    draw_hint(col, "Select the untextured mesh to texture", icon='INFO')
    draw_section_separator(layout)

    # --- Prompt (optional text guidance) ---
    draw_prompt_section(layout, tab, label="Prompt (optional)")
    draw_section_separator(layout)

    # --- Reference images: single ⇄ multi-view ---
    box = draw_section_box(layout, "Reference Images", icon='IMAGE_DATA')
    draw_toggle(box, tab, "multi_view",
                text="Multiple Views (Front / Left / Back / Right)")
    box.separator(factor=SEP_INTRA)
    if tab.multi_view:
        _draw_multi_view(box, tab)
    else:
        _draw_single_view(box, tab, context)
    draw_section_separator(layout)

    # --- Settings (Model / schema params from the catalog) ---
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    col.use_property_split = True
    col.use_property_decorate = False
    draw_capability_selector(col, tab, "pbr_generation")

    # --- Generate ---
    draw_generate_footer(
        layout, context, "mixie.pbr_gen_generate", "pbr_gen",
        gen_flag_attr="mixie_pbr_gen_is_generating",
        feature_key=FEATURE_PBR_GEN,
    )
