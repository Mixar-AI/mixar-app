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
 * The keyboard follows the holds. A suppressed dock that had it would keep it
 * (on macOS it is only transparent), so Esc / Return / typing for the dialog
 * would reach the hidden island. The first hold therefore remembers the dock
 * that was the key window and makes the dialog's host window key; the last
 * release hands the keyboard back to that dock, so after Cancel the island
 * composer types again instead of the viewport taking the keys as shortcuts.
 *
 * Linux has no floating-dock window controls: holds are tracked but nothing
 * is hidden (as for the splash).
 */

#include "BLI_listbase_iterator.hh"
#include "BLI_set.hh"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_global.hh"
#include "BKE_main.hh"
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
extern "C" bool Mixar_WindowIsKey(void *window_handle);
#endif

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

static Set<const void *> &dock_holders()
{
  static Set<const void *> holders;
  return holders;
}

bool Mixar_window_has_agent_bubble(const wmWindow *win)
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
 * vanish with the island. Shared by `Mixar_operator_modal_dialog_popup`
 * (wm_operators.cc), `wm_close_file_dialog` (wm_files.cc) and the quit flow
 * (wm_window.cc): the bubble's top-level parent (the viewport it overlays),
 * else any top-level non-temporary main window. */
wmWindow *Mixar_modal_dialog_host_window(wmWindowManager *wm, wmWindow *win)
{
  if (win == nullptr || !Mixar_window_has_agent_bubble(win)) {
    return win;
  }
  wmWindow *win_main = win->parent;
  while (win_main && win_main->parent) {
    win_main = win_main->parent;
  }
  if (win_main && !Mixar_window_has_agent_bubble(win_main)) {
    return win_main;
  }
  if (wm != nullptr) {
    for (wmWindow &iter_win : wm->windows) {
      if (iter_win.parent == nullptr && !WM_window_is_temp_screen(&iter_win) &&
          !Mixar_window_has_agent_bubble(&iter_win))
      {
        return &iter_win;
      }
    }
  }
  return win;
}

#if defined(__APPLE__) || defined(_WIN32)
/* The floating dock that was the key window when the first hold began, and
 * its id: the pointer alone could name a window freed (and its memory
 * reused) while the dialog was open. */
static wmWindow *g_key_dock = nullptr;
static int g_key_dock_winid = 0;

static void *ghost_window(const wmWindow *win)
{
  return (win != nullptr && win->runtime != nullptr) ? win->runtime->ghostwin : nullptr;
}

static wmWindow *key_floating_dock(wmWindowManager *wm)
{
  if (wm == nullptr) {
    return nullptr;
  }
  for (wmWindow &win : wm->windows) {
    void *ghostwin = ghost_window(&win);
    if (ghostwin != nullptr && Mixar_window_has_agent_bubble(&win) && Mixar_WindowIsKey(ghostwin))
    {
      return &win;
    }
  }
  return nullptr;
}

/* The remembered dock, if it still exists; forgets it either way. */
static wmWindow *take_key_dock()
{
  wmWindow *dock = g_key_dock;
  const int winid = g_key_dock_winid;
  g_key_dock = nullptr;
  g_key_dock_winid = 0;
  wmWindowManager *wm = G_MAIN ? static_cast<wmWindowManager *>(G_MAIN->wm.first) : nullptr;
  if (dock == nullptr || wm == nullptr) {
    return nullptr;
  }
  for (wmWindow &win : wm->windows) {
    if (&win == dock && win.winid == winid && ghost_window(&win) != nullptr) {
      return dock;
    }
  }
  return nullptr;
}
#endif

void Mixar_floating_docks_hold(bContext *C, const void *owner)
{
  if (owner == nullptr || !dock_holders().add(owner)) {
    return;
  }
#if defined(__APPLE__) || defined(_WIN32)
  wmWindow *host = nullptr;
  if (dock_holders().size() == 1) {
    /* Ask before hiding: Windows moves the foreground off a hidden window. */
    wmWindowManager *wm = CTX_wm_manager(C);
    wmWindow *dock = key_floating_dock(wm);
    host = dock ? Mixar_modal_dialog_host_window(wm, CTX_wm_window(C)) : nullptr;
    if (host != nullptr && host != dock) {
      g_key_dock = dock;
      g_key_dock_winid = dock->winid;
    }
    else {
      host = nullptr;
    }
  }
  Mixar_FloatingDocksSuppressForModal();
  if (ghost_window(host) != nullptr) {
    Mixar_WindowMakeKey(ghost_window(host));
  }
#else
  UNUSED_VARS(C);
#endif
}

void Mixar_floating_docks_release(const void *owner)
{
  if (owner == nullptr || !dock_holders().remove(owner)) {
    return;
  }
#if defined(__APPLE__) || defined(_WIN32)
  Mixar_FloatingDocksRestoreAfterModal();
  if (dock_holders().is_empty()) {
    if (wmWindow *dock = take_key_dock()) {
      Mixar_WindowMakeKey(ghost_window(dock));
    }
  }
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

}  // namespace blender
