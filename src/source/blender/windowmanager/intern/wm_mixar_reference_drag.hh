/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include "BKE_context.hh"
#include "BKE_screen.hh"
#include "BLI_string.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "DNA_workspace_types.h"
#include "ED_fileselect.hh"
#include "WM_api.hh"

namespace blender {

/** Preview the destination without creating WM drags or loading media. Native
 * OS drag-enter and the QA drag-enter hook use this same path. */
inline void wm_mixar_reference_drag_enter(bContext *C, wmWindow *win, const char *path)
{
  if (!(ED_path_extension_type(path) & (FILE_TYPE_IMAGE | FILE_TYPE_MOVIE))) {
    return;
  }

  /* The floating agent window belongs to the same Zen screen. Do not change
   * its attachment drop handler; just reveal the parent's reference board. */
  wmWindow *host = win->parent ? win->parent : win;
  WorkSpace *workspace = WM_window_get_active_workspace(host);
  if (!workspace || !STREQ(workspace->id.name + 2, "Zen Mode")) {
    return;
  }
  bScreen *screen = WM_window_get_active_screen(host);
  if (!screen) {
    return;
  }
  for (ScrArea &area : screen->areabase) {
    if (area.spacetype != SPACE_VIEW3D) {
      continue;
    }
    wmWindow *previous_window = CTX_wm_window(C);
    ScrArea *previous_area = CTX_wm_area(C);
    ARegion *previous_region = CTX_wm_region(C);
    CTX_wm_window_set(C, host);
    CTX_wm_area_set(C, &area);
    CTX_wm_region_set(C, BKE_area_find_region_type(&area, RGN_TYPE_WINDOW));
    WM_operator_name_call(
        C, "VIEW3D_OT_moodboard_drawer_reveal", wm::OpCallContext::ExecDefault, nullptr, nullptr);
    CTX_wm_window_set(C, previous_window);
    CTX_wm_area_set(C, previous_area);
    CTX_wm_region_set(C, previous_region);
    break;
  }
}

}  // namespace blender
