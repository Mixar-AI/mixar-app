/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The Voice button on the minimised Sketch pill.
 *
 * The pill has no uiBlock: a press on it is one gesture, decided by how it
 * ends (agent_bubble/ui/operators/bubble_header_drag_op.py). On a click the
 * gesture asks this operator first. It claims the click only when it lands on
 * the painted button (agent_ui_pill_draft.cc owns that rectangle), so every
 * other click still restores the island and a drag still moves the pill.
 */

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"
#include "ED_space_api.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_bubble_intern.hh"
#include "agent_ui_pill_draft.hh"

namespace blender {

static bool pill_voice_poll(bContext *C)
{
  return ED_agent_bubble_is_resting_pill(C);
}

static wmOperatorStatus pill_voice_invoke(bContext *C, wmOperator * /*op*/, const wmEvent *event)
{
  if (event == nullptr || !agent_ui_pill_voice_hit(event->xy[0], event->xy[1])) {
    return OPERATOR_CANCELLED;
  }
  /* The one toggle every Voice surface binds; the event carries Shift-to-cancel. */
  WM_operator_name_call(
      C, "MIXIE_CHAT_OT_voice_toggle", wm::OpCallContext::InvokeDefault, nullptr, event);
  /* Typing over the frozen viewport carries on: the keyboard goes back to the host. */
  agent_bubble_return_key_to_host();
  if (ScrArea *area = CTX_wm_area(C)) {
    ED_area_tag_redraw(area);
  }
  return OPERATOR_FINISHED;
}

void MIXAR_OT_bubble_pill_voice(wmOperatorType *ot)
{
  ot->name = "Voice";
  ot->idname = "MIXAR_OT_bubble_pill_voice";
  ot->description = "Start or stop dictating into the sketch draft";
  ot->invoke = pill_voice_invoke;
  ot->poll = pill_voice_poll;
  ot->flag = OPTYPE_INTERNAL;
}

}  // namespace blender
