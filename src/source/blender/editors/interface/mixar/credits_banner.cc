/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Out-of-credits banner: `MIXAR_OT_credits_banner` is a blocking modal
 * operator whose window draw callback paints the banner above every editor
 * of its window (the chat lightbox's pattern). Python decides WHEN it opens
 * (common/notifications/credits_banner.py) and owns what each button does:
 * every choice, dismissal included, is reported once to
 * `MIXAR_OT_credits_banner_action` with an `action` name, so the URLs,
 * handoffs and telemetry stay in one Python place.
 *
 * Input: Esc or a press on the dimmed backdrop dismisses; Enter picks the
 * focused action (Upgrade by default); Creator requires a completed slide,
 * released anywhere.
 * Foreign timers and window events pass through.
 */

#include <algorithm>

#include "MEM_guardedalloc.h"

#include "BLI_listbase_iterator.hh"
#include "BLI_rect.h"
#include "BLI_time.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "UI_mixar_credits_banner.hh"
#include "UI_mixar_motion.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "../interface_qa_inspect.hh"

#include "credits_banner.hh"

namespace blender {
namespace ui::credits_banner {

static State *g_state = nullptr;

const char *target_action(const Target target)
{
  switch (target) {
    case TARGET_UPGRADE:
      return "UPGRADE";
    case TARGET_REFER:
      return "REFER";
    case TARGET_CREATOR:
      return "CREATOR";
    case TARGET_BYOK:
      return "BYOK";
    case TARGET_MCP:
      return "MCP";
    default:
      return "DISMISS";
  }
}

const char *target_label(const Target target, const bool subscribe)
{
  switch (target) {
    case TARGET_UPGRADE:
      return subscribe ? "Subscribe" : "Upgrade Plan";
    case TARGET_REFER:
      return "Refer a Friend";
    case TARGET_CREATOR:
      return "Creator Program";
    case TARGET_BYOK:
      return "Use your own API key";
    case TARGET_MCP:
      return "Connect AI apps (MCP)";
    case TARGET_CLOSE:
      return "Close";
    default:
      return "";
  }
}

/* -------------------------------------------------------------------- */
/** \name Operator
 * \{ */

static void request_redraw(wmWindow *win)
{
  if (win) {
    if (bScreen *screen = WM_window_get_active_screen(win)) {
      screen->do_draw = true;
    }
  }
}

static void teardown(bContext *C, wmOperator *op)
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
  texture_free(*state);
  if (g_state == state) {
    g_state = nullptr;
  }
  MEM_delete(state);
  op->customdata = nullptr;
}

/** Report the user's choice to Python, then play the exit animation. */
static void choose(bContext *C, State &state, const Target target)
{
  if (state.closing_at > 0.0) {
    return;
  }
  state.closing_at = BLI_time_now_seconds();
  state.pressed = TARGET_NONE;
  state.dragging = false;
  WM_cursor_set(state.win, WM_CURSOR_DEFAULT);

  wmOperatorType *ot = WM_operatortype_find("MIXAR_OT_credits_banner_action", true);
  if (!ot) {
    return;
  }
  PointerRNA props = WM_operator_properties_create_ptr(ot);
  RNA_string_set(&props, "action", target_action(target));
  WM_operator_name_call_ptr(C, ot, wm::OpCallContext::ExecDefault, &props, nullptr);
  WM_operator_properties_free(&props);
}

static wmOperatorStatus banner_invoke(bContext *C, wmOperator *op, const wmEvent * /*event*/)
{
  wmWindow *win = CTX_wm_window(C);
  if (g_state || !win) {
    return OPERATOR_CANCELLED;
  }
  State *state = MEM_new<State>("mixar_credits_banner");
  char path[1024] = "";
  RNA_string_get(op->ptr, "image_path", path);
  state->image_path = path;
  state->subscribe = RNA_boolean_get(op->ptr, "subscribe");
  state->win = win;
  state->opened_at = BLI_time_now_seconds();
  state->draw_handle = WM_draw_cb_activate(win, draw, state);
  state->timer = WM_event_timer_add(CTX_wm_manager(C), win, TIMER, 1.0 / 60.0);
  op->customdata = state;
  g_state = state;
  WM_event_add_modal_handler(C, op);
  request_redraw(win);
  return OPERATOR_RUNNING_MODAL;
}

static void update_hover(State &state, const float mx, const float my)
{
  const Layout layout = layout_compute(state, appear_factor(state, BLI_time_now_seconds()));
  const Target hover = hit_test(layout, mx, my);
  if (hover != state.hover) {
    state.hover = hover;
    request_redraw(state.win);
  }
  WM_cursor_set(state.win, hover != TARGET_NONE ? WM_CURSOR_HAND : WM_CURSOR_DEFAULT);
}

static wmOperatorStatus banner_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  State *state = static_cast<State *>(op->customdata);
  if (!state) {
    return OPERATOR_CANCELLED;
  }

  if (event->type == TIMER) {
    if (event->customdata != state->timer) {
      return OPERATOR_PASS_THROUGH;
    }
    const double now = BLI_time_now_seconds();
    if (state->closing_at > 0.0 && now - state->closing_at >= EXIT_SECONDS) {
      teardown(C, op);
      return OPERATOR_FINISHED;
    }
    if (state->returning) {
      state->slide *= mixar_motion_reduced() ? 0.0f : 0.72f;
      if (state->slide < 0.001f) {
        state->slide = 0.0f;
        state->returning = false;
      }
    }
    /* Ease every hover highlight toward its target (~120 ms). */
    for (int t = 0; t < TARGET_COUNT; t++) {
      const float goal = (state->hover == t || state->focus == t) ? 1.0f : 0.0f;
      state->hover_mix[t] += (goal - state->hover_mix[t]) *
                             (mixar_motion_reduced() ? 1.0f : 0.22f);
    }
    /* Entrance, hover hint and slider return animate in the window overlay. */
    request_redraw(state->win);
    return OPERATOR_RUNNING_MODAL;
  }

  if (event->type == WINDEACTIVATE) {
    state->dragging = false;
    state->pressed = TARGET_NONE;
    state->returning = true;
    return OPERATOR_PASS_THROUGH;
  }
  const bool is_input = ISKEYBOARD(event->type) || ISMOUSE(event->type) ||
                        ISMOUSE_WHEEL(event->type) || ISMOUSE_GESTURE(event->type);
  if (!is_input) {
    return OPERATOR_PASS_THROUGH;
  }
  if (state->closing_at > 0.0) {
    return OPERATOR_RUNNING_MODAL;
  }

  if (ISKEYBOARD(event->type)) {
    if (event->val == KM_PRESS) {
      if (event->type == EVT_ESCKEY) {
        choose(C, *state, TARGET_CLOSE);
      }
      else if (event->type == EVT_TABKEY) {
        /* Keyboard navigation cancels any held mouse gesture. */
        state->dragging = false;
        state->pressed = TARGET_NONE;
        state->slide = 0.0f;
        state->returning = false;
        const int step = (event->modifier & KM_SHIFT) ? -1 : 1;
        state->focus = state->focus == TARGET_NONE ?
                           (step > 0 ? TARGET_UPGRADE : TARGET_CLOSE) :
                           (state->focus + step + TARGET_COUNT) % TARGET_COUNT;
      }
      else if (state->focus == TARGET_CREATOR && ELEM(event->type, EVT_RIGHTARROWKEY, EVT_LEFTARROWKEY)) {
        state->returning = false;
        state->slide = std::clamp(state->slide + (event->type == EVT_RIGHTARROWKEY ? 0.2f : -0.2f),
                                  0.0f, 1.0f);
      }
      else if (ELEM(event->type, EVT_RETKEY, EVT_PADENTER, EVT_SPACEKEY)) {
        const Target target = state->focus == TARGET_NONE ? TARGET_UPGRADE : Target(state->focus);
        if (target != TARGET_CREATOR || state->slide >= SLIDE_COMPLETE) {
          choose(C, *state, target);
        }
      }
      request_redraw(state->win);
    }
    return OPERATOR_RUNNING_MODAL;
  }

  /* Event xy are window pixels: the draw callback's space. */
  const float mx = float(event->xy[0]);
  const float my = float(event->xy[1]);

  if (ELEM(event->type, MOUSEMOVE, INBETWEEN_MOUSEMOVE)) {
    update_hover(*state, mx, my);
    if (state->dragging) {
      const Layout layout = layout_compute(*state, appear_factor(*state, BLI_time_now_seconds()));
      state->slide = slider_progress(layout, mx - state->drag_offset);
      request_redraw(state->win);
    }
    return OPERATOR_RUNNING_MODAL;
  }

  if (event->type == LEFTMOUSE) {
    const Layout layout = layout_compute(*state, appear_factor(*state, BLI_time_now_seconds()));
    const Target hit = hit_test(layout, mx, my);
    if (event->val == KM_PRESS) {
      /* A mouse gesture starts fresh after keyboard-driven progress. */
      if (state->focus != TARGET_NONE) {
        state->slide = 0.0f;
        state->returning = false;
      }
      state->focus = TARGET_NONE;
      if (hit == TARGET_CREATOR) {
        const rctf thumb = slider_thumb(layout, state->slide);
        if (BLI_rctf_isect_pt(&thumb, mx, my)) {
          state->dragging = true;
          state->returning = false;
          state->drag_offset = mx - BLI_rctf_cent_x(&thumb);
          state->pressed = hit;
        }
      }
      else if (hit != TARGET_NONE) {
        state->pressed = hit;
      }
      else if (!BLI_rctf_isect_pt(&layout.card, mx, my)) {
        choose(C, *state, TARGET_CLOSE); /* backdrop press */
      }
    }
    else if (event->val == KM_RELEASE) {
      if (state->dragging) {
        state->slide = slider_progress(layout, mx - state->drag_offset);
        state->dragging = false;
        /* Progress alone decides: a full slide usually overshoots the short
         * track or drifts off its thin height, and the hint already reads
         * "Release to continue" there. Sliding back is the way to cancel. */
        if (state->slide >= SLIDE_COMPLETE) {
          choose(C, *state, TARGET_CREATOR);
        }
        else {
          state->returning = true;
        }
      }
      else if (hit != TARGET_NONE && hit != TARGET_CREATOR && hit == state->pressed) {
        choose(C, *state, hit);
      }
      state->pressed = TARGET_NONE;
    }
    request_redraw(state->win);
  }
  /* Everything else (wheel, other buttons) stays inside the overlay. */
  return OPERATOR_RUNNING_MODAL;
}

static void banner_cancel(bContext *C, wmOperator *op)
{
  /* File load / window close: tear down silently, nothing was chosen. */
  teardown(C, op);
}

static void MIXAR_OT_credits_banner(wmOperatorType *ot)
{
  ot->name = "Out of Credits";
  ot->idname = "MIXAR_OT_credits_banner";
  ot->description = "Show the out-of-credits banner over the whole window";
  ot->invoke = banner_invoke;
  ot->modal = banner_modal;
  ot->cancel = banner_cancel;
  ot->flag = OPTYPE_INTERNAL | OPTYPE_BLOCKING;

  PropertyRNA *prop = RNA_def_string_file_path(
      ot->srna, "image_path", nullptr, 1024, "Image", "Banner art to draw");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
  prop = RNA_def_boolean(ot->srna,
                         "subscribe",
                         false,
                         "Subscribe",
                         "The account has no plan: ask for a subscription instead of an upgrade");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name QA targets
 *
 * Exported once per window through the top bar's HEADER region (Mixar
 * collapses its WINDOW region to nothing), as
 * `credits_banner` targets (text = the button's label, value = its action).
 * \{ */

/** The top bar carries more than one HEADER region; export from the first
 * visible one only, so each target appears once. */
static bool is_host_region(const ScrArea *area, const ARegion *region)
{
  for (const ARegion &r : area->regionbase) {
    if (r.regiontype == RGN_TYPE_HEADER && !(r.flag & RGN_FLAG_HIDDEN) &&
        BLI_rcti_size_x(&r.winrct) > 0 && BLI_rcti_size_y(&r.winrct) > 0)
    {
      return &r == region;
    }
  }
  return false;
}

static void qa_targets(const wmWindow *win,
                       const ScrArea *area,
                       const ARegion *region,
                       std::vector<MixarQATarget> &r_targets)
{
  const State *state = g_state;
  if (!state || state->win != win || state->closing_at > 0.0 ||
      !is_host_region(area, region))
  {
    return;
  }
  const Layout layout = layout_compute(*state, appear_factor(*state, BLI_time_now_seconds()));
  for (int t = 0; t < TARGET_COUNT; t++) {
    MixarQATarget target;
    target.surface = "credits_banner";
    target.text = target_label(Target(t), state->subscribe);
    target.value = target_action(Target(t));
    target.index = t;
    BLI_rcti_rctf_copy_round(&target.rect_win, &layout.targets[t]);
    target.sel = state->hover == t;
    target.window_level = true;
    r_targets.push_back(std::move(target));
  }
  MixarQATarget thumb;
  thumb.surface = "credits_banner_slider";
  thumb.text = creator_hint(*state);
  thumb.value = std::to_string(state->slide);
  thumb.detail = state->dragging ? "dragging" : "idle";
  const rctf thumb_rect = slider_thumb(layout, state->slide);
  BLI_rcti_rctf_copy_round(&thumb.rect_win, &thumb_rect);
  thumb.window_level = true;
  r_targets.push_back(std::move(thumb));
  MixarQATarget card;
  card.surface = "credits_banner_card";
  card.text = state->texture ? "art" : (state->image_failed ? "missing" : "loading");
  BLI_rcti_rctf_copy_round(&card.rect_win, &layout.card);
  card.window_level = true;
  r_targets.push_back(std::move(card));
}

/** \} */

}  // namespace ui::credits_banner

void ED_mixar_credits_banner_register()
{
  WM_operatortype_append(ui::credits_banner::MIXAR_OT_credits_banner);
  Mixar_qa_register_target_provider(SPACE_TOPBAR, ui::credits_banner::qa_targets);
}

}  // namespace blender
