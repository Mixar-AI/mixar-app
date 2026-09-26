/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Sliding Scenes drawer for Zen Mode: the list of scene tabs (one Blender
 * Scene + one agent chat each), hosted in a normal left-aligned region of the
 * 3D View that PUSHES the viewport right as it opens (the moodboard drawer on
 * the right edge is an overlay; this one is not). WindowManager-owned
 * amount / target / width; a wall-clock ease that the Python tick
 * (`scene_tabs_props._drawer_tick` → `view3d.scenes_drawer_update`) writes
 * into the region's size every frame; a toolbar button (`view3d.scenes_drawer_toggle`)
 * opens and closes it; a sash on the panel's right edge resizes it.
 *
 * What it paints comes from Python (`wm.mixar_scene_tabs`, refreshed by
 * `space_mixie_chat/ui/properties/scene_tabs_props.py`); what a click does is a
 * Python operator (`mixie_chat.new_scene_tab` / `switch_scene_tab` /
 * `close_scene_tab`). C owns pixels and hit geometry only.
 */

#pragma once

#include <string>

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
struct wmOperatorType;
struct Main;
struct PointerRNA;

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
int view3d_scenes_drawer_target(const bContext *C);
void view3d_scenes_drawer_target_set(bContext *C, int target);
bool view3d_scenes_drawer_zen_active(const bContext *C);
float view3d_scenes_drawer_width(wmWindowManager *wm);
/** The width the panel opens to, unscaled UI units, bounded by the area. */
float view3d_scenes_drawer_open_width(wmWindowManager *wm, const ScrArea *area);
void view3d_scenes_drawer_width_set(bContext *C, float width);
/** Region width = open width × slide amount; hidden while shut. Tags the
 * area's region layout when anything changed. */
void view3d_scenes_drawer_size_sync(wmWindowManager *wm, ScrArea *area, ARegion *region);
/** `size_sync` for the context's drawer, plus the hidden ↔ visible re-init.
 * Every writer of amount or width calls this; the draw pass never lays out. */
void view3d_scenes_drawer_layout_sync(bContext *C);
/** The region runtime, allocated on first use: a hidden region is never
 * initialised, yet the slide state lives on it. */
ScenesDrawerRuntime *view3d_scenes_drawer_runtime_ensure(wmWindowManager *wm, ARegion *region);

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

/** \} */

/* -------------------------------------------------------------------- */
/** \name Region lifecycle
 * \{ */

void view3d_scenes_drawer_region_init(wmWindowManager *wm, ARegion *region);
void view3d_scenes_drawer_region_exit(wmWindowManager *wm, ARegion *region);
void view3d_scenes_drawer_region_draw(const bContext *C, ARegion *region);

/** True once the last drawn amount is high enough that the cards take clicks. */
bool view3d_scenes_drawer_is_open(const ARegion *region);

void view3d_scenes_drawer_region_register(SpaceType *st);

/** Thumbnails (`view3d_scenes_drawer_thumbs.cc`). */
void view3d_scenes_drawer_thumb_render(ScenesDrawerThumb &thumb, Main *bmain, const wmWindowManager *wm,
                                       Scene *scene, const View3D *host, int w, int h,
                                       double min_interval);
void view3d_scenes_drawer_thumb_free(ScenesDrawerThumb &thumb);
void view3d_scenes_drawer_region_ensure(wmWindowManager *wm, ScrArea *area);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Draw widgets (`view3d_scenes_drawer_draw_widgets.cc`)
 * \{ */

namespace view3d_scenes_drawer {

void read_string(PointerRNA *ptr, const char *name, std::string &out);
int read_int(PointerRNA *ptr, const char *name, int fallback);
int read_enum(PointerRNA *ptr, const char *name, int fallback);
bool read_bool(PointerRNA *ptr, const char *name);
/** Pull the tab list Python keeps on the WindowManager into the runtime,
 * keeping the previous rects until this pass lays them out again. */
void sync_cards(const bContext *C, ScenesDrawerRuntime *runtime);
void with_alpha(const float src[4], float alpha, float r_out[4]);
void draw_elided(int font_id,
                 const std::string &text,
                 float x,
                 float baseline_y,
                 float max_width,
                 const float color[4]);
const char *status_label(ScenesDrawerTabStatus status);
const float *status_color(ScenesDrawerTabStatus status);
void draw_pill(const rctf &rect, const float fill[4], float radius);

}  // namespace view3d_scenes_drawer

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operators, keymap, QA
 * \{ */

/** `view3d.scenes_drawer_{update,reveal,toggle,set,edge,click,hover}`. */
void view3d_scenes_drawer_operatortypes();
/** Shared by the two operator files (`_ops.cc`, `_ops_cards.cc`). */
bool view3d_scenes_drawer_op_poll(bContext *C);
/** True on the resize sash of the context region. */
bool view3d_scenes_drawer_edge_hit(const bContext *C, const int xy[2]);
void VIEW3D_OT_scenes_drawer_click(wmOperatorType *ot);
void VIEW3D_OT_scenes_drawer_hover(wmOperatorType *ot);
void VIEW3D_OT_scenes_drawer_scroll(wmOperatorType *ot);
/** Insertion position (0..cards) for a drag released at window `y`. */
int view3d_scenes_drawer_drop_slot(const ScenesDrawerRuntime *runtime, int y);
void view3d_scenes_drawer_keymap(wmKeyConfig *keyconf);
/** Attach the Ctrl+` toggle map. Call first on View3D WINDOW and the drawer. */
void view3d_scenes_drawer_toggle_handlers_add(wmWindowManager *wm, ARegion *region);
void view3d_scenes_drawer_qa_targets_register();

/** \} */

}  // namespace blender
