/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The model card: data, the open tab's list, input and the operator. See
 * agent_ui_model_card.hh. Paint is agent_ui_model_card_draw.cc, layout
 * agent_ui_model_card_layout.cc, QA targets agent_ui_model_card_qa.cc.
 *
 * Input, while open (a blocking modal operator on the island window):
 * - a press on a pick runs it on release; the current pick's "Thinking: …"
 *   unfolds its levels in place; a footer opens AI Provider Settings;
 * - wheel / trackpad scroll the list (eased), the thumb drags, the track pages;
 * - Up / Down move a keyboard focus over the picks, Enter runs it,
 *   Left / Right / Tab switch tabs, Esc closes;
 * - a press outside closes the card and still reaches what it was on,
 *   except the chip itself (it would only open the card again).
 */

#include <algorithm>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_time.h"

#include "BLT_translation.hh"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "UI_mixar_motion.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_ui_model_card.hh"
#include "agent_ui_model_card_intern.hh"

namespace blender {

namespace agent_model_card {

State *g_state = nullptr;

namespace {

struct Anchor {
  const wmWindow *win = nullptr;
  rctf chip = {};
  float text_size = 0.0f;
  bool valid = false;
};
Anchor g_anchor;

constexpr const char *PICK_OP = "MIXAR_OT_agent_pick";
constexpr const char *SETTINGS_OP = "MIXAR_BYOK_OT_open_dialog";

void request_redraw(wmWindow *win)
{
  if (win) {
    if (bScreen *screen = WM_window_get_active_screen(win)) {
      screen->do_draw = true;
    }
  }
}


void set_tab(State &state, const int index)
{
  if (index < 0 || index >= int(state.tabs.size()) || !state.tabs[index].enabled ||
      state.tabs[index].id == state.tab)
  {
    return;
  }
  state.tab = state.tabs[index].id;
  state.thinking_open = false;
  state.scroll = state.scroll_target = 0.0f;
  rebuild_lines(state);
  reveal_current(state);
  request_redraw(state.win);
}

void teardown(bContext *C, wmOperator *op)
{
  State *state = static_cast<State *>(op->customdata);
  if (!state) {
    return;
  }
  if (state->timer) {
    WM_event_timer_remove(CTX_wm_manager(C), state->win, state->timer);
  }
  if (state->win && state->draw_handle) {
    WM_draw_cb_exit(state->win, state->draw_handle);
    WM_cursor_set(state->win, WM_CURSOR_DEFAULT);
    request_redraw(state->win);
  }
  if (g_state == state) {
    g_state = nullptr;
  }
  MEM_delete(state);
  op->customdata = nullptr;
}

/** Run a pick (close first: the operator may open a dialog). */
wmOperatorStatus run_pick(bContext *C, wmOperator *op, const Row row)
{
  teardown(C, op);
  wmOperatorType *ot = WM_operatortype_find(PICK_OP, true);
  if (ot) {
    PointerRNA props = WM_operator_properties_create_ptr(ot);
    RNA_enum_set_identifier(C, &props, "source", row.tab.c_str());
    RNA_string_set(&props, "provider", row.provider.c_str());
    RNA_string_set(&props, "model", row.model.c_str());
    RNA_string_set(&props, "thinking", row.thinking.c_str());
    WM_operator_name_call_ptr(C, ot, wm::OpCallContext::InvokeDefault, &props, nullptr);
    WM_operator_properties_free(&props);
  }
  return OPERATOR_FINISHED;
}

wmOperatorStatus run_footer(bContext *C, wmOperator *op)
{
  teardown(C, op);
  WM_operator_name_call(C, SETTINGS_OP, wm::OpCallContext::InvokeDefault, nullptr, nullptr);
  return OPERATOR_FINISHED;
}

wmOperatorStatus card_invoke(bContext *C, wmOperator *op, const wmEvent * /*event*/)
{
  wmWindow *win = CTX_wm_window(C);
  if (g_state || !win || !g_anchor.valid || g_anchor.win != win) {
    return OPERATOR_CANCELLED;
  }
  State *state = MEM_new<State>("agent_model_card");
  state->win = win;
  state->opened_at = BLI_time_now_seconds();
  state->anchor = g_anchor.chip;
  state->anchor_valid = true;
  state->text_size = g_anchor.text_size;
  refresh(C, *state, true);
  reveal_current(*state);
  state->pill = float(std::max(0, tab_index(*state, state->tab)));
  state->draw_handle = WM_draw_cb_activate(win, draw, state);
  state->timer = WM_event_timer_add(CTX_wm_manager(C), win, TIMER, 1.0 / 60.0);
  op->customdata = state;
  g_state = state;
  WM_event_add_modal_handler(C, op);
  request_redraw(win);
  return OPERATOR_RUNNING_MODAL;
}

wmOperatorStatus card_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  State *state = static_cast<State *>(op->customdata);
  if (!state) {
    return OPERATOR_CANCELLED;
  }
  /* Still open, and the event reaches the regions below (the composer's
   * buttons must keep their hover, or a click-away press finds no active
   * button). RUNNING_MODAL | PASS would not: the window counts that pair as
   * handled and skips every region (wm_event_do_handlers). */
  constexpr wmOperatorStatus PASS = OPERATOR_PASS_THROUGH;
  /* Closed, and the event still reaches what it was on. FINISHED | PASS
   * would not: the window manager counts that pair as handled and stops
   * before the regions (wm_handler_operator_call). */
  constexpr wmOperatorStatus CLOSE_PASS = wmOperatorStatus(OPERATOR_CANCELLED |
                                                           OPERATOR_PASS_THROUGH);
  if (event->type == TIMER) {
    if (event->customdata != state->timer) {
      return OPERATOR_PASS_THROUGH;
    }
    /* The chip went away (the island folded, the row dropped it): close. */
    if (!g_anchor.valid || g_anchor.win != state->win) {
      teardown(C, op);
      return OPERATOR_FINISHED;
    }
    state->anchor = g_anchor.chip;
    state->text_size = g_anchor.text_size;
    refresh(C, *state, false);
    step_motion(*state);
    request_redraw(state->win);
    return OPERATOR_RUNNING_MODAL;
  }
  if (event->type == WINDEACTIVATE) {
    teardown(C, op);
    return CLOSE_PASS;
  }

  if (ISKEYBOARD(event->type)) {
    if (event->val != KM_PRESS) {
      return PASS;
    }
    switch (event->type) {
      case EVT_ESCKEY:
        teardown(C, op);
        return OPERATOR_FINISHED;
      case EVT_UPARROWKEY:
        move_focus(*state, -1);
        break;
      case EVT_DOWNARROWKEY:
        move_focus(*state, 1);
        break;
      case EVT_LEFTARROWKEY:
        set_tab(*state, tab_index(*state, state->tab) - 1);
        break;
      case EVT_RIGHTARROWKEY:
        set_tab(*state, tab_index(*state, state->tab) + 1);
        break;
      case EVT_TABKEY: {
        const int n = int(state->tabs.size());
        if (n > 0) {
          const int step = (event->modifier & KM_SHIFT) ? n - 1 : 1;
          set_tab(*state, (tab_index(*state, state->tab) + step) % n);
        }
        break;
      }
      case EVT_RETKEY:
      case EVT_PADENTER:
        if (pickable(*state, state->focus)) {
          return run_pick(C, op, state->rows[state->lines[state->focus].row]);
        }
        break;
      default:
        return PASS; /* Typing still reaches the composer. */
    }
    request_redraw(state->win);
    return OPERATOR_RUNNING_MODAL;
  }

  const float mx = float(event->xy[0]);
  const float my = float(event->xy[1]);
  const Layout layout = layout_compute(*state);
  const Hit hit = hit_test(*state, layout, mx, my);

  if (ELEM(event->type, MOUSEMOVE, INBETWEEN_MOUSEMOVE)) {
    if (state->dragging_bar) {
      drag_bar(*state, layout, my);
      request_redraw(state->win);
      return OPERATOR_RUNNING_MODAL;
    }
    state->hover = hit.line;
    state->hover_tab = hit.tab;
    state->hover_footer = hit.footer;
    state->hover_trailing = hit.trailing;
    state->hover_bar = hit.thumb || hit.track;
    if (hit.line >= 0) {
      state->focus = -1;
    }
    const bool clickable = (hit.line >= 0 && pickable(*state, hit.line)) || hit.trailing ||
                           hit.footer >= 0 ||
                           (hit.tab >= 0 && state->tabs[hit.tab].enabled &&
                            state->tabs[hit.tab].id != state->tab);
    WM_cursor_set(state->win, clickable ? WM_CURSOR_HAND : WM_CURSOR_DEFAULT);
    return hit.inside ? OPERATOR_RUNNING_MODAL : PASS;
  }

  if (ISMOUSE_WHEEL(event->type) || event->type == MOUSEPAN) {
    if (!hit.inside) {
      return PASS;
    }
    const Metrics m = metrics(*state);
    float delta = 0.0f;
    if (event->type == WHEELUPMOUSE) {
      delta = -m.row_h * 1.5f;
    }
    else if (event->type == WHEELDOWNMOUSE) {
      delta = m.row_h * 1.5f;
    }
    else if (event->type == MOUSEPAN) {
      delta = float(WM_event_absolute_delta_y(event));
    }
    state->scroll_target = std::clamp(state->scroll_target + delta, 0.0f, layout.max_scroll);
    if (event->type == MOUSEPAN) {
      state->scroll = state->scroll_target; /* A trackpad is already smooth. */
    }
    request_redraw(state->win);
    return OPERATOR_RUNNING_MODAL;
  }

  if (event->type == LEFTMOUSE) {
    if (event->val == KM_PRESS) {
      if (hit.chip) {
        teardown(C, op);
        return OPERATOR_FINISHED; /* The chip toggles: do not reopen. */
      }
      if (!hit.inside) {
        teardown(C, op);
        return CLOSE_PASS;
      }
      if (hit.thumb) {
        state->dragging_bar = true;
        state->drag_grab = layout.bar_thumb.ymax - my;
      }
      else if (hit.track) {
        const float page = BLI_rctf_size_y(&layout.list) * 0.9f;
        state->scroll_target = std::clamp(
            state->scroll_target + (my < layout.bar_thumb.ymin ? page : -page),
            0.0f, layout.max_scroll);
      }
      else if (hit.tab >= 0) {
        set_tab(*state, hit.tab);
      }
      else {
        state->pressed = hit.footer >= 0 ? -2 - hit.footer : hit.line;
      }
      request_redraw(state->win);
      return OPERATOR_RUNNING_MODAL;
    }
    if (event->val == KM_RELEASE) {
      state->dragging_bar = false;
      const int pressed = state->pressed;
      state->pressed = -1;
      if (pressed <= -2 && hit.footer == -2 - pressed) {
        return run_footer(C, op);
      }
      if (pressed >= 0 && pressed == hit.line) {
        if (hit.trailing && state->lines[pressed].disclosure) {
          state->thinking_open = !state->thinking_open;
          rebuild_lines(*state);
          scroll_into_view(*state, int(state->lines.size()) > pressed ? pressed : 0);
        }
        else if (pickable(*state, pressed)) {
          return run_pick(C, op, state->rows[state->lines[pressed].row]);
        }
      }
      request_redraw(state->win);
      return hit.inside ? OPERATOR_RUNNING_MODAL : PASS;
    }
  }
  if (ISMOUSE_BUTTON(event->type) && event->val == KM_PRESS && !hit.inside) {
    teardown(C, op);
    return CLOSE_PASS;
  }
  return hit.inside ? OPERATOR_RUNNING_MODAL : PASS;
}

void card_cancel(bContext *C, wmOperator *op)
{
  teardown(C, op);
}

void MIXAR_OT_agent_model_card(wmOperatorType *ot)
{
  ot->name = "Agent Model";
  ot->idname = "MIXAR_OT_agent_model_card";
  ot->description = "Who answers the agent and which model";
  ot->invoke = card_invoke;
  ot->modal = card_modal;
  ot->cancel = card_cancel;
  ot->flag = OPTYPE_INTERNAL | OPTYPE_BLOCKING;
}

}  // namespace

void qa_register();

}  // namespace agent_model_card

void agent_model_card_anchor(const wmWindow *win,
                             const rctf &chip,
                             const float text_size,
                             const bool available)
{
  using namespace agent_model_card;
  g_anchor.win = win;
  g_anchor.chip = chip;
  g_anchor.text_size = text_size;
  g_anchor.valid = available && BLI_rctf_size_x(&chip) > 0.0f;
}

bool agent_model_card_is_open()
{
  return agent_model_card::g_state != nullptr;
}

void agent_model_card_register()
{
  WM_operatortype_append(agent_model_card::MIXAR_OT_agent_model_card);
  agent_model_card::qa_register();
}

}  // namespace blender
