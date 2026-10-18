/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Frameless Linux window edges own native resize presses and hover cursors. */
#ifdef __linux__
#  include <cmath>

#  include "BKE_context.hh"
#  include "BKE_global.hh"
#  include "BKE_screen.hh"
#  include "BLI_listbase.h"
#  include "BLI_math_vector_types.hh"
#  include "DNA_space_types.h"
#  include "DNA_windowmanager_types.h"
#  include "UI_interface_c.hh"
#  include "UI_resources.hh"
#  include "WM_api.hh"
#  include "WM_types.hh"

#  include "agent_bubble_intern.hh"
#  include "agent_bubble_resize_edges.hh"

extern "C" bool Mixar_WindowBeginNativeResize(void *window_handle, int edges);
extern "C" void Mixar_WindowSetResizeCursor(void *window_handle, int edges);

namespace blender {

static void *resize_cursor_window = nullptr;

AgentBubbleWindowEvent agent_bubble_linux_handle_event(
    bContext *C, const wmEvent *event, void *bubble, bool minimised)
{
  wmWindow *win = CTX_wm_window(C);
  if (!win || !bubble || win->runtime->ghostwin != bubble) {
    return AgentBubbleWindowEvent::PassThrough;
  }
  const int2 size = WM_window_native_pixel_size(win);
  const int edges = minimised ? 0 : agent_bubble_resize_edges(
      event->xy[0], event->xy[1], size.x, size.y, int(std::ceil(12 * UI_SCALE_FAC)));

  if (event->type == MOUSEMOVE && edges) {
    Mixar_WindowSetResizeCursor(bubble, edges);
    resize_cursor_window = bubble;
    return AgentBubbleWindowEvent::Handled;
  }
  if (resize_cursor_window == bubble && (!edges || event->type == WINDEACTIVATE)) {
    /* GHOST's edge cursor temporarily bypasses the editor cursor cache. Force
     * its restoration even when WM still remembers the same default/text cursor. */
    const int cursor = win->cursor;
    win->cursor = 0;
    WM_cursor_set(win, cursor);
    resize_cursor_window = nullptr;
  }
  if (!edges || event->type != LEFTMOUSE || event->val != KM_PRESS) {
    return AgentBubbleWindowEvent::PassThrough;
  }

  /* Release the live text editor without reverting its RNA draft. Native
   * edge drags must not depend on which region/keymap owns this pixel. */
  bContext *border_context = CTX_copy(C);
  for (ScrArea &area : WM_window_get_active_screen(win)->areabase) {
    if (area.spacetype != SPACE_AGENT_BUBBLE) {
      continue;
    }
    CTX_wm_area_set(border_context, &area);
    for (ARegion &region : area.regionbase) {
      CTX_wm_region_set(border_context, &region);
      ui::UI_region_free_active_but_all(border_context, &region);
    }
  }
  CTX_free(border_context);
  /* A declined native resize must not fall through into a header move. */
  return Mixar_WindowBeginNativeResize(bubble, edges) ? AgentBubbleWindowEvent::Resizing :
                                                     AgentBubbleWindowEvent::Handled;
}

}  // namespace blender
#endif
