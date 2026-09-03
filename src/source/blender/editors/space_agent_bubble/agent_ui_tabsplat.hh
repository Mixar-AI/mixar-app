/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Gaussian Splat tab for the Agent island: the moodboard N-panel's World
 * Labs (world gen) surface, restyled to the island. Catalog-only — the pane
 * FAILS CLOSED (dim unavailable message, no controls) whenever the live
 * catalog does not publish an enabled `world_labs` model with valid
 * `mode`/`lod` schemas, exactly like `_draw_world_labs`.
 */

#pragma once

struct ARegion;
struct bContext;
struct rctf;

/**
 * Paint the World Labs pane and lay its controls into the card panel.
 *
 * \param panel: the card panel rect in REGION pixel coordinates (the same
 * space the island's uiBlocks use — call where the composer controls are
 * built, NOT inside a translated GPU matrix; the uiBlock captures matrices
 * at begin).
 * \param u: island unit scale (window_native_w / AGENT_ISLAND_W).
 *
 * State is read via RNA from `scene.mixie_moodboard_sidebar.tab_world_labs`
 * (model / prompt / use_selected_image / reference_image) and the
 * generation-params WindowManager group `mixar_genparams_world_labs__<slug>`
 * (`p_mode`, `p_lod`). Every action goes through EXISTING operators:
 * `mixie.world_labs_generate`, `mixie.world_labs_pick_image`,
 * `wm.context_set_enum` (mode / lod / model) and `wm.context_toggle`
 * (use_selected_image).
 */
void agent_ui_tabsplat_draw(const bContext *C,
                            ARegion *region,
                            const rctf &panel,
                            float u);
