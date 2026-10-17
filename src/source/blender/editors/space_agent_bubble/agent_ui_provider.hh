/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The model chip, right of Auto on the composer's chip row: who answers the
 * agent (a badge: Mixie, the user's key's provider, Local) and which model,
 * always named. The whole chip opens the model card
 * (agent_ui_model_card.hh), where every row is a pick. Geometry is fitted in
 * #agent_provider_sizes (agent_ui_chip_fit.hh) and placed by
 * #agent_ui_layout_fit_controls; this file reads the Python half's
 * WindowManager mirrors (core/picker.py decides, this draws), paints the chip
 * and lays the native button over it.
 */

#pragma once

struct ARegion;
struct bContext;
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
 *  variable axis); the layout measures the chip words with it. */
float agent_ui_provider_text_width(const char *text, float size, int weight);

/** Read `wm.mixar_agent_*` into \a r_state. A build whose Python half has
 *  not registered them reads as "no picker". */
void agent_ui_provider_gather(wmWindowManager *wm, AgentIslandState *r_state);

/** Paint the chip. */
void agent_ui_draw_provider(ARegion *region,
                            const AgentIslandLayout *layout,
                            const AgentIslandState *state);

/** The native button over the painted chip (opens the model card,
 * agent_ui_model_card.hh) and the card's anchor. */
void agent_bubble_provider_buttons(const bContext *C,
                                   ui::Block *block,
                                   const ARegion *region,
                                   const AgentIslandLayout &layout,
                                   const AgentIslandState &state);

}  // namespace blender
