/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The engine chip, right of the model chip on the composer's chip row: which
 * game engine the agent builds in, at a glance. A status dot (green: an
 * editor with Mixar Link is connected; grey: none; amber: connecting; red: the
 * last connect failed) and the engine and project ("Godot · Ruins"), or
 * "Connect engine". The whole chip opens the engine card (the model card's
 * painter fed by the engine mirror, agent_ui_model_card.hh), where the user
 * switches editors or runs the one-click connect. Python decides
 * (space_mixie_chat/core/engine_connect.py, mirrored on the WindowManager by
 * ui/properties/engine_chip_props.py); this file reads the mirror, paints and
 * lays the native button over the chip.
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

/** Read `wm.mixar_engine_*` into \a r_state; no mirror reads as no chip. */
void agent_ui_engine_gather(wmWindowManager *wm, AgentIslandState *r_state);

/** Paint the chip. */
void agent_ui_draw_engine(ARegion *region, const AgentIslandLayout *layout, const AgentIslandState *state);

/** The native button over the painted chip (opens the engine card) and the
 *  card's anchor. */
void agent_bubble_engine_buttons(const bContext *C,
                                 ui::Block *block,
                                 const ARegion *region,
                                 const AgentIslandLayout &layout,
                                 const AgentIslandState &state);

}  // namespace blender
