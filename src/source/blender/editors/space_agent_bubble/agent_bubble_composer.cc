/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** One-shot keyboard focus for the island's native chat composer. */

#include "BKE_context.hh"
#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "DNA_scene_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "RNA_access.hh"
#include "UI_interface_c.hh"
#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_bubble_intern.hh"

namespace blender {

static void *pending_focus_window = nullptr;

static bool focus_composer(bContext *C, void *ghost_window)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  for (wmWindow &win : wm->windows) {
    if (win.runtime->ghostwin != ghost_window) {
      continue;
    }
    PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
    PropertyRNA *tab = RNA_struct_find_property(&wm_ptr, "mixar_bubble_tab");
    PropertyRNA *ink = RNA_struct_find_property(&wm_ptr, "mixie_chat_ink_visible");
    int agent_tab = 0;
    if ((tab && (!RNA_property_enum_value(C, &wm_ptr, tab, "AGENT", &agent_tab) ||
                 RNA_property_enum_get(&wm_ptr, tab) != agent_tab)) ||
        (ink && RNA_property_boolean_get(&wm_ptr, ink)))
    {
      return true; /* Opening another pane must not focus a hidden chat field. */
    }
    if (win.scene == nullptr) {
      return true;
    }
    bContext *bubble_context = CTX_copy(C);
    CTX_wm_window_set(bubble_context, &win);
    bScreen *screen = CTX_wm_screen(bubble_context);
    bool focused = false;
    for (ScrArea &area : screen->areabase) {
      if (area.spacetype != SPACE_AGENT_BUBBLE) {
        continue;
      }
      CTX_wm_area_set(bubble_context, &area);
      for (ARegion &region : area.regionbase) {
        if (region.regiontype == RGN_TYPE_WINDOW || region.regiontype == RGN_TYPE_TOOLS) {
          focused = ui::textbutton_activate_rna(
              bubble_context, &region, win.scene, "mixie_chat_input", true);
          if (focused) {
            break;
          }
        }
      }
      if (focused) {
        break;
      }
    }
    CTX_free(bubble_context);
    return focused;
  }
  return true; /* Window closed before its next layout. */
}

void agent_bubble_composer_focus_request(bContext *C, void *ghost_window)
{
  pending_focus_window = focus_composer(C, ghost_window) ? nullptr : ghost_window;
}

void agent_bubble_composer_focus_tick(bContext *C, void *ghost_window, const bool minimised)
{
  if (minimised || pending_focus_window != ghost_window) {
    pending_focus_window = nullptr;
  }
  if (pending_focus_window && focus_composer(C, pending_focus_window)) {
    pending_focus_window = nullptr;
  }
}

void agent_bubble_composer_focus_if_pending(bContext *C)
{
  wmWindow *win = CTX_wm_window(C);
  if (!win || !win->runtime || pending_focus_window == nullptr ||
      win->runtime->ghostwin != pending_focus_window)
  {
    return;
  }
  if (focus_composer(C, pending_focus_window)) {
    pending_focus_window = nullptr;
  }
}

bool agent_bubble_composer_has_focused_draft(const bContext *C, void *ghost_window)
{
  const wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm || !wm->runtime) {
    return false;
  }
  const wmWindow *active = wm->runtime->winactive;
  if (!active || !active->runtime || active->runtime->ghostwin != ghost_window ||
      active->scene == nullptr)
  {
    return false;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&active->scene->id);
  PropertyRNA *input = RNA_struct_find_property(&scene_ptr, "mixie_chat_input");
  return input && RNA_property_string_length(&scene_ptr, input) > 0;
}

}  // namespace blender
