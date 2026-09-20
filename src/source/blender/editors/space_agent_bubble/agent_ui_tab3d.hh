/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * 3D tab for the Agent island: the moodboard Model Gen tab (consolidated
 * catalog-driven image-to-3D / text-to-3D) re-rendered as the island card's
 * content. Same properties, same operators, island pixels.
 */

#pragma once

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct bContext;
struct rctf;

/**
 * Paint the 3D generation composer into the card panel and lay its controls.
 *
 * \param panel: the card panel rect in REGION pixel coordinates (same space
 * as the island's uiBlocks — call OUTSIDE any custom GPU matrix translation;
 * the pane builds uiBlocks).
 * \param u: island unit scale (window_native_w / AGENT_ISLAND_W).
 *
 * Everything binds to the moodboard Model Gen tab's own state and operators:
 * `scene.mixie_moodboard_sidebar.tab_image_to_3d` (mode / model / prompt /
 * reference_image / use_selected_image), the schema param group the
 * generation_params engine registers on WindowManager for the selected
 * (service, model), and the footer operators from `_MODEL_GEN_FOOTER`
 * (`mixie.model_gen_generate`, `mixie.smart_segment_generate`). Params render
 * from the group's RNA — no hardcoded param names; when the catalog has not
 * loaded, only the prompt + Generate render.
 */
void agent_ui_tab3d_draw(const bContext *C, ARegion *region, const rctf &panel, float u);

}  // namespace blender
