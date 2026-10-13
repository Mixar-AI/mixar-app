/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Who answers the agent, right of Auto on the composer's chip row: the
 * Mixie | Custom AI toggle and, while the user's own key is in use, the key
 * chip naming its provider and model, whose model pill switches the model in
 * place (`MIXAR_BYOK_MT_key_model` -> `mixar_byok.switch_model`, no dialog).
 * Geometry is fitted in #agent_provider_sizes (agent_ui_chip_fit.hh) and
 * placed by #agent_ui_layout_fit_controls; this file reads the Python half's
 * WindowManager mirrors, paints both controls and lays the native buttons
 * over them.
 */

#pragma once

struct ARegion;
struct wmWindowManager;

namespace blender {

namespace ui {
struct Block;
}

struct AgentIslandLayout;
struct AgentIslandState;

/** The frames' chevron: an equilateral triangle pointing down with softly
 *  rounded corners, \a w x \a h, filled, centred on (cx, cy). */
void agent_ui_chevron_fill_draw(float cx, float cy, float w, float h, const float col[4]);

/** Width of \a text at \a size in the island face at \a weight (Manrope's
 *  variable axis); the layout measures the provider words with it. */
float agent_ui_provider_text_width(const char *text, float size, int weight);

/** Read `wm.mixar_agent_model_*` / `wm.mixar_agent_key_*` into \a r_state.
 *  A build whose Python half has not registered them reads as "no picker". */
void agent_ui_provider_gather(wmWindowManager *wm, AgentIslandState *r_state);

/** Paint the toggle and the key chip. */
void agent_ui_draw_provider(ARegion *region,
                            const AgentIslandLayout *layout,
                            const AgentIslandState *state);

/** The native buttons over the painted toggle and key chip. */
void agent_bubble_provider_buttons(ui::Block *block,
                                   const ARegion *region,
                                   const AgentIslandLayout &layout,
                                   const AgentIslandState &state);

}  // namespace blender
