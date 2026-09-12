/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Zen chrome beds. The island/pill windows frost through GHOST; the Zen
 * topbar and View3D header live in the main window, so they take the same
 * ISLAND pane the kit already owns. macOS and Windows share this GPU path.
 */

#include "BKE_context.hh"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_workspace_types.h"

#include "ED_mixar_glass.hh"
#include "ED_screen.hh"

#include "GPU_framebuffer.hh"
#include "GPU_state.hh"

#include "UI_mixar.hh"

namespace blender::ui {

bool mixar_workspace_is_zen(const bContext *C)
{
  const WorkSpace *workspace = C ? CTX_wm_workspace(C) : nullptr;
  return workspace != nullptr && STREQ(workspace->id.name + 2, "Zen Mode");
}

bool mixar_zen_header_clear(const bContext *C, const ARegion *region)
{
  if (region == nullptr || !mixar_workspace_is_zen(C)) {
    return false;
  }
  const ScrArea *area = CTX_wm_area(C);
  if (area == nullptr) {
    return false;
  }
  const bool chrome = (area->spacetype == SPACE_TOPBAR) ||
                      (area->spacetype == SPACE_VIEW3D &&
                       ELEM(region->regiontype, RGN_TYPE_HEADER, RGN_TYPE_TOOL_HEADER));
  if (!chrome) {
    return false;
  }

  ED_region_pixelspace(region);
  /* The main window has no native backdrop. Its header is an opaque bed;
   * alpha here exposes uninitialised region buffers, not viewport frost. */
  GPU_clear_color(0.040f, 0.055f, 0.048f, 1.0f);
  const rcti pane{0, region->winx, 0, region->winy};
  MixarGlassStyle style;
  style.role = MIXAR_GLASS_ISLAND;
  style.radius = 0.0f;
  style.draw_shadow = false;
  style.draw_specular = false;
  style.draw_rim = false;
  mixar_glass_draw(pane, style);
  return true;
}

}  // namespace blender::ui
