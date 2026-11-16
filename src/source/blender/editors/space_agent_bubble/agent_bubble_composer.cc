/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Keyboard focus and active-editor lifetime for the island's native composer. */

#include "BKE_context.hh"
#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "DNA_scene_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "ED_screen.hh"
#include "ED_space_api.hh"
#include "RNA_access.hh"
#include "UI_interface_c.hh"
#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_bubble_intern.hh"

namespace blender {

static void *pending_focus_window = nullptr;

void agent_bubble_composer_deactivate(bContext *C, void *ghost_window)
{
  if (pending_focus_window == ghost_window) {
    pending_focus_window = nullptr;
  }
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm || !ghost_window) {
    return;
  }
  for (wmWindow &win : wm->windows) {
    if (win.runtime->ghostwin != ghost_window) {
      continue;
    }
    bContext *bubble_context = CTX_copy(C);
    CTX_wm_window_set(bubble_context, &win);
    if (bScreen *screen = CTX_wm_screen(bubble_context)) {
      for (ScrArea &area : screen->areabase) {
        if (area.spacetype != SPACE_AGENT_BUBBLE) {
          continue;
        }
        CTX_wm_area_set(bubble_context, &area);
        for (ARegion &region : area.regionbase) {
          CTX_wm_region_set(bubble_context, &region);
          /* Native hiding does not tear down Blender's RNA-backed UI. Free
           * both active editors and inactive buttons while their owner lives;
           * a hidden block must not retain a scene that can later be deleted.
           * BUT_TEXTEDIT_UPDATE already saved the draft, and onfree teardown
           * does not apply or undo it. Region handlers remain for restore. */
          ui::blocklist_free(bubble_context, &region);
          ED_region_tag_redraw(&region);
        }
      }
    }
    CTX_free(bubble_context);
    return;
  }
}

static bool focus_composer(bContext *C, void *ghost_window)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  for (wmWindow &win : wm->windows) {
    if (win.runtime->ghostwin != ghost_window) {
      continue;
    }
    PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
    PropertyRNA *ink = RNA_struct_find_property(&wm_ptr, "mixie_chat_ink_visible");
    if (!ED_agent_bubble_tab_shows_chat(C, true) ||
        (ink && RNA_property_boolean_get(&wm_ptr, ink)))
    {
      return true; /* Opening another pane must not focus a hidden chat field. */
    }
    if (win.scene == nullptr) {
      return true;
    }
    /* A cleared/first conversation moves the composer between regions. Old
     * uiBlocks can survive until the next layout, especially when reopening
     * at the same user-resized dimensions. Never focus the outgoing field. */
    PointerRNA scene_ptr = RNA_id_pointer_create(&win.scene->id);
    PropertyRNA *messages = RNA_struct_find_property(&scene_ptr, "mixie_chat_messages");
    const bool has_messages = messages && RNA_property_collection_length(&scene_ptr, messages) > 0;
    const int composer_region = has_messages ? RGN_TYPE_TOOLS : RGN_TYPE_WINDOW;
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
        if (region.regiontype == composer_region) {
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
