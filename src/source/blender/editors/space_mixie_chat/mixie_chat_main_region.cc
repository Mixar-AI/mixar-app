/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Main region callbacks for Mixie Chat space.
 * Cursor hover tracking, View2D init, draw, listener, and layout.
 */

#include <cmath>

#include "BLI_listbase.h"
#include "BLI_rect.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "ED_screen.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "GPU_framebuffer.hh"
#include "UI_view2d.hh"

#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Cursor / Hover Tracking
 * \{ */

void mixie_chat_main_region_cursor(wmWindow *win, ScrArea *area, ARegion *region)
{
  int mval[2];
  mval[0] = win->runtime->eventstate->xy[0] - region->winrct.xmin;
  mval[1] = win->runtime->eventstate->xy[1] - region->winrct.ymin;

  bool needs_redraw = false;
  bool any_hovered = false;

  SpaceMixieChat *smixie = reinterpret_cast<SpaceMixieChat *>(area->spacedata.first);
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);

  /* The floating Agent Bubble keeps the default cursor everywhere: the
   * hover-tracking below still runs (it drives the hover highlights), but
   * the hand cursor is never shown — during an agent run the steps/thinking
   * headers cover most of the bubble, which made the cursor flip to a hand
   * over practically the whole window. */
  const bool suppress_hand = (area->spacetype == SPACE_AGENT_BUBBLE);

  /* Scribble ink overlay is modal while open — it owns the cursor (paint
   * crosshair over the canvas) and suppresses hover behind its scrim.
   * Checked first, matching its topmost draw slot. */
  if (rt->ink_overlay_active &&
      mixie_chat_ink_cursor(win, rt, region, float(mval[0]), float(mval[1])))
  {
    return;
  }

  /* Project-rules overlay is modal while open — it owns hover + cursor and
   * suppresses hover on everything behind its scrim. Checked before the
   * history overlay: it draws on top, so it wins the cursor too. */
  if (rt->rules_overlay_active &&
      mixie_chat_rules_cursor(win, rt, region, float(mval[0]), float(mval[1])))
  {
    return;
  }

  /* Past-chats overlay is modal while open — it owns hover + cursor and
   * suppresses hover on everything behind its scrim. */
  if (rt->history_overlay_active &&
      mixie_chat_history_cursor(win, rt, region, float(mval[0]), float(mval[1])))
  {
    return;
  }

  /* Check scroll-to-bottom indicator (screen-space, checked before View2D transform) */
  if (rt->scroll_indicator_visible) {
    float mouse_x = float(mval[0]);
    float mouse_y = float(mval[1]);
    if (BLI_rctf_isect_pt(&rt->scroll_indicator_bounds, mouse_x, mouse_y)) {
      WM_cursor_set(win, suppress_hand ? WM_CURSOR_DEFAULT : WM_CURSOR_HAND);
      return;
    }
  }

  /* Check empty prompt bubbles first (when chat is empty) */
  if (rt->empty_prompts_visible) {
    float mouse_x = float(mval[0]);
    float mouse_y = float(mval[1]);

    for (int i = 0; i < CHAT_EMPTY_PROMPT_COUNT; i++) {
      bool was_hovered = rt->empty_prompts[i].is_hovered;
      rt->empty_prompts[i].is_hovered = BLI_rctf_isect_pt(
          &rt->empty_prompts[i].bounds, mouse_x, mouse_y);

      if (was_hovered != rt->empty_prompts[i].is_hovered) {
        needs_redraw = true;
      }
      if (rt->empty_prompts[i].is_hovered) {
        any_hovered = true;
      }
    }

    if (needs_redraw) {
      ED_region_tag_redraw(region);
    }

    WM_cursor_set(
        win, (any_hovered && !suppress_hand) ? WM_CURSOR_HAND : WM_CURSOR_DEFAULT);
    return;
  }

  /* Convert to View2D coords for message option bubbles */
  View2D *v2d = &region->v2d;
  float mouse_x, mouse_y;
  ui::view2d_region_to_view(v2d, mval[0], mval[1], &mouse_x, &mouse_y);

  blender::Vector<MessageLayoutData> &layout_cache =
      const_cast<blender::Vector<MessageLayoutData> &>(mixie_chat_get_layout_cache(smixie));

  for (MessageLayoutData &layout : layout_cache) {
    for (int i = 0; i < layout.option_bubble_count; i++) {
      OptionBubbleData &bubble = layout.option_bubbles[i];
      bool was_hovered = bubble.is_hovered;
      bubble.is_hovered = BLI_rctf_isect_pt(&bubble.bounds, mouse_x, mouse_y);

      if (was_hovered != bubble.is_hovered) {
        needs_redraw = true;
      }
      if (bubble.is_hovered) {
        any_hovered = true;
      }
    }

    for (int i = 0; i < layout.slot_action_count; i++) {
      ActionSlotData &action = layout.slot_actions[i];
      bool was_hovered = action.is_hovered;
      action.is_hovered = BLI_rctf_isect_pt(&action.bounds, mouse_x, mouse_y);

      if (was_hovered != action.is_hovered) {
        needs_redraw = true;
      }
      if (action.is_hovered) {
        any_hovered = true;
      }
    }

    for (int i = 0; i < layout.action_button_count; i++) {
      ChatActionButton &btn = layout.action_buttons[i];
      bool was_hovered = btn.is_hovered;
      btn.is_hovered = BLI_rctf_isect_pt(&btn.bounds, mouse_x, mouse_y);

      if (was_hovered != btn.is_hovered) {
        needs_redraw = true;
      }
      if (btn.is_hovered) {
        any_hovered = true;
      }
    }


    /* Feedback stars hover. Locked (in-flight or accepted) feedback is not
     * interactive, so it gets no hover affordance either. */
    const bool feedback_locked = layout.feedback_status == FEEDBACK_STATUS_SENDING ||
                                 layout.feedback_status == FEEDBACK_STATUS_RECEIVED;
    if (layout.has_feedback) {
      /* Stars keep the DEFAULT cursor: the fill preview is the hover
       * affordance, and flipping to the hand while sweeping the row reads as
       * flicker. So hover only drives needs_redraw, never any_hovered. */
      for (int i = 0; i < FEEDBACK_STAR_COUNT; i++) {
        FeedbackStarData &star = layout.feedback_stars[i];
        bool was_hovered = star.is_hovered;
        bool has_bounds = star.bounds.xmax > star.bounds.xmin;
        star.is_hovered = !feedback_locked && has_bounds &&
                          BLI_rctf_isect_pt(&star.bounds, mouse_x, mouse_y);
        if (was_hovered != star.is_hovered) {
          needs_redraw = true;
        }
      }
      /* Comment link hover */
      bool was_comment_hovered = layout.feedback_comment_hovered;
      bool has_comment_bounds = layout.feedback_comment_bounds.xmax >
                                layout.feedback_comment_bounds.xmin;
      layout.feedback_comment_hovered = has_comment_bounds &&
          BLI_rctf_isect_pt(&layout.feedback_comment_bounds, mouse_x, mouse_y);
      if (was_comment_hovered != layout.feedback_comment_hovered) {
        needs_redraw = true;
      }
      if (layout.feedback_comment_hovered) {
        any_hovered = true;
      }
    }

    /* Steps block header + rows and thinking dropdown header are click
     * targets too — give them the hand cursor. */
    if (layout.has_steps &&
        BLI_rctf_isect_pt(&layout.steps_header_bounds, mouse_x, mouse_y))
    {
      any_hovered = true;
    }
    if (layout.has_steps && !layout.steps_collapsed) {
      for (int i = 0; i < layout.slot_step_count; i++) {
        StepItemSlotData &step = layout.slot_steps[i];
        bool was_hovered = step.is_hovered;
        step.is_hovered = BLI_rctf_isect_pt(&step.row_bounds, mouse_x, mouse_y);
        if (was_hovered != step.is_hovered) {
          needs_redraw = true;
        }
        if (step.is_hovered) {
          any_hovered = true;
        }
      }
    }
    if (layout.has_thinking &&
        BLI_rctf_isect_pt(&layout.thinking_header_bounds, mouse_x, mouse_y))
    {
      any_hovered = true;
    }
  }

  /* Code-block copy chips (hover state lives in mixie_chat_code_copy.cc) */
  {
    bool chip_hover_changed = false;
    if (mixie_chat_code_hits_hover(rt, mouse_x, mouse_y, &chip_hover_changed)) {
      any_hovered = true;
    }
    if (chip_hover_changed) {
      needs_redraw = true;
    }
  }

  if (needs_redraw) {
    ED_region_tag_redraw(region);
  }

  WM_cursor_set(
      win, (any_hovered && !suppress_hand) ? WM_CURSOR_HAND : WM_CURSOR_DEFAULT);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Direct Click Handler (UI Handler)
 *
 * Bypasses keymap system entirely. Registered as a UI handler so it runs
 * before any keymap handlers, ensuring LEFTMOUSE reaches our click dispatch.
 * \{ */

/**
 * Is this region's transcript the surface actually on screen?
 *
 * The Agent Bubble's WINDOW region is SHARED: the transcript draws there on
 * the Agent tab, while the 3D / Media / Splat / Generations / Queue panes build
 * their uiBlocks into the very same region. This handler is registered so it
 * sees LEFTMOUSE ahead of the ui::Block handler (mixie_chat_main_region_init) —
 * exactly the overlap that comment warns about. On a pane tab it would dispatch
 * message rects left over from the last Agent-tab draw and BREAK the event
 * before the pane's own button ran. SPACE_MIXIE_CHAT is never tab-switched.
 */
static bool mixie_chat_dispatch_is_live(const bContext *C)
{
  const ScrArea *area = CTX_wm_area(C);
  if (!area) {
    return false;
  }
  if (area->spacetype != SPACE_AGENT_BUBBLE) {
    return area->spacetype == SPACE_MIXIE_CHAT;
  }

  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return true;
  }
  /* wm.mixar_bubble_tab is the island's ONE source of what the card shows
   * (bubble_tab_props.py). Matched on the stable enum IDENTIFIER, never an
   * index; absent before Python registers it, and the card is Agent until
   * then — so every unreadable branch below falls back to live. */
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixar_bubble_tab");
  if (!prop || RNA_property_type(prop) != PROP_ENUM) {
    return true;
  }
  const char *ident = nullptr;
  if (!RNA_property_enum_identifier(
          nullptr, &wm_ptr, prop, RNA_property_enum_get(&wm_ptr, prop), &ident) ||
      ident == nullptr)
  {
    return true;
  }
  return STREQ(ident, "AGENT");
}

int mixie_chat_ui_handler(bContext *C, const wmEvent *event, void * /*userdata*/)
{
  if (!mixie_chat_dispatch_is_live(C)) {
    return WM_UI_HANDLER_CONTINUE;
  }

  /* 0a. Scribble ink overlay — modal while open: captures pen strokes,
   * consumes keys/clicks/scroll, runs the idle-commit timer. Checked
   * before rules/history because it draws on top of both. Cheap no-op
   * when closed (runtime flag check, no RNA reads). */
  if (mixie_chat_ink_handle_event(C, event)) {
    return WM_UI_HANDLER_BREAK;
  }

  /* 0. Project-rules overlay — modal while open: consumes text-editing
   * keys, clicks (incl. click-away close), scroll, and ESC. Checked
   * before the history overlay because it draws on top. Cheap no-op when
   * closed (runtime flag check, no RNA reads). */
  if (mixie_chat_rules_handle_event(C, event)) {
    return WM_UI_HANDLER_BREAK;
  }

  /* 0b. Past-chats overlay — modal while open: consumes clicks (incl.
   * click-away close), wheel/trackpad scroll, and ESC. Cheap no-op when
   * closed (runtime flag check, no RNA reads). */
  if (mixie_chat_history_handle_event(C, event)) {
    return WM_UI_HANDLER_BREAK;
  }

  if (event->type == LEFTMOUSE && event->val == KM_PRESS) {
    ScrArea *area = CTX_wm_area(C);
    ARegion *region = CTX_wm_region(C);

    /* SPACE_AGENT_BUBBLE reuses these callbacks via its layout-
     * compatible spacedata struct (see DNA_space_types.h on
     * SpaceAgentBubble). The cast below works for both. */
    if (!area || !region ||
        (area->spacetype != SPACE_MIXIE_CHAT &&
         area->spacetype != SPACE_AGENT_BUBBLE))
    {
      return WM_UI_HANDLER_CONTINUE;
    }

    SpaceMixieChat *smixie = reinterpret_cast<SpaceMixieChat *>(area->spacedata.first);
    if (!smixie) {
      return WM_UI_HANDLER_CONTINUE;
    }

    float mx = float(event->mval[0]);
    float my = float(event->mval[1]);

    /* 1. Scroll-to-bottom indicator (screen-space) */
    if (mixie_chat_handle_scroll_indicator_click(smixie, region, mx, my)) {
      ED_region_tag_redraw(region);
      return WM_UI_HANDLER_BREAK;
    }

    /* 2. Empty prompt clicks */
    if (mixie_chat_handle_empty_prompt_click(C, mx, my)) {
      return WM_UI_HANDLER_BREAK;
    }

    /* 3. Action button clicks (copy/retry) */
    if (mixie_chat_handle_action_button_click(C, region, mx, my)) {
      return WM_UI_HANDLER_BREAK;
    }

    /* 3b. Code-block copy chip clicks */
    if (mixie_chat_handle_code_copy_click(C, region, mx, my)) {
      return WM_UI_HANDLER_BREAK;
    }

    /* 4. Steps/thinking collapse toggle clicks */
    if (mixie_chat_handle_steps_click(C, region, mx, my)) {
      return WM_UI_HANDLER_BREAK;
    }

    /* 5. Slot action clicks (approve/modify/cancel/options) */
    if (mixie_chat_handle_slot_action_click(C, region, mx, my)) {
      return WM_UI_HANDLER_BREAK;
    }

    /* 6. Feedback star/comment clicks */
    if (mixie_chat_handle_feedback_click(C, region, mx, my)) {
      return WM_UI_HANDLER_BREAK;
    }

    /* 7. Option bubble clicks */
    {
      const blender::Vector<MessageLayoutData> &layout_cache =
          mixie_chat_get_layout_cache(smixie);

      View2D *v2d = &region->v2d;
      float view_x, view_y;
      ui::view2d_region_to_view(v2d, int(mx), int(my), &view_x, &view_y);

      for (const MessageLayoutData &layout : layout_cache) {
        for (int i = 0; i < layout.option_bubble_count; i++) {
          const OptionBubbleData &bubble = layout.option_bubbles[i];
          if (bubble.bounds.xmax > bubble.bounds.xmin &&
              BLI_rctf_isect_pt(&bubble.bounds, view_x, view_y))
          {
            /* Option bubbles use the same mechanism as slot actions but with the
             * option text as the action value. Dispatch via Python operator. */
            wmOperatorType *ot = WM_operatortype_find("mixie_chat.select_slot_action", true);
            if (ot && layout.bubble_id[0] != '\0') {
              PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
              RNA_string_set(&op_ptr, "bubble_id", layout.bubble_id);
              RNA_string_set(&op_ptr, "action_value", bubble.option_text);
              WM_operator_name_call_ptr(
                  C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
              WM_operator_properties_free(&op_ptr);
              ED_region_tag_redraw(region);
              return WM_UI_HANDLER_BREAK;
            }
          }
        }
      }
    }

    /* 8. Scribble auto-open: a stylus press that reached this point hit no
     * interactive chat target — pen users write, they don't drag-select
     * transcript text. The press itself seeds the first ink stroke.
     * Mouse presses fall through to text selection / View2D as before. */
    if (mixie_chat_ink_try_auto_open(C, event)) {
      return WM_UI_HANDLER_BREAK;
    }

    /* Let text selection / View2D scrolling handle it */
  }

  return WM_UI_HANDLER_CONTINUE;
}

void mixie_chat_ui_handler_remove(bContext * /*C*/, void * /*userdata*/)
{
  /* Nothing to free */
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Region Init / Draw / Layout / Listener
 * \{ */

void mixie_chat_main_region_init(wmWindowManager *wm, ARegion *region)
{
  const float prev_y_min = region->v2d.cur.ymin;

  ui::view2d_region_reinit(&region->v2d, ui::V2D_COMMONVIEW_CUSTOM, region->winx, region->winy);

  View2D *v2d = &region->v2d;

  v2d->tot.xmin = 0;
  v2d->tot.xmax = float(region->winx);
  v2d->tot.ymin = 0;
  v2d->tot.ymax = float(region->winy);

  if (prev_y_min != v2d->cur.ymin) {
    const float cur_y_range = BLI_rctf_size_y(&v2d->cur);
    v2d->cur.ymin = prev_y_min;
    v2d->cur.ymax = prev_y_min + cur_y_range;
  }

  v2d->scroll = V2D_SCROLL_RIGHT | V2D_SCROLL_VERTICAL_HANDLES;
  v2d->keepzoom = V2D_LOCKZOOM_X | V2D_LOCKZOOM_Y | V2D_KEEPZOOM;
  v2d->minzoom = 1.0f;
  v2d->maxzoom = 1.0f;

  v2d->align = V2D_ALIGN_NO_NEG_X | V2D_ALIGN_NO_NEG_Y;
  v2d->keeptot = V2D_KEEPTOT_STRICT;

  /* Register ui::Block event handler so embedded text inputs (feedback comment)
   * can receive clicks and keyboard events. NOTE: both this and
   * WM_event_add_ui_handler below PREPEND (BLI_addhead), so registering the
   * ui::Block handler first actually makes it run AFTER the chat handler —
   * mixie_chat_ui_handler gets first look at every mouse press. That works
   * today only because no chat hit-target overlaps the feedback text field
   * (and active textedit grabs keys via the window modal handler); if a chat
   * hit-target ever overlaps a ui::Block button, the click will be stolen from
   * the button unless this ordering is revisited. */
  ui::region_handlers_add(&region->runtime->handlers);

  /* Register our direct UI click handler.
   * UI handlers run before ALL keymap handlers in Blender's event dispatch.
   * This ensures LEFTMOUSE clicks reach our chat click dispatch (option bubbles,
   * slot actions, scroll indicator, etc.) before any keymap consumes the event. */
  WM_event_remove_ui_handler(
      &region->runtime->handlers, mixie_chat_ui_handler, mixie_chat_ui_handler_remove, nullptr, false);
  WM_event_add_ui_handler(nullptr,
                          &region->runtime->handlers,
                          mixie_chat_ui_handler,
                          mixie_chat_ui_handler_remove,
                          nullptr,
                          eWM_EventHandlerFlag(0));

  /* Register the View2D keymap BEFORE the Mixie Chat keymap. Keymap
   * handlers run in registration order, and both keymaps bind LEFTMOUSE:
   * "Mixie Chat" for text selection and "View2D" for scrollbar dragging
   * (view2d.scroller_activate). scroller_activate passes the event
   * through when the cursor is not over a scroller, so it must get first
   * look — the reverse order let select_text consume every click
   * (OPERATOR_CANCELLED breaks event handling even on a miss), which
   * made the chat scrollbar impossible to click or drag. This matches
   * upstream editors, where ed_default_handlers installs View2D ahead
   * of the editor's own keymap. */
  wmKeyMap *keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "View2D", SPACE_EMPTY, RGN_TYPE_WINDOW);
  WM_event_add_keymap_handler_v2d_mask(&region->runtime->handlers, keymap);

  /* Register Mixie Chat keymap for text selection (modal drag) and copy. */
  wmKeyMap *mixie_keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "Mixie Chat", SPACE_MIXIE_CHAT, RGN_TYPE_WINDOW);
  WM_event_add_keymap_handler(&region->runtime->handlers, mixie_keymap);

  /* Register dropbox handler for image drag-and-drop. */
  ListBaseT<wmDropBox> *dropboxes = WM_dropboxmap_find(
      "Mixie Chat", SPACE_MIXIE_CHAT, RGN_TYPE_WINDOW);
  WM_event_add_dropbox_handler(static_cast<ListBaseT<wmEventHandler> *>(&region->runtime->handlers),
                               static_cast<ListBaseT<wmDropBox> *>(dropboxes));
}

/* ---- Background colour override for Agent Bubble -------------------- */

static bool s_bg_override_active = false;
static float s_bg_override_rgba[4] = {0, 0, 0, 1};

void mixie_chat_set_bg_override(const float rgba[4])
{
  s_bg_override_active = true;
  for (int i = 0; i < 4; i++) {
    s_bg_override_rgba[i] = rgba[i];
  }
}

void mixie_chat_clear_bg_override()
{
  s_bg_override_active = false;
}

bool mixie_chat_has_bg_override()
{
  return s_bg_override_active;
}

void mixie_chat_get_bg_override(float r_rgba[4])
{
  for (int i = 0; i < 4; i++) {
    r_rgba[i] = s_bg_override_rgba[i];
  }
}

static void mixie_chat_clear_background()
{
  if (s_bg_override_active) {
    GPU_clear_color(
        s_bg_override_rgba[0], s_bg_override_rgba[1],
        s_bg_override_rgba[2], s_bg_override_rgba[3]);
  }
  else {
    ui::theme::frame_buffer_clear(TH_BACK);
  }
}

void mixie_chat_main_region_draw(const bContext *C, ARegion *region)
{
  mixie_chat_clear_background();
  mixie_chat_draw_messages(C, region);
  /* Past-chats overlay — drawn last (screen-space) so it sits on top of
   * messages, the empty state, and the View2D scrollbar. */
  mixie_chat_draw_history_overlay(C, region);
  /* Project-rules overlay — drawn after history so it sits on top (the
   * Python toggles keep the two mutually exclusive; this is belt and
   * braces for the event-order contract in mixie_chat_ui_handler). */
  mixie_chat_draw_rules_overlay(C, region);
  /* Scribble ink overlay — topmost, matching its first-in-events slot. */
  mixie_chat_draw_ink_overlay(C, region);
}

/* -------------------------------------------------------------------- */
/** \name Animation Frame Pump
 *
 * Draw-side animations (bubble slide-in, spinner, streaming loader) advance
 * per draw and tag their own region — but a tag from inside a draw callback
 * does NOT wake Blender's idle event loop, so with no input events the next
 * frame only arrives on the next unrelated timer tick and animations stutter.
 *
 * The pump is a TIMERNOTIFIER wmTimer (same pattern as the View3D agent
 * strip tick): while any chat animation is live, it broadcasts
 * NC_SPACE | ND_SPACE_MIXIE_CHAT_TICK at CHAT_ANIM_PUMP_FPS; the (narrow)
 * main-region listener turns each tick into a redraw for every chat surface
 * (MIXIE_CHAT editor and the floating agent bubble).
 *
 * Lifecycle: every messages draw calls mixie_chat_anim_pump_request() with
 * whether that surface still animates. The timer is created on first demand
 * and removed after a short idle grace (the pump's own ticks keep draws
 * coming, so the idle path is guaranteed to run). Region exit removes it
 * outright — otherwise closing/switching away from the last chat surface
 * would leave an orphan timer waking the event loop forever. All removals go
 * through WM_event_timer_remove, which membership-checks first, so a pointer
 * the WM already freed on window close is a safe no-op.
 * \{ */

#define CHAT_ANIM_PUMP_FPS 30.0
#define CHAT_ANIM_PUMP_IDLE_GRACE 0.5 /* seconds without an active animation */

static wmTimer *g_chat_anim_timer = nullptr;
static double g_chat_anim_last_request = 0.0;

void mixie_chat_anim_pump_request(const bContext *C, bool anim_active)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return;
  }
  const double now = BLI_time_now_seconds();
  if (anim_active) {
    g_chat_anim_last_request = now;
    if (g_chat_anim_timer == nullptr) {
      wmWindow *win = CTX_wm_window(C);
      if (win != nullptr) {
        g_chat_anim_timer = WM_event_timer_add_notifier(
            wm, win, NC_SPACE | ND_SPACE_MIXIE_CHAT_TICK, 1.0 / CHAT_ANIM_PUMP_FPS);
      }
    }
  }
  else if (g_chat_anim_timer != nullptr &&
           (now - g_chat_anim_last_request) > CHAT_ANIM_PUMP_IDLE_GRACE)
  {
    WM_event_timer_remove(wm, nullptr, g_chat_anim_timer);
    g_chat_anim_timer = nullptr;
  }
}

void mixie_chat_anim_pump_shutdown(wmWindowManager *wm)
{
  if (wm == nullptr || g_chat_anim_timer == nullptr) {
    return;
  }
  WM_event_timer_remove(wm, nullptr, g_chat_anim_timer);
  g_chat_anim_timer = nullptr;
}

void mixie_chat_main_region_exit(wmWindowManager *wm, ARegion * /*region*/)
{
  /* One of possibly several chat surfaces went away. If another surface is
   * still animating, its next draw re-creates the pump (content updates keep
   * tagging it); if this was the last one, the timer must die here. */
  mixie_chat_anim_pump_shutdown(wm);
  /* Same discipline for the scribble idle-commit timer: window close and
   * file-load WM replacement free window-bound timers, and a dangling
   * global pointer would block re-arming AND could match a recycled
   * foreign wmTimer. A surviving surface re-arms on its next pen-up. */
  mixie_chat_ink_idle_timer_remove(wm);
}

/** \} */

void mixie_chat_main_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  /* Keep this listener narrow. Chat content only changes through the
   * Python message store, which explicitly tags the chat/bubble areas
   * after every event batch (redraw_chat_areas in ui_utils.py); undo and
   * file loads broadcast NC_WINDOW, which the generic region listener in
   * area.cc already handles. The previous catch-alls here (every
   * NC_SCENE notifier, every NC_ID edit, every NC_WM job tick) repainted
   * the chat and the floating agent bubble constantly while the user
   * worked in the viewport (selection, frame changes, bakes, renders) —
   * a large part of the perceived bubble lag. */
  switch (wmn->category) {
    case NC_SPACE:
      /* Redraw on our space notifier OR the agent bubble's, since
       * SPACE_AGENT_BUBBLE reuses this listener (layout-compatible
       * spacedata, see DNA_space_types.h on SpaceAgentBubble). */
      if (wmn->data == ND_SPACE_MIXIE_CHAT || wmn->data == ND_SPACE_AGENT_BUBBLE ||
          wmn->data == ND_SPACE_MIXIE_CHAT_TICK)
      {
        /* MIXIE_CHAT_TICK is the animation frame pump (see above): it only
         * redraws this main region, never the header/footer. */
        ED_region_tag_redraw(region);
      }
      break;
    case NC_SCENE:
      /* Messages live on Scene — redraw when the window switches to a
       * different scene, but not on every scene-data edit. */
      if (wmn->data == ND_SCENEBROWSE || wmn->action == NA_REMOVED) {
        ED_region_tag_redraw(region);
      }
      break;
  }
}

void mixie_chat_main_region_layout(const bContext * /*C*/, ARegion *region)
{
  View2D *v2d = &region->v2d;

  int winx = BLI_rcti_size_x(&region->winrct) + 1;
  int winy = BLI_rcti_size_y(&region->winrct) + 1;

  v2d->winx = winx;
  v2d->winy = winy;

  v2d->tot.xmax = float(winx);

  v2d->mask.xmin = 0;
  v2d->mask.ymin = 0;
  v2d->mask.xmax = winx;
  v2d->mask.ymax = winy;

  float cur_height_current = BLI_rctf_size_y(&v2d->cur);
  float cur_height_target = float(winy);

  if (fabsf(cur_height_current - cur_height_target) > 0.5f) {
    const float scroll_threshold = 20.0f;
    bool was_at_bottom = (v2d->cur.ymin <= v2d->tot.ymin + scroll_threshold);

    if (was_at_bottom || v2d->cur.ymax <= 0.0f) {
      v2d->cur.ymin = v2d->tot.ymin;
      v2d->cur.ymax = v2d->cur.ymin + cur_height_target;
    }
    else {
      float center_y = (v2d->cur.ymin + v2d->cur.ymax) / 2.0f;
      v2d->cur.ymin = center_y - cur_height_target / 2.0f;
      v2d->cur.ymax = center_y + cur_height_target / 2.0f;
    }

    v2d->cur.xmin = 0.0f;
    v2d->cur.xmax = float(winx);
  }
}

/** \} */
}  // namespace blender
