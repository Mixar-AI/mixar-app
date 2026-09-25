/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Sliding Scenes drawer for Zen Mode: the list of scene tabs (one Blender
 * Scene + one agent chat each), hosted in an overlapping region docked to the
 * LEFT edge of the 3D View and slid in and out by a grip on that edge. The
 * mirror image of the moodboard drawer (`view3d_moodboard_drawer.hh`), whose
 * mechanics it copies: WindowManager-owned amount / target / width, a
 * wall-clock ease painted through TIMERNOTIFIER, a grip that toggles on click
 * and resizes on drag, and event routing through
 * `view3d_scenes_drawer_contains_xy` so only the grip, the resize sash and the
 * painted panel belong to this region.
 *
 * What it paints comes from Python (`wm.mixar_scene_tabs`, refreshed by
 * `space_mixie_chat/ui/properties/scene_tabs_props.py`); what a click does is a
 * Python operator (`mixie_chat.new_scene_tab` / `switch_scene_tab` /
 * `close_scene_tab`). C owns pixels and hit geometry only.
 */

#pragma once

#include "BLI_listbase_iterator.hh"
#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "DNA_workspace_types.h"

#include "ED_scenes_drawer.hh"

#include "WM_api.hh"

struct ARegion;
struct Scene;
struct View3D;
struct ARegionType;
struct ScrArea;
struct SpaceType;
struct bContext;
struct wmEvent;
struct wmKeyConfig;
struct wmWindow;
struct wmWindowManager;

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name State
 * \{ */

float view3d_scenes_drawer_amount(const bContext *C);
float view3d_scenes_drawer_amount_wm(const wmWindowManager *wm);
void view3d_scenes_drawer_amount_set(bContext *C, float amount);
float view3d_scenes_drawer_display_amount(const bContext *C);
void view3d_scenes_drawer_slide_begin(bContext *C);
void view3d_scenes_drawer_slide_stop(bContext *C);
void view3d_scenes_drawer_slide_hold(bContext *C);
int view3d_scenes_drawer_target(const bContext *C);
void view3d_scenes_drawer_target_set(bContext *C, int target);
bool view3d_scenes_drawer_zen_active(const bContext *C);
float view3d_scenes_drawer_width(wmWindowManager *wm);
void view3d_scenes_drawer_width_set(bContext *C, float width);
void view3d_scenes_drawer_size_sync(wmWindowManager *wm, ScrArea *area, ARegion *region);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Geometry
 * \{ */

ARegion *view3d_scenes_drawer_region_find(const ScrArea *area);

inline bool view3d_scenes_drawer_workspace_is_zen(const WorkSpace *workspace)
{
  return workspace != nullptr && STREQ(workspace->id.name + 2, "Zen Mode");
}

inline ScrArea *view3d_scenes_drawer_area_find(const bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return nullptr;
  }
  if (view3d_scenes_drawer_workspace_is_zen(CTX_wm_workspace(C))) {
    if (ScrArea *area = CTX_wm_area(C)) {
      if (view3d_scenes_drawer_region_find(area) != nullptr) {
        return area;
      }
    }
  }
  for (wmWindow &win : wm->windows) {
    if (!view3d_scenes_drawer_workspace_is_zen(WM_window_get_active_workspace(&win))) {
      continue;
    }
    const bScreen *screen = WM_window_get_active_screen(&win);
    if (screen == nullptr) {
      continue;
    }
    for (ScrArea &area : screen->areabase) {
      if (view3d_scenes_drawer_region_find(&area) != nullptr) {
        return &area;
      }
    }
  }
  return nullptr;
}

inline ARegion *view3d_scenes_drawer_region_from_context(const bContext *C)
{
  if (ARegion *region = view3d_scenes_drawer_region_find(CTX_wm_area(C))) {
    return region;
  }
  return view3d_scenes_drawer_region_find(view3d_scenes_drawer_area_find(C));
}

bool view3d_scenes_drawer_grip_rect(const bContext *C, rcti *r_rect);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Region lifecycle
 * \{ */

void view3d_scenes_drawer_region_init(wmWindowManager *wm, ARegion *region);
void view3d_scenes_drawer_region_exit(wmWindowManager *wm, ARegion *region);
void view3d_scenes_drawer_region_draw(const bContext *C, ARegion *region);

/** True once the last drawn amount is high enough that the cards take clicks. */
bool view3d_scenes_drawer_is_open(const ARegion *region);

bool view3d_scenes_drawer_grip_handler_poll(const wmWindow *win,
                                            const ScrArea *area,
                                            const ARegion *region,
                                            const wmEvent *event);

void view3d_scenes_drawer_region_register(SpaceType *st);

/** Thumbnails (`view3d_scenes_drawer_thumbs.cc`). */
void view3d_scenes_drawer_thumb_render(ScenesDrawerThumb &thumb, Scene *scene, const View3D *host,
                                       int width, int height, double min_interval);
void view3d_scenes_drawer_thumb_free(ScenesDrawerThumb &thumb);
void view3d_scenes_drawer_region_ensure(wmWindowManager *wm, ScrArea *area);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operators, keymap, QA
 * \{ */

/** `view3d.scenes_drawer_{update,reveal,toggle,set,grip,click}`. */
void view3d_scenes_drawer_operatortypes();
void view3d_scenes_drawer_keymap(wmKeyConfig *keyconf);
/** Attach the Ctrl+` toggle map. Call first on View3D WINDOW and the drawer. */
void view3d_scenes_drawer_toggle_handlers_add(wmWindowManager *wm, ARegion *region);
void view3d_scenes_drawer_qa_targets_register();

/** \} */

}  // namespace blender
