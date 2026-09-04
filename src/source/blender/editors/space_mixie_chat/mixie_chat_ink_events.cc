/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Scribble ink overlay — event + cursor half (drawing lives in
 * mixie_chat_ink_overlay.cc).
 *
 * While open the overlay is modal for the chat main region:
 *   - left-press-drag captures a pressure-stamped ink stroke (stylus is
 *     the primary device but the mouse works too — recognition doesn't
 *     care); modal-free capture: the region UI handler sees every
 *     MOUSEMOVE / INBETWEEN_MOUSEMOVE between press and release;
 *   - a wmTimer converts pending strokes after INK_IDLE_COMMIT_SEC of
 *     pen-up silence (iPadOS-Scribble style "pause to convert"), so the
 *     user keeps writing and text keeps flowing into the composer;
 *   - Enter converts now; Esc / close X / click on Clear behave as
 *     labelled; every close path flushes pending ink first — writing is
 *     never silently dropped;
 *   - all other keyboard input is consumed (modal, like the rules
 *     overlay).
 *
 * Two auto-open paths make the feature feel like Scribble:
 *   - a stylus press on the composer input box (footer region UI handler
 *     below) opens the canvas instead of entering text-edit;
 *   - a stylus press in the main region that hit no interactive chat
 *     target (checked LAST in mixie_chat_ui_handler) opens the canvas
 *     AND starts the first stroke with that very press.
 */

#include <algorithm>
#include <cmath>

#include "BLI_listbase.h"
#include "BLI_rect.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "ED_screen.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_footer_intern.hh"
#include "mixie_chat_ink_intern.hh"
#include "mixie_chat_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Shared Helpers
 * \{ */

static SpaceMixieChat *ink_space_from_area(ScrArea *area)
{
  /* SPACE_AGENT_BUBBLE reuses these callbacks via its layout-compatible
   * spacedata struct (same as the rules/history overlays). */
  if (!area || !area->spacedata.first ||
      (area->spacetype != SPACE_MIXIE_CHAT && area->spacetype != SPACE_AGENT_BUBBLE))
  {
    return nullptr;
  }
  return static_cast<SpaceMixieChat *>(area->spacedata.first);
}

static ARegion *ink_area_main_region(ScrArea *area)
{
  for (ARegion &region_ref : area->regionbase) {
    ARegion *region = &region_ref;
    if (region->regiontype == RGN_TYPE_WINDOW) {
      return region;
    }
  }
  return nullptr;
}

static int ink_completed_stroke_count(const MixieChatRuntime *rt)
{
  return rt->ink_stroke_count - (rt->ink_stroke_live ? 1 : 0);
}

/** Open the canvas: pre-latch the runtime so the very next event (often
 * the seeding press itself) already captures. */
static void ink_open_for_area(bContext *C, ScrArea *area, MixieChatRuntime *rt)
{
  mixie_chat_ink_begin_session(rt);
  rt->ink_overlay_active = true;
  mixie_chat_ink_set_visible(C, true);
  if (ARegion *main_region = ink_area_main_region(area)) {
    ED_region_tag_redraw(main_region);
  }
}

/** Event-side open that also force-exits any active composer text-edit:
 * the footer text button holds a private edit buffer that would clobber
 * recognized-text appends on its next apply (its per-keystroke
 * TEXTEDIT_UPDATE writes mean cancel loses nothing). NOT for use from
 * inside the text-edit handler itself — freeing the active button there
 * is a use-after-free; that path exits via BUTTON_STATE_EXIT instead
 * (see mixie_chat_ink_composer_stylus_open). */
static void ink_open_from_event(bContext *C, ScrArea *area, MixieChatRuntime *rt)
{
  for (ARegion &region_ref : area->regionbase) {
    ARegion *region = &region_ref;
    if (region->regiontype == RGN_TYPE_TOOLS) {
      ui::UI_region_free_active_but_all(C, region);
    }
  }
  ink_open_for_area(C, area, rt);
}

/** Commit pending strokes on EVERY chat surface, then close. The
 * visibility bool is WM-global — the docked chat and the Agent Bubble
 * latch the canvas together, so a close from either must flush both or
 * the other surface's writing dies at its draw closing edge. */
static void ink_flush_and_close(bContext *C, MixieChatRuntime * /*rt*/)
{
  mixie_chat_ink_flush_all_surfaces(C);
  mixie_chat_ink_set_visible(C, false);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Hover (region cursor callback)
 * \{ */

bool mixie_chat_ink_cursor(
    wmWindow *win, MixieChatRuntime *rt, ARegion *region, float mouse_x, float mouse_y)
{
  if (!rt->ink_overlay_active) {
    return false;
  }
  bool needs_redraw = false;

  const bool close_hovered = BLI_rctf_isect_pt(&rt->ink_close_bounds, mouse_x, mouse_y);
  needs_redraw |= (close_hovered != rt->ink_close_hovered);
  rt->ink_close_hovered = close_hovered;

  const bool clear_hovered = BLI_rctf_isect_pt(&rt->ink_clear_bounds, mouse_x, mouse_y);
  needs_redraw |= (clear_hovered != rt->ink_clear_hovered);
  rt->ink_clear_hovered = clear_hovered;

  if (needs_redraw) {
    ED_region_tag_redraw(region);
  }
  WM_cursor_set(win, (close_hovered || clear_hovered) ? WM_CURSOR_HAND : WM_CURSOR_PAINT);
  return true; /* Overlay is modal — suppress hover on elements behind it. */
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Events (checked first in the region UI handler)
 * \{ */

bool mixie_chat_ink_handle_event(bContext *C, const wmEvent *event)
{
  ScrArea *area = CTX_wm_area(C);
  ARegion *region = CTX_wm_region(C);
  SpaceMixieChat *smixie = ink_space_from_area(area);
  if (!smixie || !region) {
    return false;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);

  /* Idle-commit tick: convert once the pen rested long enough. Runs even
   * before the active check below fails — timer events are "always pass",
   * and the canvas may have pending ink while the pointer sits here. The
   * timer is removed ONLY when the overlay is globally closed: a local
   * "this surface is empty" check would kill the shared timer while a
   * sibling chat area still holds pending ink (WM-global visibility means
   * every surface latches the canvas together). */
  if (mixie_chat_ink_idle_timer_matches(event)) {
    if (rt->ink_overlay_active && !rt->ink_stroke_live && ink_completed_stroke_count(rt) > 0 &&
        (BLI_time_now_seconds() - rt->ink_last_penup_time) >= INK_IDLE_COMMIT_SEC)
    {
      mixie_chat_ink_commit(C, region, rt);
    }
    wmWindowManager *wm = CTX_wm_manager(C);
    if (!mixie_chat_ink_read_visible(wm)) {
      mixie_chat_ink_idle_timer_remove(wm);
    }
    return false; /* Timer events pass through regardless. */
  }

  if (!rt->ink_overlay_active) {
    return false;
  }

  if (ISKEYBOARD(event->type)) {
    if (event->val != KM_PRESS) {
      return true; /* Consume releases too — the overlay is modal. */
    }
    switch (event->type) {
      case EVT_ESCKEY:
        ink_flush_and_close(C, rt);
        return true;
      case EVT_RETKEY:
      case EVT_PADENTER:
        /* Convert now, stay open for more writing. */
        if (ink_completed_stroke_count(rt) > 0) {
          mixie_chat_ink_commit(C, region, rt);
        }
        return true;
      default:
        return true; /* Modal: no key press leaks to the chat behind it. */
    }
  }

  const float mx = float(event->mval[0]);
  const float my = float(event->mval[1]);

  if (ELEM(event->type, MOUSEMOVE, INBETWEEN_MOUSEMOVE)) {
    if (rt->ink_stroke_live) {
      /* Missed-release recovery: a pen that lifts OUTSIDE the region
       * (descender dragged over the footer) never delivers its release
       * here. A genuine hover sample reports pressure 0.0 on Wintab /
       * Windows Ink — treat it as the pen-up. (macOS may carry a stale
       * cached pressure on hover; the press-recovery below still ends
       * the stroke there.) */
      if (WM_event_is_tablet(event) && event->tablet.pressure <= 0.0f) {
        mixie_chat_ink_stroke_end(rt);
        mixie_chat_ink_idle_timer_ensure(C);
        ED_region_tag_redraw(region);
        return true;
      }
      mixie_chat_ink_stroke_extend(rt, mx, my, event->tablet.pressure);
      ED_region_tag_redraw(region);
      return true;
    }
    return false; /* Hover is the cursor callback's job. */
  }

  if (event->type == LEFTMOUSE && event->val == KM_PRESS) {
    if (rt->ink_stroke_live) {
      /* A fresh press while a stroke is still latched means its release
       * was missed (it landed outside the region) — close it out first. */
      mixie_chat_ink_stroke_end(rt);
      mixie_chat_ink_idle_timer_ensure(C);
    }
    if (BLI_rctf_isect_pt(&rt->ink_close_bounds, mx, my)) {
      ink_flush_and_close(C, rt);
      return true;
    }
    if (BLI_rctf_isect_pt(&rt->ink_clear_bounds, mx, my)) {
      /* Clear drops UNCONVERTED ink only (already-committed batches are
       * in flight or in the composer). */
      rt->ink_point_count = 0;
      rt->ink_stroke_count = 0;
      rt->ink_stroke_live = false;
      rt->ink_store_full = false;
      ED_region_tag_redraw(region);
      return true;
    }
    if (mixie_chat_ink_stroke_begin(rt, mx, my, event->tablet.pressure)) {
      ED_region_tag_redraw(region);
    }
    return true;
  }

  if (event->type == LEFTMOUSE && event->val == KM_RELEASE) {
    if (rt->ink_stroke_live) {
      mixie_chat_ink_stroke_end(rt);
      mixie_chat_ink_idle_timer_ensure(C);
      ED_region_tag_redraw(region);
      return true;
    }
    return false;
  }

  if (ELEM(event->type, WHEELUPMOUSE, WHEELDOWNMOUSE, MOUSEPAN)) {
    return true; /* Modal: the chat must not scroll under the canvas. */
  }

  return false;
}

/** Step 8 of mixie_chat_ui_handler: a stylus press that hit no interactive
 * chat target starts handwriting — pen users write, they don't drag-select
 * transcript text. Mouse presses keep the existing select/scroll behavior. */
bool mixie_chat_ink_try_auto_open(bContext *C, const wmEvent *event)
{
  if (event->tablet.active != EVT_TABLET_STYLUS) {
    return false;
  }
  ScrArea *area = CTX_wm_area(C);
  ARegion *region = CTX_wm_region(C);
  SpaceMixieChat *smixie = ink_space_from_area(area);
  if (!smixie || !region || !mixie_chat_ink_feature_available(CTX_wm_manager(C))) {
    return false;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  if (rt->ink_overlay_active) {
    return false; /* Already open — the ink handler owns presses. */
  }
  ink_open_from_event(C, area, rt);
  mixie_chat_ink_stroke_begin(
      rt, float(event->mval[0]), float(event->mval[1]), event->tablet.pressure);
  ED_region_tag_redraw(region);
  return true;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Footer Composer Intercept (footer region UI handler)
 *
 * The iPadOS gesture: pen-touch the text field to write. A stylus press
 * on the composer input box opens the ink canvas instead of entering
 * text-edit. While the canvas is open, ALL presses on the input box are
 * consumed — entering text-edit mid-scribble would clobber recognized
 * appends with the button's stale private edit buffer.
 * \{ */

static bool ink_footer_input_rect(const bContext *C, ARegion *region, rctf *r_rect)
{
  Scene *scene = CTX_data_scene(const_cast<bContext *>(C));
  if (!scene) {
    return false;
  }
  const FooterThemeCache *theme = footer_cache_get_theme();
  const int pending_count = footer_cache_get_attachment_count(scene);
  const int input_lines = footer_layout_get_input_line_count(scene, region->winx);
  const int mention_rows = mixie_chat_mention_row_count(scene);
  FooterElementPositions pos;
  footer_layout_calculate_positions(
      region->winx, pending_count, theme, &pos, input_lines, mention_rows);
  if (pos.input_w <= 0) {
    return false;
  }
  BLI_rctf_init(r_rect,
                float(pos.input_x),
                float(pos.input_x + pos.input_w),
                float(pos.input_y),
                float(pos.input_y + pos.input_height));
  return true;
}

static int mixie_chat_ink_footer_ui_handler(bContext *C, const wmEvent *event, void * /*userdata*/)
{
  ScrArea *area = CTX_wm_area(C);
  ARegion *region = CTX_wm_region(C);
  SpaceMixieChat *smixie = ink_space_from_area(area);
  if (!smixie || !region || region->regiontype != RGN_TYPE_TOOLS) {
    return WM_UI_HANDLER_CONTINUE;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);

  /* The idle-commit timer must also fire while the pointer rests over the
   * composer — commonly where a pen hovers between words. Removal follows
   * the same rule as the main-region branch: only when the overlay is
   * globally closed (a sibling surface may still hold pending ink). */
  if (mixie_chat_ink_idle_timer_matches(event)) {
    ARegion *main_region = ink_area_main_region(area);
    if (main_region && rt->ink_overlay_active && !rt->ink_stroke_live &&
        ink_completed_stroke_count(rt) > 0 &&
        (BLI_time_now_seconds() - rt->ink_last_penup_time) >= INK_IDLE_COMMIT_SEC)
    {
      mixie_chat_ink_commit(C, main_region, rt);
    }
    wmWindowManager *wm = CTX_wm_manager(C);
    if (!mixie_chat_ink_read_visible(wm)) {
      mixie_chat_ink_idle_timer_remove(wm);
    }
    return WM_UI_HANDLER_CONTINUE;
  }

  if (event->type != LEFTMOUSE || event->val != KM_PRESS) {
    return WM_UI_HANDLER_CONTINUE;
  }

  rctf input_rect;
  if (!ink_footer_input_rect(C, region, &input_rect) ||
      !BLI_rctf_isect_pt(&input_rect, float(event->mval[0]), float(event->mval[1])))
  {
    return WM_UI_HANDLER_CONTINUE;
  }

  if (rt->ink_overlay_active) {
    return WM_UI_HANDLER_BREAK; /* No text-edit while the canvas is open. */
  }
  if (event->tablet.active == EVT_TABLET_STYLUS &&
      mixie_chat_ink_feature_available(CTX_wm_manager(C)))
  {
    ink_open_from_event(C, area, rt);
    return WM_UI_HANDLER_BREAK;
  }
  return WM_UI_HANDLER_CONTINUE;
}

/** Called from ui_do_but_textedit in the overlaid interface_handlers.cc:
 * a stylus press on the composer WHILE ITS TEXT-EDIT IS ACTIVE never
 * reaches the footer region handler (the active button's window-level
 * modal handler consumes it first), so the text-edit hook opens the
 * canvas itself and then exits editing via BUTTON_STATE_EXIT — which is
 * also why this variant must NOT free the active button. Returns true
 * when the canvas opened. */
bool mixie_chat_ink_composer_stylus_open(bContext *C)
{
  ScrArea *area = CTX_wm_area(C);
  SpaceMixieChat *smixie = ink_space_from_area(area);
  if (!smixie || !mixie_chat_ink_feature_available(CTX_wm_manager(C))) {
    return false;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  if (rt->ink_overlay_active) {
    return false;
  }
  ink_open_for_area(C, area, rt);
  return true;
}

static void mixie_chat_ink_footer_ui_handler_remove(bContext * /*C*/, void * /*userdata*/)
{
  /* Nothing to free. */
}

void mixie_chat_ink_footer_handler_register(ARegion *region)
{
  WM_event_remove_ui_handler(&region->runtime->handlers,
                             mixie_chat_ink_footer_ui_handler,
                             mixie_chat_ink_footer_ui_handler_remove,
                             nullptr,
                             false);
  WM_event_add_ui_handler(nullptr,
                          &region->runtime->handlers,
                          mixie_chat_ink_footer_ui_handler,
                          mixie_chat_ink_footer_ui_handler_remove,
                          nullptr,
                          eWM_EventHandlerFlag(0));
}

/** \} */

}  // namespace blender
