/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Sliding Scenes drawer: state, geometry and region lifecycle. Operators,
 * keymap and QA live in `view3d_scenes_drawer_ops.cc`; painting lives in
 * `view3d_scenes_drawer_draw.cc`; the region's width follows the slide in
 * `view3d_scenes_drawer_resize.cc`.
 */

#include <algorithm>
#include <cmath>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_listbase_iterator.hh"
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

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_scenes_drawer.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name State
 * \{ */

ScenesDrawerRuntime *view3d_scenes_drawer_runtime_ensure(wmWindowManager *wm, ARegion *region)
{
  if (region == nullptr) {
    return nullptr;
  }
  if (region->regiondata == nullptr) {
    ScenesDrawerRuntime *runtime = MEM_new<ScenesDrawerRuntime>("scenes drawer runtime");
    /* Hit tests read `runtime->amount`, which only the draw pass writes; seed
     * it from the WM property so a re-init (workspace round trip) cannot leave
     * the cards painted open while the click lands shut. */
    runtime->amount = std::clamp(view3d_scenes_drawer_amount_wm(wm), 0.0f, 1.0f);
    region->regiondata = runtime;
  }
  return static_cast<ScenesDrawerRuntime *>(region->regiondata);
}

static ScenesDrawerRuntime *drawer_runtime(const bContext *C)
{
  return view3d_scenes_drawer_runtime_ensure(CTX_wm_manager(C),
                                             view3d_scenes_drawer_region_from_context(C));
}

static void drawer_tick_timer_ensure(const bContext *C, ScenesDrawerRuntime *runtime)
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

static void drawer_tick_timer_remove(wmWindowManager *wm, ScenesDrawerRuntime *runtime)
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

float view3d_scenes_drawer_display_amount(const bContext *C)
{
  const float rna = view3d_scenes_drawer_amount(C);
  const ScenesDrawerRuntime *runtime = drawer_runtime(C);
  if (runtime == nullptr || runtime->slide_started_at <= 0.0) {
    return rna;
  }
  const float target = view3d_scenes_drawer_target(C) != 0 ? 1.0f : 0.0f;
  const float t = float((BLI_time_now_seconds() - runtime->slide_started_at) /
                        double(VIEW3D_SCENES_DRAWER_SLIDE_SECONDS));
  if (t >= 1.0f) {
    return target;
  }
  return runtime->slide_start_amount +
         (target - runtime->slide_start_amount) * drawer_ease_out_cubic(t);
}

void view3d_scenes_drawer_slide_begin(bContext *C)
{
  ScenesDrawerRuntime *runtime = drawer_runtime(C);
  if (runtime == nullptr) {
    return;
  }
  runtime->slide_start_amount = view3d_scenes_drawer_display_amount(C);
  runtime->slide_started_at = BLI_time_now_seconds();
  drawer_tick_timer_ensure(C, runtime);
}

void view3d_scenes_drawer_slide_stop(bContext *C)
{
  ScenesDrawerRuntime *runtime = drawer_runtime(C);
  if (runtime != nullptr) {
    runtime->slide_started_at = 0.0;
    drawer_tick_timer_remove(CTX_wm_manager(C), runtime);
  }
}

bool view3d_scenes_drawer_zen_active(const bContext *C)
{
  return view3d_scenes_drawer_workspace_is_zen(CTX_wm_workspace(C));
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
    return view3d_scenes_drawer_workspace_is_zen(WM_window_get_active_workspace(&win));
  }
  return false;
}

bool view3d_scenes_drawer_is_open(const ARegion *region)
{
  if (region == nullptr || region->regiontype != VIEW3D_SCENES_DRAWER_REGION_TYPE) {
    return false;
  }
  const ScenesDrawerRuntime *runtime = static_cast<const ScenesDrawerRuntime *>(
      region->regiondata);
  return runtime != nullptr && runtime->amount >= VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT;
}

static bool drawer_card_contains_xy(const ScenesDrawerRuntime *runtime, const int xy[2])
{
  if (runtime == nullptr || runtime->amount < VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT) {
    return false;
  }
  if (runtime->new_visible && BLI_rcti_isect_pt_v(&runtime->new_rect, xy)) {
    return true;
  }
  for (const ScenesDrawerCard &card : runtime->cards) {
    if (BLI_rcti_isect_pt_v(&card.rect, xy)) {
      return true;
    }
  }
  return false;
}

static void drawer_region_cursor(wmWindow *win, ScrArea *area, ARegion *region)
{
  const wmEvent *event = win->runtime->eventstate;
  if (event && view3d_scenes_drawer_resize_contains_xy(area, region, event->xy)) {
    WM_cursor_set(win, WM_CURSOR_X_MOVE);
    return;
  }
  const ScenesDrawerRuntime *runtime = static_cast<const ScenesDrawerRuntime *>(
      region->regiondata);
  if (event && drawer_card_contains_xy(runtime, event->xy)) {
    WM_cursor_set(win, WM_CURSOR_HAND);
    return;
  }
  WM_cursor_set(win, WM_CURSOR_DEFAULT);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Geometry
 * \{ */

ARegion *view3d_scenes_drawer_region_find(const ScrArea *area)
{
  if (area == nullptr || area->spacetype != SPACE_VIEW3D) {
    return nullptr;
  }
  return BKE_area_find_region_type(const_cast<ScrArea *>(area),
                                   VIEW3D_SCENES_DRAWER_REGION_TYPE);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Region lifecycle
 * \{ */

static void drawer_region_listener(const wmRegionListenerParams *params)
{
  /* Tag here: `wm_draw.cc` wipes a redraw tagged from inside the draw pass. */
  ScenesDrawerRuntime *runtime = static_cast<ScenesDrawerRuntime *>(params->region->regiondata);
  if (runtime != nullptr && runtime->slide_started_at > 0.0) {
    ED_region_tag_redraw(params->region);
    if (ARegion *window = BKE_area_find_region_type(params->area, RGN_TYPE_WINDOW)) {
      ED_region_tag_redraw_editor_overlays(window);
    }
  }
  /* A thumbnail rendered in the last pass lands on screen only with another
   * draw; the pass queued an `ND_SPACE_SCENES_DRAWER` notifier to get here. */
  if (runtime != nullptr && runtime->redraw_pending) {
    runtime->redraw_pending = false;
    ED_region_tag_redraw(params->region);
  }
  const wmNotifier *notifier = params->notifier;
  /* Scene switches, chat state and the Python tab mirror all arrive as
   * scene / window-manager notifications; a repaint is one cheap RNA walk. */
  if (ELEM(notifier->category, NC_SCENE, NC_WM, NC_WINDOW, NC_SCREEN) ||
      (notifier->category == NC_SPACE &&
       ELEM(notifier->data, ND_SPACE_MIXIE, ND_SPACE_SCENES_DRAWER)))
  {
    ED_region_tag_redraw(params->region);
  }
}

static bool drawer_region_poll(const RegionPollParams *params)
{
  /* The region exists for as long as the drawer *could* be shown; shut, it is
   * hidden (zero width). One workspace compare, nothing else. */
  return view3d_scenes_drawer_zen_active(params->context);
}

void view3d_scenes_drawer_toggle_handlers_add(wmWindowManager *wm, ARegion *region)
{
  wmKeyMap *keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "Scenes Drawer", SPACE_VIEW3D, RGN_TYPE_WINDOW);
  WM_event_add_keymap_handler_priority(&region->runtime->handlers, keymap, 0);
}

void view3d_scenes_drawer_region_init(wmWindowManager *wm, ARegion *region)
{
  view3d_scenes_drawer_size_sync(wm, nullptr, region);
  view3d_scenes_drawer_runtime_ensure(wm, region);

  /* No View2D canvas: the cards are laid out from the region rect each draw.
   * The edge keymap goes first so nothing painted over it can swallow the
   * sash; the click map follows and passes through outside the cards. */
  wmKeyMap *grip_keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "Scenes Drawer Grip", SPACE_VIEW3D, VIEW3D_SCENES_DRAWER_REGION_TYPE);
  WM_event_add_keymap_handler_priority(&region->runtime->handlers, grip_keymap, 0);
  view3d_scenes_drawer_toggle_handlers_add(wm, region);

  ED_region_tag_redraw(region);
}

static void drawer_region_free(ARegion *region)
{
  if (region->regiondata != nullptr) {
    ScenesDrawerRuntime *runtime = static_cast<ScenesDrawerRuntime *>(region->regiondata);
    runtime->tick_timer = nullptr;
    for (auto &item : runtime->thumbs) {
      view3d_scenes_drawer_thumb_free(item.second);
    }
    runtime->thumbs.clear();
    MEM_delete(runtime);
    region->regiondata = nullptr;
  }
}

void view3d_scenes_drawer_region_exit(wmWindowManager *wm, ARegion *region)
{
  if (ScenesDrawerRuntime *runtime = static_cast<ScenesDrawerRuntime *>(region->regiondata)) {
    drawer_tick_timer_remove(wm, runtime);
  }
  drawer_region_free(region);
}

void view3d_scenes_drawer_region_register(SpaceType *st)
{
  ARegionType *art = MEM_new_zeroed<ARegionType>("spacetype view3d scenes drawer region");
  art->regionid = VIEW3D_SCENES_DRAWER_REGION_TYPE;
  art->prefsizex = VIEW3D_SCENES_DRAWER_WIDTH;
  art->keymapflag = 0;
  art->poll = drawer_region_poll;
  art->listener = drawer_region_listener;
  art->init = view3d_scenes_drawer_region_init;
  art->draw = view3d_scenes_drawer_region_draw;
  art->exit = view3d_scenes_drawer_region_exit;
  art->free = drawer_region_free;
  art->cursor = drawer_region_cursor;
  art->event_cursor = true;
  BLI_addhead(&st->regiontypes, art);
}

/** The first non-header region of the area: the drawer goes right before it,
 * after every header (the floating Zen toolbar clips the drawer's top). */
static ARegion *drawer_region_anchor(ScrArea *area)
{
  for (ARegion &region : area->regionbase) {
    if (region.regiontype == VIEW3D_SCENES_DRAWER_REGION_TYPE) {
      continue;
    }
    if (!ELEM(region.regiontype, RGN_TYPE_HEADER, RGN_TYPE_TOOL_HEADER, RGN_TYPE_FOOTER)) {
      return &region;
    }
  }
  return nullptr;
}

void view3d_scenes_drawer_region_ensure(wmWindowManager *wm, ScrArea *area)
{
  if (!area || area->spacetype != SPACE_VIEW3D) {
    return;
  }

  /* The drawer takes its width from the area BEFORE the overlapping regions
   * (TOOLS, UI, the parallel-agents band) are placed: `region_rect_recursive`
   * resets the overlap remainder only after a non-overlap region, so a drawer
   * listed after TOOLS left the transform pill at the area's edge, painted
   * over the cards. Anchor: the first region after the headers. */
  ARegion *anchor = drawer_region_anchor(area);
  if (ARegion *existing = BKE_area_find_region_type(area, VIEW3D_SCENES_DRAWER_REGION_TYPE)) {
    if (anchor && existing->next != anchor) {
      BLI_remlink(&area->regionbase, existing);
      BLI_insertlinkbefore(&area->regionbase, anchor, existing);
    }
    view3d_scenes_drawer_size_sync(wm, area, existing);
    return;
  }

  ARegion *region = BKE_area_region_new();
  if (anchor) {
    BLI_insertlinkbefore(&area->regionbase, anchor, region);
  }
  else {
    BLI_addtail(&area->regionbase, region);
  }
  region->regiontype = VIEW3D_SCENES_DRAWER_REGION_TYPE;

  region->alignment = RGN_ALIGN_LEFT;
  region->sizex = 0;
  /* The sash on the panel edge resizes it; Blender's own region-scale zone
   * (already refused in `region_azone_edge_poll`) must never fight it. */
  region->flag |= RGN_FLAG_TEMP_REGIONDATA | RGN_FLAG_POLL_FAILED | RGN_FLAG_NO_USER_RESIZE;
  region->runtime->type = BKE_regiontype_from_id(area->type, region->regiontype);

  /* Same first-layout answer as the moodboard drawer: poll and size the
   * region here so the very first Zen refresh lays it out. */
  if (drawer_area_in_zen_workspace(wm, area)) {
    region->flag &= ~RGN_FLAG_POLL_FAILED;
  }
  view3d_scenes_drawer_size_sync(wm, area, region);
  area->flag |= AREA_FLAG_REGION_SIZE_UPDATE;
}

/** \} */

}  // namespace blender
