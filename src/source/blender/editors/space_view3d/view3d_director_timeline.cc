/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Poll-driven native keyframe timeline dock for Director mode.
 */

#include <algorithm>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_rect.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "ED_screen.hh"

#include "GPU_immediate.hh"
#include "GPU_immediate_util.hh"
#include "GPU_shader_shared_utils.hh"
#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_director_cinema.hh"
#include "view3d_director_timeline.hh"

namespace {

constexpr double PLAYBACK_REDRAW_INTERVAL = 1.0 / 30.0;

wmTimer *g_playback_redraw_timer = nullptr;

void playback_redraw_timer_update(const bContext *C, const bool enabled)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return;
  }
  if (enabled) {
    if (!g_playback_redraw_timer && CTX_wm_window(C)) {
      g_playback_redraw_timer = WM_event_timer_add_notifier(
          wm, CTX_wm_window(C), NC_SPACE | ND_SPACE_VIEW3D, PLAYBACK_REDRAW_INTERVAL);
    }
  }
  else if (g_playback_redraw_timer) {
    WM_event_timer_remove(wm, nullptr, g_playback_redraw_timer);
    g_playback_redraw_timer = nullptr;
  }
}


bool director_timeline_poll(const RegionPollParams *params)
{
  DirectorViewState state;
  const bool visible = view3d_director_state_read(CTX_data_scene(params->context), &state) &&
                       state.active && state.timeline_expanded;
  if (!visible) {
    playback_redraw_timer_update(params->context, false);
  }
  return visible;
}

void director_timeline_draw(const bContext *C, ARegion *region)
{
  DirectorViewState state;
  if (!view3d_director_state_read(CTX_data_scene(C), &state) || !state.active) {
    return;
  }
  ED_region_pixelspace(region);
  GPU_blend(GPU_BLEND_ALPHA);
  const int margin = std::max(6, int(8.0f * UI_SCALE_FAC));
  const int unit = std::max(18, int(20.0f * UI_SCALE_FAC));
  const int gap = std::max(4, int(5.0f * UI_SCALE_FAC));
  const bool playing = ED_screen_animation_playing(CTX_wm_manager(C)) != nullptr;
  playback_redraw_timer_update(C, playing);
  cinema_draw_dock_panel(region);

  uiBlock *block = UI_block_begin(
      C, region, "mixar_director_timeline", blender::ui::EmbossType::Emboss);
  UI_block_theme_style_set(block, UI_BLOCK_THEME_STYLE_POPUP);
  cinema_draw_dock_controls(block, C, region, state, playing);
  DirectorTimelineRuntime *runtime = view3d_director_timeline_runtime_ensure(region);
  const int content_top = region->winy - int(cinema_dock_control_height());
  view3d_director_timeline_draw_content(region, state, runtime, margin, unit, content_top);
  UI_block_end(C, block);
  UI_block_draw(C, block);
  GPU_blend(GPU_BLEND_NONE);
}

void director_timeline_listener(const wmRegionListenerParams *params)
{
  const wmNotifier *notifier = params->notifier;
  if (ELEM(notifier->category, NC_SCENE, NC_ANIMATION, NC_SPACE) ||
      (notifier->category == NC_SCREEN && notifier->data == ND_ANIMPLAY))
  {
    ED_region_tag_redraw(params->region);
  }
}

}  // namespace

void view3d_director_timeline_region_ensure(ScrArea *area)
{
  if (!area || area->spacetype != SPACE_VIEW3D ||
      BKE_area_find_region_type(area, RGN_TYPE_CHANNELS))
  {
    return;
  }

  /* Builds made before the Director dock used RGN_TYPE_FOOTER, whose height
   * Blender hard-clamps to one header row. Retype a saved legacy region before
   * adding a new one so existing workspaces recover the full timeline. */
  ARegion *region = BKE_area_find_region_type(area, RGN_TYPE_FOOTER);
  if (region) {
    region->regiontype = RGN_TYPE_CHANNELS;
  }
  else {
    region = BKE_area_region_new();
    ARegion *window_region = BKE_area_find_region_type(area, RGN_TYPE_WINDOW);
    if (window_region) {
      BLI_insertlinkbefore(&area->regionbase, window_region, region);
    }
    else {
      BLI_addtail(&area->regionbase, region);
    }
    region->regiontype = RGN_TYPE_CHANNELS;
  }

  /* ED_area_and_region_types_init() has already run when SpaceType.init is
   * called. RGN_TYPE_CHANNELS is intentionally used as an otherwise-unused
   * View3D region type because RGN_TYPE_FOOTER ignores custom heights. */
  region->alignment = RGN_ALIGN_BOTTOM;
  region->sizey = VIEW3D_DIRECTOR_TIMELINE_HEIGHT;
  region->flag |= RGN_FLAG_TEMP_REGIONDATA | RGN_FLAG_POLL_FAILED;
  /* The normal type-assignment pass preceded this callback. Without this,
   * ED_area_init() dereferences a null runtime type while visiting the newly
   * inserted region. */
  region->runtime->type = BKE_regiontype_from_id(area->type, region->regiontype);
}

void view3d_director_timeline_region_register(SpaceType *st)
{
  ARegionType *art = MEM_callocN<ARegionType>("spacetype view3d director timeline region");
  art->regionid = RGN_TYPE_CHANNELS;
  art->prefsizey = VIEW3D_DIRECTOR_TIMELINE_HEIGHT;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_FRAMES;
  art->poll = director_timeline_poll;
  art->init = view3d_director_timeline_region_init;
  art->draw = director_timeline_draw;
  art->free = view3d_director_timeline_region_free;
  art->duplicate = view3d_director_timeline_region_duplicate;
  art->listener = director_timeline_listener;
  BLI_addhead(&st->regiontypes, art);

  /* Keep the old type readable long enough for SpaceType.init to migrate it.
   * Without a registered type, opening a .blend saved by the first Director
   * build would fail before view3d_director_timeline_region_ensure() runs. */
  art = MEM_callocN<ARegionType>("spacetype view3d legacy director timeline region");
  art->regionid = RGN_TYPE_FOOTER;
  art->poll = director_timeline_poll;
  BLI_addhead(&st->regiontypes, art);
}
