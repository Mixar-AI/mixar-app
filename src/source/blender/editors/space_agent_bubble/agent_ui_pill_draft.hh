/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once

#include "agent_ui_draw.hh"

namespace blender {
/** Paint the Sketch pill's content between \a left and \a right (the cat
 *  chip's gap): the Voice button when Voice exists, the title line (with the
 *  live ECG while capturing) and the draft with its blinking caret. \a u is
 *  the pill's artboard unit. */
void agent_ui_draw_pill_draft(const AgentIslandState &state,
                              float left,
                              float right,
                              float height,
                              float font_size,
                              float u);
/** Seconds until the Sketch pill next needs a frame: the caret's next blink
 *  edge, or the ECG cadence while capturing. Infinity when not painted. */
double agent_ui_pill_draft_next_frame();
/** True when pill-window pixel (\a x, \a y) is on the painted Voice button. */
bool agent_ui_pill_voice_hit(int x, int y);
void agent_ui_pill_draft_clear();
void agent_ui_pill_draft_qa_register();
}  // namespace blender
