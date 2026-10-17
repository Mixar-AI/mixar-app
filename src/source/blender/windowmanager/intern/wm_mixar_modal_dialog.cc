/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup wm
 *
 * Mixar modal dialogs: floating-dock suppression held per pop-up, and the
 * window such a dialog is hosted in.
 *
 * The splash, the "Save changes before closing?" dialog and
 * `WindowManager.mixar_invoke_modal_dialog` (wm_operators.cc) hide the Agent
 * island and pill (alpha 0 + ignore mouse on macOS, hidden on Windows) for as
 * long as they are open. GHOST keeps a depth counter, so nested holders are
 * fine in principle, but each of those dialogs reaches its restore from TWO
 * places on a button close: the button handler, and the pop-up's own free
 * path (`popup_block_close` → `popup_block_free` → `arg_free`). A second
 * decrement from one dialog would re-show the docks while another dialog is
 * still open. Holds are therefore keyed by their owner (the pop-up's data or
 * a per-dialog static): a hold counts once, a release only undoes a hold that
 * exists, so every path may release unconditionally.
 *
 * Linux has no floating-dock window controls: holds are tracked but nothing
 * is hidden (as for the splash).
 */

#include "BLI_listbase_iterator.hh"
#include "BLI_set.hh"
#include "BLI_utildefines.h"

#include "BKE_screen.hh"
#include "BKE_wm_runtime.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "WM_api.hh"
#include "WM_mixar.hh"
#include "WM_types.hh"

#if defined(__APPLE__) || defined(_WIN32)
extern "C" void Mixar_FloatingDocksSuppressForModal();
extern "C" void Mixar_FloatingDocksRestoreAfterModal();
extern "C" void Mixar_WindowMakeKey(void *window_handle);
#endif

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

static Set<const void *> &dock_holders()
{
  static Set<const void *> holders;
  return holders;
}

void Mixar_floating_docks_hold(const void *owner)
{
  if (owner == nullptr || !dock_holders().add(owner)) {
    return;
  }
#if defined(__APPLE__) || defined(_WIN32)
  Mixar_FloatingDocksSuppressForModal();
#endif
}

void Mixar_floating_docks_release(const void *owner)
{
  if (owner == nullptr || !dock_holders().remove(owner)) {
    return;
  }
#if defined(__APPLE__) || defined(_WIN32)
  Mixar_FloatingDocksRestoreAfterModal();
  /* wm_draw_update skips natively hidden windows (Mixar_WindowIsVisible in
   * wm_draw.cc), so a dock's content froze while suppressed: tag a redraw so
   * its first visible frame is current. */
  WM_main_add_notifier(NC_WINDOW, nullptr);
#endif
}

bool Mixar_floating_docks_held()
{
  return !dock_holders().is_empty();
}

static bool window_has_agent_bubble(const wmWindow *win)
{
  const bScreen *screen = win ? WM_window_get_active_screen(win) : nullptr;
  if (screen == nullptr) {
    return false;
  }
  for (const ScrArea &area : screen->areabase) {
    if (area.spacetype == SPACE_AGENT_BUBBLE) {
      return true;
    }
  }
  return false;
}

/* A dialog that hides the floating docks must never live in one: it would
 * vanish with the island. Mirrors `wm_close_file_dialog_target_window`
 * (wm_files.cc): the bubble's top-level parent (the viewport it overlays),
 * else any top-level non-temporary main window. */
wmWindow *Mixar_modal_dialog_host_window(wmWindowManager *wm, wmWindow *win)
{
  if (win == nullptr || !window_has_agent_bubble(win)) {
    return win;
  }
  wmWindow *win_main = win->parent;
  while (win_main && win_main->parent) {
    win_main = win_main->parent;
  }
  if (win_main && !window_has_agent_bubble(win_main)) {
    return win_main;
  }
  if (wm != nullptr) {
    for (wmWindow &iter_win : wm->windows) {
      if (iter_win.parent == nullptr && !WM_window_is_temp_screen(&iter_win) &&
          !window_has_agent_bubble(&iter_win))
      {
        return &iter_win;
      }
    }
  }
  return win;
}

void Mixar_modal_dialog_focus_host(wmWindow *win)
{
#if defined(__APPLE__) || defined(_WIN32)
  /* The island stays the key window while only made transparent (macOS), so
   * keystrokes for the dialog's fields would reach the hidden island. */
  if (win != nullptr && win->runtime != nullptr && win->runtime->ghostwin != nullptr) {
    Mixar_WindowMakeKey(win->runtime->ghostwin);
  }
#else
  UNUSED_VARS(win);
#endif
}

}  // namespace blender
