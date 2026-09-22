/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Sliding moodboard drawer: state, geometry and region lifecycle. Operators,
 * keymap and QA live in `view3d_moodboard_drawer_ops.cc`; painting lives in
 * `view3d_moodboard_drawer_draw.cc`.
 */

#include <algorithm>
#include <cmath>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_math_base.h"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "DNA_workspace_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"
#include "UI_view2d.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_moodboard_drawer.hh"
#include "mixie_moodboard_canvas.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name State
 * \{ */

/* Property accessors live in `view3d_moodboard_drawer_state.cc`. */

static MoodboardDrawerRuntime *drawer_runtime(const bContext *C)
{
  ARegion *region = view3d_moodboard_drawer_region_from_context(C);
  return region != nullptr ? static_cast<MoodboardDrawerRuntime *>(region->regiondata) :
                             nullptr;
}

static void drawer_tick_timer_ensure(const bContext *C, MoodboardDrawerRuntime *runtime)
{
  if (runtime->tick_timer != nullptr) {
    return;
  }
  wmWindowManager *wm = CTX_wm_manager(C);
  wmWindow *win = CTX_wm_window(C);
  if (wm != nullptr && win != nullptr) {
    runtime->tick_timer = WM_event_timer_add(wm, win, TIMERNOTIFIER, 1.0 / 60.0);
  }
}

static void drawer_tick_timer_remove(wmWindowManager *wm, MoodboardDrawerRuntime *runtime)
{
  if (runtime == nullptr || runtime->tick_timer == nullptr) {
    return;
  }
  if (wm != nullptr) {
    WM_event_timer_remove(wm, runtime->tick_timer->win, runtime->tick_timer);
  }
  runtime->tick_timer = nullptr;
}

static float drawer_ease_out_cubic(const float t)
{
  const float inv = 1.0f - std::clamp(t, 0.0f, 1.0f);
  return 1.0f - inv * inv * inv;
}

float view3d_moodboard_drawer_display_amount(const bContext *C)
{
  const float rna = view3d_moodboard_drawer_amount(C);
  const MoodboardDrawerRuntime *runtime = drawer_runtime(C);
  if (runtime == nullptr || runtime->slide_held || runtime->slide_started_at <= 0.0) {
    return rna;
  }
  const float target = view3d_moodboard_drawer_target(C) != 0 ? 1.0f : 0.0f;
  const float t = float((BLI_time_now_seconds() - runtime->slide_started_at) /
                        double(VIEW3D_MOODBOARD_DRAWER_SLIDE_SECONDS));
  if (t >= 1.0f) {
    return target;
  }
  return runtime->slide_start_amount +
         (target - runtime->slide_start_amount) * drawer_ease_out_cubic(t);
}

void view3d_moodboard_drawer_slide_begin(bContext *C)
{
  MoodboardDrawerRuntime *runtime = drawer_runtime(C);
  if (runtime == nullptr) {
    return;
  }
  runtime->slide_held = false;
  runtime->slide_start_amount = view3d_moodboard_drawer_display_amount(C);
  runtime->slide_started_at = BLI_time_now_seconds();
  drawer_tick_timer_ensure(C, runtime);
}

void view3d_moodboard_drawer_slide_stop(bContext *C)
{
  MoodboardDrawerRuntime *runtime = drawer_runtime(C);
  if (runtime != nullptr) {
    runtime->slide_started_at = 0.0;
    runtime->slide_held = false;
    drawer_tick_timer_remove(CTX_wm_manager(C), runtime);
  }
}

void view3d_moodboard_drawer_slide_hold(bContext *C)
{
  MoodboardDrawerRuntime *runtime = drawer_runtime(C);
  if (runtime != nullptr) {
    runtime->slide_held = true;
    runtime->slide_started_at = 0.0;
    drawer_tick_timer_remove(CTX_wm_manager(C), runtime);
  }
}

bool view3d_moodboard_drawer_zen_active(const bContext *C)
{
  return view3d_moodboard_drawer_workspace_is_zen(CTX_wm_workspace(C));
}

/* The region poll's answer without a context: the workspace of the window
 * whose active screen holds `area`. SpaceType.init gets only (wm, area). */
static bool drawer_area_in_zen_workspace(wmWindowManager *wm, const ScrArea *area)
{
  if (wm == nullptr || area == nullptr) {
    return false;
  }
  for (wmWindow &win : wm->windows) {
    const bScreen *screen = WM_window_get_active_screen(&win);
    if (screen == nullptr || BLI_findindex(&screen->areabase, area) == -1) {
      continue;
    }
    return view3d_moodboard_drawer_workspace_is_zen(WM_window_get_active_workspace(&win));
  }
  return false;
}

bool view3d_moodboard_drawer_canvas_is_active(const ARegion *region)
{
  if (region == nullptr || region->regiontype != RGN_TYPE_TOOL_PROPS) {
    return false;
  }
  const MoodboardDrawerRuntime *runtime =
      static_cast<const MoodboardDrawerRuntime *>(region->regiondata);
  return runtime != nullptr && runtime->amount >= VIEW3D_MOODBOARD_DRAWER_CANVAS_MIN_AMOUNT;
}

bool view3d_moodboard_drawer_canvas_handler_poll(const wmWindow *win,
                                                const ScrArea *area,
                                                const ARegion *region,
                                                const wmEvent *event)
{
  /* The shared poll owns pointer bounds and preserves mouse-leave/timer
   * delivery. A second current-position check would discard those events. */
  return area && area->spacetype == SPACE_VIEW3D &&
         view3d_moodboard_drawer_canvas_is_active(region) &&
         ed::mixie::moodboard_canvas_handler_poll(win, area, region, event);
}

bool view3d_moodboard_drawer_grip_handler_poll(const wmWindow * /*win*/,
                                              const ScrArea *area,
                                              const ARegion *region,
                                              const wmEvent *event)
{
  if (event == nullptr || area == nullptr || area->spacetype != SPACE_VIEW3D) {
    return false;
  }
  return view3d_moodboard_drawer_resize_contains_xy(area, region, event->xy);
}

static void drawer_region_cursor(wmWindow *win, ScrArea *area, ARegion *region)
{
  const wmEvent *event = win->runtime->eventstate;
  const bool resize = event &&
                      view3d_moodboard_drawer_resize_contains_xy(area, region, event->xy);
  WM_cursor_set(win, resize ? WM_CURSOR_X_MOVE : WM_CURSOR_DEFAULT);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Geometry
 * \{ */

ARegion *view3d_moodboard_drawer_region_find(const ScrArea *area)
{
  if (area == nullptr || area->spacetype != SPACE_VIEW3D) {
    return nullptr;
  }
  return BKE_area_find_region_type(const_cast<ScrArea *>(area), RGN_TYPE_TOOL_PROPS);
}

bool view3d_moodboard_drawer_grip_rect(const bContext *C, rcti *r_rect)
{
  const ScrArea *area = CTX_wm_area(C);
  if (area == nullptr || !view3d_moodboard_drawer_zen_active(C)) {
    return false;
  }
  return view3d_moodboard_drawer_grip_rect_for(
      area, view3d_moodboard_drawer_region_find(area), view3d_moodboard_drawer_amount(C), r_rect);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Region lifecycle
 * \{ */

static void drawer_region_listener(const wmRegionListenerParams *params)
{
  /* Tag here: `wm_draw.cc` wipes a redraw tagged from inside the draw pass. */
  const MoodboardDrawerRuntime *runtime =
      static_cast<const MoodboardDrawerRuntime *>(params->region->regiondata);
  if (runtime != nullptr && runtime->slide_started_at > 0.0) {
    ED_region_tag_redraw(params->region);
    /* Keep navigation gizmos in step with display_amount without a 3D rebuild. */
    if (ARegion *window = BKE_area_find_region_type(params->area, RGN_TYPE_WINDOW)) {
      ED_region_tag_redraw_editor_overlays(window);
    }
  }
  const wmNotifier *notifier = params->notifier;
  if ((notifier->category == NC_SPACE && notifier->data == ND_SPACE_MIXIE) ||
      ELEM(notifier->category, NC_SCENE, NC_IMAGE, NC_WM))
  {
    ED_region_tag_redraw(params->region);
  }
}

static bool drawer_region_poll(const RegionPollParams *params)
{
  /* The region exists for as long as the drawer *could* be shown, not for as
   * long as it is open: the grip is painted and clicked on this region, and a
   * region that polls out draws nothing. Panels re-run polls only on a screen
   * refresh, which a redraw tag is not, so anything this poll reads must be
   * cheap — one workspace compare, no RNA walk of a collection. */
  return view3d_moodboard_drawer_zen_active(params->context);
}

void view3d_moodboard_drawer_toggle_handlers_add(wmWindowManager *wm, ARegion *region)
{
  wmKeyMap *keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "Moodboard Drawer", SPACE_VIEW3D, RGN_TYPE_WINDOW);
  WM_event_add_keymap_handler_priority(&region->runtime->handlers, keymap, 0);
}

void view3d_moodboard_drawer_region_init(wmWindowManager *wm, ARegion *region)
{
  view3d_moodboard_drawer_size_sync(wm, nullptr, region);

  if (region->regiondata == nullptr) {
    MoodboardDrawerRuntime *runtime = MEM_new<MoodboardDrawerRuntime>("moodboard drawer runtime");
    /* The grip's hit rect reads `runtime->amount`, which only the draw pass
     * writes. Fresh regiondata (a workspace round trip re-inits the region)
     * left it at 0 while the WM property still said open, so the tab painted
     * open and the click landed on the shut position until one draw ran. */
    runtime->amount = std::clamp(view3d_moodboard_drawer_amount_wm(wm), 0.0f, 1.0f);
    region->regiondata = runtime;
  }

  const bool is_first_init = (region->v2d.cur.xmax - region->v2d.cur.xmin) < 1.0f;
  rctf saved_cur = region->v2d.cur;
  const int previous_width = region->v2d.winx;
  if (!is_first_init && previous_width > 0) {
    /* Expanding left reveals more board at the same zoom and right edge. */
    saved_cur.xmin = saved_cur.xmax - BLI_rctf_size_x(&saved_cur) *
                                        float(region->winx) / float(previous_width);
  }

  ui::view2d_region_reinit(&region->v2d, ui::V2D_COMMONVIEW_CUSTOM, region->winx, region->winy);

  region->v2d.tot.xmin = -10000.0f;
  region->v2d.tot.ymin = -10000.0f;
  region->v2d.tot.xmax = 10000.0f;
  region->v2d.tot.ymax = 10000.0f;

  if (is_first_init) {
    region->v2d.cur.xmin = -500.0f;
    region->v2d.cur.ymin = -500.0f;
    region->v2d.cur.xmax = 500.0f;
    region->v2d.cur.ymax = 500.0f;
  }
  else {
    region->v2d.cur = saved_cur;
  }

  region->v2d.min[0] = 1.0f;
  region->v2d.min[1] = 1.0f;
  region->v2d.max[0] = 32000.0f;
  region->v2d.max[1] = 32000.0f;
  region->v2d.minzoom = 0.05f;
  region->v2d.maxzoom = 21.0f;
  /* No scrollers: this region spans the viewport's right band in BOTH states
   * (closing is a paint translation), so `AZONE_REGION_SCROLL` would claim
   * presses there while shut, for a thumb `tot`'s fixed box cannot inform. */
  region->v2d.scroll = eView2D_Scroll(0);
  region->v2d.keepzoom = V2D_LIMITZOOM;
  region->v2d.keeptot = V2D_KEEPTOT_FREE;
  const float half_height = 0.5f * BLI_rctf_size_x(&region->v2d.cur) *
                            float(region->winy) / std::max(int(region->winx), 1);
  const float center_y = BLI_rctf_cent_y(&region->v2d.cur);
  region->v2d.cur.ymin = center_y - half_height;
  region->v2d.cur.ymax = center_y + half_height;

  /* UI handlers prepend themselves. Put the resize keymap ahead of them so
   * clipped canvas buttons cannot swallow the sash. The operator's invoke
   * passes through outside the shared grip/edge geometry. */
  ui::region_handlers_add(&region->runtime->handlers);
  wmKeyMap *grip_keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "Moodboard Drawer Grip", SPACE_VIEW3D, RGN_TYPE_TOOL_PROPS);
  WM_event_add_keymap_handler_priority(&region->runtime->handlers, grip_keymap, 0);
  view3d_moodboard_drawer_toggle_handlers_add(wm, region);

  wmKeyMap *mixie_keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "Mixie", SPACE_MIXIE, RGN_TYPE_WINDOW);
  WM_event_add_keymap_handler_poll(&region->runtime->handlers,
                                   mixie_keymap,
                                   view3d_moodboard_drawer_canvas_handler_poll);

  wmKeyMap *view2d_keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "View2D", SPACE_EMPTY, RGN_TYPE_WINDOW);
  WM_event_add_keymap_handler_poll(&region->runtime->handlers,
                                   view2d_keymap,
                                   view3d_moodboard_drawer_canvas_handler_poll);

  ListBaseT<wmDropBox> *dropboxes = WM_dropboxmap_find("Mixie", SPACE_MIXIE, RGN_TYPE_WINDOW);
  if (dropboxes != nullptr) {
    WM_event_add_dropbox_handler(
        static_cast<ListBaseT<wmEventHandler> *>(&region->runtime->handlers), dropboxes);
  }

  /* A newly polled-in region draws only when something tags it. */
  ED_region_tag_redraw(region);
}

static void drawer_region_free(ARegion *region)
{
  /* Exit already dropped the WM timer; null it so a stale pointer cannot be
   * removed twice. `RGN_FLAG_TEMP_REGIONDATA` then frees these bytes. */
  if (region->regiondata != nullptr) {
    MoodboardDrawerRuntime *runtime = static_cast<MoodboardDrawerRuntime *>(region->regiondata);
    runtime->tick_timer = nullptr;
    MEM_delete(runtime);
    region->regiondata = nullptr;
  }
}

void view3d_moodboard_drawer_region_exit(wmWindowManager *wm, ARegion *region)
{
  if (MoodboardDrawerRuntime *runtime =
          static_cast<MoodboardDrawerRuntime *>(region->regiondata))
  {
    drawer_tick_timer_remove(wm, runtime);
  }
  drawer_region_free(region);
}

void view3d_moodboard_drawer_region_register(SpaceType *st)
{
  ARegionType *art = MEM_new_zeroed<ARegionType>("spacetype view3d moodboard drawer region");
  art->regionid = RGN_TYPE_TOOL_PROPS;
  art->prefsizex = VIEW3D_MOODBOARD_DRAWER_WIDTH;
  art->keymapflag = 0;
  art->poll = drawer_region_poll;
  art->listener = drawer_region_listener;
  art->init = view3d_moodboard_drawer_region_init;
  art->draw = view3d_moodboard_drawer_region_draw;
  art->exit = view3d_moodboard_drawer_region_exit;
  art->free = drawer_region_free;
  art->cursor = drawer_region_cursor;
  art->event_cursor = true;
  BLI_addhead(&st->regiontypes, art);
}

void view3d_moodboard_drawer_region_ensure(wmWindowManager *wm, ScrArea *area)
{
  if (!area || area->spacetype != SPACE_VIEW3D) {
    return;
  }

  ARegion *window_region = BKE_area_find_region_type(area, RGN_TYPE_WINDOW);
  if (ARegion *existing = BKE_area_find_region_type(area, RGN_TYPE_TOOL_PROPS)) {
    if (window_region && existing->next != window_region) {
      BLI_remlink(&area->regionbase, existing);
      BLI_insertlinkbefore(&area->regionbase, window_region, existing);
    }
    view3d_moodboard_drawer_size_sync(wm, area, existing);
    return;
  }

  ARegion *region = BKE_area_region_new();
  if (window_region) {
    BLI_insertlinkbefore(&area->regionbase, window_region, region);
  }
  else {
    BLI_addtail(&area->regionbase, region);
  }
  region->regiontype = RGN_TYPE_TOOL_PROPS;

  region->alignment = RGN_ALIGN_RIGHT;
  region->sizex = 0;
  region->flag |= RGN_FLAG_TEMP_REGIONDATA | RGN_FLAG_POLL_FAILED;
  region->runtime->type = BKE_regiontype_from_id(area->type, region->regiontype);

  /* `ED_area_init()` polled the regions and laid out their rects BEFORE the
   * space init that created this one, and nothing re-polls until the next
   * full screen refresh. A first-ever Zen Mode workspace therefore came up
   * with a poll-failed, zero-width drawer: no grip drawn, no grip to click
   * ("moodboard not opening on click") until a window resize or workspace
   * switch happened to refresh the screen. Answer the poll here with the
   * same workspace test, size the region, and ask for the region-size pass
   * that runs before the first draw so this very refresh lays it out. */
  if (drawer_area_in_zen_workspace(wm, area)) {
    region->flag &= ~RGN_FLAG_POLL_FAILED;
  }
  view3d_moodboard_drawer_size_sync(wm, area, region);
  area->flag |= AREA_FLAG_REGION_SIZE_UPDATE;
}

/** \} */

}  // namespace blender
