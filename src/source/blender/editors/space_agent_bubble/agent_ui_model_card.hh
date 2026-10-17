/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The model card: what the island's model chip opens. A card drawn by hand
 * over the island window (no Blender popup, no stock widgets): source tabs
 * (Mixie | the user's key | Local), a caption, the picks of the open tab with
 * the current one checked, its thinking levels folded under it, a pinned
 * footer of settings actions and its own scrollbar.
 *
 * It is `MIXAR_OT_agent_model_card`, a modal operator on the island
 * window (the credits banner's pattern): a window draw callback paints the
 * card above every region, the modal handler owns clicks, wheel, keys and
 * click-away, and a 60 Hz timer eases the scroll, the tab pill and hovers.
 * Python decides what the rows are (byok/core/picker.py, mirrored on the
 * WindowManager by picker_mirror.py); a pick runs `MIXAR_OT_agent_pick`, a
 * footer `MIXAR_BYOK_OT_open_dialog`, and the card closes.
 */

#pragma once

namespace blender {

struct wmWindow;
struct rctf;

/** Where the chip is (window pixels) and the island's body text size, for
 * the card of \a win. Called by the chip's button pass every draw; an
 * unavailable chip closes an open card. */
void agent_model_card_anchor(const wmWindow *win, const rctf &chip, float text_size, bool available);

/** The card is open (the chip draws lit). */
bool agent_model_card_is_open();

/** `MIXAR_OT_agent_model_card` and the card's QA targets. */
void agent_model_card_register();

}  // namespace blender
