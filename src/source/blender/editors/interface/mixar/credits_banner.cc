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
 * primary Upgrade; buttons act on release over the button they were
 * pressed on. Foreign timers and window events pass through.
 */

#include <algorithm>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLF_api.hh"

#include "BLI_listbase_iterator.hh"
#include "BLI_math_base.h"
#include "BLI_rect.h"
#include "BLI_time.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "UI_interface.hh"
#include "UI_mixar_credits_banner.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "../interface_qa_inspect.hh"

#include "credits_banner.hh"

namespace blender {
namespace ui::credits_banner {

static State *g_state = nullptr;

State *active()
{
  return g_state;
}

const char *target_action(const Target target)
{
  switch (target) {
    case TARGET_UPGRADE:
      return "UPGRADE";
    case TARGET_REFER:
      return "REFER";
    case TARGET_CREATOR:
      return "CREATOR";
    default:
      return "DISMISS";
  }
}

const char *target_label(const Target target)
{
  switch (target) {
    case TARGET_UPGRADE:
      return "Upgrade Plan";
    case TARGET_REFER:
      return "Refer a Friend";
    case TARGET_CREATOR:
      return "Apply to Creator Program";
    case TARGET_CLOSE:
      return "Close";
    default:
      return "";
  }
}

/* -------------------------------------------------------------------- */
/** \name Layout
 * \{ */

float appear_factor(const State &state, const double now)
{
  float t = float(std::clamp((now - state.opened_at) / ENTER_SECONDS, 0.0, 1.0));
  /* Ease-out back: the card lands with a whisper of overshoot. */
  const float c = 1.4f;
  t -= 1.0f;
  float f = 1.0f + (c + 1.0f) * t * t * t + c * t * t;
  if (state.closing_at > 0.0) {
    const float out = float(std::clamp((now - state.closing_at) / EXIT_SECONDS, 0.0, 1.0));
    f *= 1.0f - out * out;
  }
  return std::clamp(f, 0.0f, 1.08f);
}

Layout layout_compute(const State &state, const float appear)
{
  Layout l{};
  const float winx = float(WM_window_native_pixel_x(state.win));
  const float winy = float(WM_window_native_pixel_y(state.win));
  const float s = UI_SCALE_FAC;
  const float aspect = float(std::max(state.image_h, 1)) / float(std::max(state.image_w, 1));

  /* ~60% of the window, never cramped on small windows, never taller than 90%. */
  float w = std::max(winx * 0.60f, std::min(760.0f * s, winx * 0.94f));
  if (w * aspect > winy * 0.90f) {
    w = winy * 0.90f / aspect;
  }
  const float grow = 0.94f + 0.06f * appear; /* overshoot → a touch past 1 */
  const float cw = w * grow;
  const float ch = cw * aspect;
  const float cx = winx * 0.5f;
  const float cy = winy * 0.5f - (1.0f - std::min(appear, 1.0f)) * ch * 0.04f;
  BLI_rctf_init(&l.card, cx - cw * 0.5f, cx + cw * 0.5f, cy - ch * 0.5f, cy + ch * 0.5f);
  l.radius = cw * (44.0f / 1744.0f); /* the art's own corner radius */

  /* Buttons sit in the art's empty bottom band, under its chevron (the art's
   * frame ends ~20% above its bottom edge). */
  const float bh = std::clamp(ch * 0.074f, 30.0f * s, 58.0f * s);
  const float row_w = cw * 0.86f;
  const float gap = cw * 0.02f;
  const float bw = (row_w - 2.0f * gap) / 3.0f;
  const float by = l.card.ymin + ch * 0.098f;
  for (int i = 0; i < 3; i++) {
    const float x0 = cx - row_w * 0.5f + float(i) * (bw + gap);
    BLI_rctf_init(&l.targets[i], x0, x0 + bw, by - bh * 0.5f, by + bh * 0.5f);
  }
  l.button_h = bh;

  const rctf &creator = l.targets[TARGET_CREATOR];
  const float badge_h = bh * 0.42f;
  const int font = BLF_default();
  BLF_size(font, badge_h * 0.56f);
  BLF_character_weight(font, 800);
  const char *badge_text = "10K+ FOLLOWERS";
  const float badge_w = BLF_width(font, badge_text, strlen(badge_text)) + badge_h * 1.1f;
  BLF_character_weight(font, 400);
  const float badge_xmax = creator.xmax - bh * 0.35f;
  BLI_rctf_init(&l.badge,
                badge_xmax - badge_w,
                badge_xmax,
                creator.ymax - badge_h * 0.5f,
                creator.ymax + badge_h * 0.5f);

  const float close = std::clamp(cw * 0.03f, 24.0f * s, 38.0f * s);
  const float inset = cw * 0.022f;
  BLI_rctf_init(&l.targets[TARGET_CLOSE],
                l.card.xmax - inset - close,
                l.card.xmax - inset,
                l.card.ymax - inset - close,
                l.card.ymax - inset);
  return l;
}

Target hit_test(const Layout &layout, const float x, const float y)
{
  for (int t = 0; t < TARGET_COUNT; t++) {
    if (BLI_rctf_isect_pt(&layout.targets[t], x, y)) {
      return Target(t);
    }
  }
  if (BLI_rctf_isect_pt(&layout.badge, x, y)) {
    return TARGET_CREATOR;
  }
  return TARGET_NONE;
}

/** \} */

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
  const Layout layout = layout_compute(state, 1.0f);
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
    /* Ease every hover highlight toward its target (~120 ms). */
    for (int t = 0; t < TARGET_COUNT; t++) {
      const float goal = (state->hover == t) ? 1.0f : 0.0f;
      state->hover_mix[t] += (goal - state->hover_mix[t]) * 0.22f;
    }
    /* Redraw every tick: entrance, button stagger and the Upgrade halo's
     * breathing all animate. Regions are composited from their buffers. */
    request_redraw(state->win);
    return OPERATOR_RUNNING_MODAL;
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
      else if (ELEM(event->type, EVT_RETKEY, EVT_PADENTER)) {
        choose(C, *state, TARGET_UPGRADE);
      }
    }
    return OPERATOR_RUNNING_MODAL;
  }

  /* Event xy are window pixels: the draw callback's space. */
  const float mx = float(event->xy[0]);
  const float my = float(event->xy[1]);

  if (ELEM(event->type, MOUSEMOVE, INBETWEEN_MOUSEMOVE)) {
    update_hover(*state, mx, my);
    return OPERATOR_RUNNING_MODAL;
  }

  if (event->type == LEFTMOUSE) {
    const Layout layout = layout_compute(*state, 1.0f);
    const Target hit = hit_test(layout, mx, my);
    if (event->val == KM_PRESS) {
      if (hit != TARGET_NONE) {
        state->pressed = hit;
      }
      else if (!BLI_rctf_isect_pt(&layout.card, mx, my)) {
        choose(C, *state, TARGET_CLOSE); /* backdrop press */
      }
    }
    else if (event->val == KM_RELEASE) {
      if (hit != TARGET_NONE && hit == state->pressed) {
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
  const Layout layout = layout_compute(*state, 1.0f);
  for (int t = 0; t < TARGET_COUNT; t++) {
    MixarQATarget target;
    target.surface = "credits_banner";
    target.text = target_label(Target(t));
    target.value = target_action(Target(t));
    target.index = t;
    BLI_rcti_rctf_copy_round(&target.rect_win, &layout.targets[t]);
    target.sel = state->hover == t;
    target.window_level = true;
    r_targets.push_back(std::move(target));
  }
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
