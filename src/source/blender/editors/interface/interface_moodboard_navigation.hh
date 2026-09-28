/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include "BKE_context.hh"
#include "BLI_rect.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "WM_types.hh"
#include "interface_intern.hh"

namespace blender::ui {

/* Canvas navigation belongs to View2D even while a node prompt owns text focus.
 * Keep sidebar fields, popup editors and other spaces on native text scrolling. */
inline bool moodboard_text_navigation_event(const bContext *C,
                                           const Button *but,
                                           const wmEvent *event)
{
  if (!but || !ELEM(but->type, ButtonType::Text, ButtonType::TextBox) ||
      CTX_wm_region_popup(C) ||
      !ELEM(event->type, MOUSEZOOM, MOUSEPAN, WHEELUPMOUSE, WHEELDOWNMOUSE,
            WHEELLEFTMOUSE, WHEELRIGHTMOUSE))
  {
    return false;
  }
  const ScrArea *area = CTX_wm_area(C);
  const ARegion *region = CTX_wm_region(C);
  if (!area || !region || !BLI_rcti_isect_pt_v(&region->winrct, event->xy)) {
    return false;
  }
  return (area->spacetype == SPACE_MIXIE && region->regiontype == RGN_TYPE_WINDOW) ||
         (area->spacetype == SPACE_VIEW3D && region->regiontype == RGN_TYPE_TOOL_PROPS);
}

}  // namespace blender::ui
