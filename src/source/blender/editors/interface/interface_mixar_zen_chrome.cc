/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Zen chrome beds. The island/pill windows frost through GHOST; the Zen
 * topbar and scene toolbar share one opaque themed bed; the empty
 * tool-header remains transparent. Both use the existing overlap geometry.
 * macOS and Windows share this GPU path.
 *
 * Zen Mode is the only workspace on this path. Texturing / Texture Paint
 * are ordinary Engine workspaces: their 3D viewport keeps Blender's full
 * opaque header, so it must stay on the stock overlap and clear path.
 */

#include <algorithm>
#include "interface_intern.hh"
#include "BKE_context.hh"
#include "BKE_screen.hh"
#include "UI_mixar_theme.hh"
#include "BKE_global.hh"
#include "BKE_main.hh"

#include "BLI_listbase.h"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_workspace_types.h"
#include "DNA_userdef_types.h"

#include "ED_screen.hh"

#include "GPU_framebuffer.hh"
#include "GPU_state.hh"

#include "UI_mixar.hh"
#include "UI_mixar_chrome.hh"
#include "UI_interface_c.hh"

#include "WM_api.hh"
#include "WM_types.hh"

namespace blender::ui {

static bool mixar_workspace_name_floats_viewport_chrome(const char *name)
{
  return STREQ(name, "Zen Mode");
}

bool mixar_workspace_is_zen(const bContext *C)
{
  const WorkSpace *workspace = C ? CTX_wm_workspace(C) : nullptr;
  return workspace != nullptr && STREQ(workspace->id.name + 2, "Zen Mode");
}

bool mixar_workspace_floats_viewport_chrome(const bContext *C)
{
  const WorkSpace *workspace = C ? CTX_wm_workspace(C) : nullptr;
  return workspace != nullptr &&
         mixar_workspace_name_floats_viewport_chrome(workspace->id.name + 2);
}

bool mixar_area_floats_viewport_chrome(const ScrArea *area)
{
  if (area == nullptr || area->spacetype != SPACE_VIEW3D) {
    return false;
  }
  if (G_MAIN == nullptr) {
    return false;
  }
  wmWindowManager *wm = static_cast<wmWindowManager *>(G_MAIN->wm.first);
  if (wm == nullptr) {
    return false;
  }
  for (wmWindow &win : wm->windows) {
    const bScreen *screen = WM_window_get_active_screen(&win);
    if (screen == nullptr || BLI_findindex(&screen->areabase, area) == -1) {
      continue;
    }
    const WorkSpace *workspace = WM_window_get_active_workspace(&win);
    return workspace != nullptr &&
           mixar_workspace_name_floats_viewport_chrome(workspace->id.name + 2);
  }
  return false;
}

bool mixar_zen_header_clear(const bContext *C, const ARegion *region)
{
  if (region == nullptr || !mixar_workspace_is_zen(C)) {
    return false;
  }
  const ScrArea *area = CTX_wm_area(C);
  /* The mode bar shares the Cinema toolbar background below. */
  if (area == nullptr || area->spacetype != SPACE_TOPBAR) {
    return false;
  }

  ED_region_pixelspace(region);
  /* The main window has no native backdrop. Its topbar is an opaque bed;
   * alpha here exposes uninitialised region buffers, not viewport frost. */
  MIXAR_THEME_LOAD(background, ToolbarBackground);
  GPU_clear_color(background[0], background[1], background[2], 1.0f);
  return true;
}

bool mixar_zen_floating_header_clear(const bContext *C, const ARegion *region)
{
  if (region == nullptr || !mixar_workspace_floats_viewport_chrome(C)) {
    return false;
  }
  const ScrArea *area = CTX_wm_area(C);
  if (area == nullptr || area->spacetype != SPACE_VIEW3D) {
    return false;
  }
  /* The scene toolbar owns a full-width bed. TOOL_HEADER remains empty
   * and transparent, including when users explicitly show that region. */
  if (!ELEM(region->regiontype, RGN_TYPE_HEADER, RGN_TYPE_TOOL_HEADER)) {
    return false;
  }
  ED_region_pixelspace(region);
  if (region->regiontype == RGN_TYPE_HEADER) {
    MIXAR_THEME_LOAD(background, ToolbarBackground);
    GPU_clear_color(background[0], background[1], background[2], 1.0f);
    const rctf divider{0, float(region->winx), 0, float(U.pixelsize)};
    MIXAR_THEME_LOAD(color, ToolbarBorder);
    draw_roundbox_corner_set(CNR_ALL);
    draw_roundbox_4fv(&divider, true, 0, color);
  }
  else {
    GPU_clear_color(0.0f, 0.0f, 0.0f, 0.0f);
  }
  return true;
}

/* Native View2D panning owns drag events; keep the entire control group reachable. */
void mixar_zen_adaptive_pan_clamp(const bContext *C, ARegion *region)
{
  if (!mixar_workspace_is_zen(C) || region->regiontype != RGN_TYPE_TOOL_HEADER) {
    return;
  }
  rctf bounds;
  BLI_rctf_init_minmax(&bounds);
  bool found = false;
  for (const Block &block : region->runtime->uiblocks) {
    if (block.name != "VIEW3D_HT_tool_header") {
      continue;
    }
    for (const Button &button : block.buttons()) {
      if (button.mixar_style.component != MixarComponent::Toolbar ||
          (button.flag & UI_HIDDEN)) {
        continue;
      }
      BLI_rctf_union(&bounds, &button.rect);
      found = true;
    }
  }
  if (!found) {
    return;
  }
  /* A compact swatch stays vertically centered with the full-height controls. */
  for (Block &block : region->runtime->uiblocks) {
    if (block.name != "VIEW3D_HT_tool_header") {
      continue;
    }
    for (Button &button : block.buttons()) {
      if (button.type == ButtonType::Color) {
        BLI_rctf_translate(&button.rect, 0,
                          BLI_rctf_cent_y(&bounds) - BLI_rctf_cent_y(&button.rect));
      }
    }
  }
  const float xmin = std::min(bounds.xmax - region->winx, bounds.xmin);
  const float xmax = std::max(bounds.xmax - region->winx, bounds.xmin);
  const float ymin = std::min(bounds.ymax - region->winy, bounds.ymin);
  const float ymax = std::max(bounds.ymax - region->winy, bounds.ymin);
  View2D &v2d = region->v2d;
  BLI_rctf_translate(&v2d.cur,
                    std::clamp(v2d.cur.xmin, xmin, xmax) - v2d.cur.xmin,
                    std::clamp(v2d.cur.ymin, ymin, ymax) - v2d.cur.ymin);
}

}  // namespace blender::ui
