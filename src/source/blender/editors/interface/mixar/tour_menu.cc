/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * Onboarding tour: open a real top-bar menu as if its button had been
 * clicked, and close it again.
 *
 * The tour narrates "Help ▸ Creator Program" with the real Help menu open.
 * No input is synthesized: the menu is built with the public popup API
 * (`popup_menu_begin_ex` → `menutype_draw` → `popup_menu_but_set` →
 * `popup_menu_end`) and anchored to the menu's own pulldown button, so it
 * lands exactly where a click would put it; the first row it pre-activates
 * for keyboard navigation is released again. The block carries a fixed name
 * so the tour closes only its own popup. Quit-on-mouse-leave is cleared on
 * that block: the viewer's pointer is usually far from the top bar and the
 * menu must stay up for the whole line; Escape or a click outside still
 * close it like any popup.
 */

#include "../interface_intern.hh"

#include "BLI_listbase_iterator.hh"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "UI_interface_layout.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

namespace blender {

static constexpr const char *MIXAR_TOUR_MENU_BLOCK = "mixar_tour_menu";

static ui::Button *mixar_tour_find_menu_button(wmWindow *win,
                                               bScreen *screen,
                                               MenuType *mt,
                                               ScrArea **r_area,
                                               ARegion **r_region)
{
  ED_screen_areas_iter (win, screen, area) {
    for (ARegion &region : area->regionbase) {
      if (region.runtime == nullptr) {
        continue;
      }
      for (ui::Block &block : region.runtime->uiblocks) {
        for (ui::Button &but : block.buttons()) {
          if (ui::button_menutype_get(&but) == mt) {
            *r_area = area;
            *r_region = &region;
            return &but;
          }
        }
      }
    }
  }
  return nullptr;
}

static ui::Block *mixar_tour_find_menu_block(bScreen *screen, ARegion **r_region = nullptr)
{
  for (ARegion &region : screen->regionbase) {
    if (region.runtime == nullptr) {
      continue;
    }
    for (ui::Block &block : region.runtime->uiblocks) {
      if (block.name == MIXAR_TOUR_MENU_BLOCK && block.handle != nullptr) {
        if (r_region) {
          *r_region = &region;
        }
        return &block;
      }
    }
  }
  return nullptr;
}

bool Mixar_tour_menu_is_open(wmWindow *win)
{
  bScreen *screen = win ? WM_window_get_active_screen(win) : nullptr;
  return screen != nullptr && mixar_tour_find_menu_block(screen) != nullptr;
}

bool Mixar_tour_menu_open(bContext *C, wmWindow *win, const char *menu_idname)
{
  if (C == nullptr || win == nullptr || menu_idname == nullptr) {
    return false;
  }
  bScreen *screen = WM_window_get_active_screen(win);
  MenuType *mt = WM_menutype_find(menu_idname, true);
  if (screen == nullptr || mt == nullptr || mixar_tour_find_menu_block(screen) != nullptr) {
    return false;
  }
  ScrArea *area = nullptr;
  ARegion *region = nullptr;
  ui::Button *but = mixar_tour_find_menu_button(win, screen, mt, &area, &region);
  if (but == nullptr) {
    return false;
  }

  wmWindow *prev_win = CTX_wm_window(C);
  ScrArea *prev_area = CTX_wm_area(C);
  ARegion *prev_region = CTX_wm_region(C);
  CTX_wm_window_set(C, win);
  CTX_wm_area_set(C, area);
  CTX_wm_region_set(C, region);

  ui::PopupMenu *pup = ui::popup_menu_begin_ex(C, "", MIXAR_TOUR_MENU_BLOCK, ICON_NONE);
  ui::menutype_draw(C, mt, ui::popup_menu_layout(pup));
  ui::popup_menu_but_set(pup, region, but);
  ui::popup_menu_end(C, pup);

  ARegion *menu_region = nullptr;
  if (ui::Block *block = mixar_tour_find_menu_block(screen, &menu_region)) {
    block->flag &= ~ui::BLOCK_MOVEMOUSE_QUIT;
    /* A popup-path menu pre-activates its first item (keyboard navigation),
     * which a click on the menu bar never does: the tour highlights its own
     * row, so no other row may look hovered or raise a tooltip. */
    ui::UI_region_free_active_but_all(C, menu_region);
  }

  CTX_wm_window_set(C, prev_win);
  CTX_wm_area_set(C, prev_area);
  CTX_wm_region_set(C, prev_region);
  return true;
}

bool Mixar_tour_menu_close(wmWindow *win)
{
  bScreen *screen = win ? WM_window_get_active_screen(win) : nullptr;
  ui::Block *block = screen ? mixar_tour_find_menu_block(screen) : nullptr;
  if (block == nullptr) {
    return false;
  }
  ui::popup_menu_close(block, true);
  /* The popup handler frees a closed menu on its next event. */
  WM_event_add_mousemove(win);
  return true;
}

}  // namespace blender
