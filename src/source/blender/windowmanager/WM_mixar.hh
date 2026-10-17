/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup wm
 *
 * Mixar additions to the window manager's public API that other modules
 * (RNA, editors) read. Definitions live in the `intern/wm_*.cc` overlays.
 */

#pragma once

#include <cstdint>

namespace blender {

struct bContext;
struct wmWindow;
struct wmWindowManager;
struct wmEvent;

/* Main-thread-only production input. Never enables global QA simulation. */
void Mixar_ui_control_enable(wmWindowManager *wm, bool enabled);
bool Mixar_ui_control_enabled();
bool Mixar_ui_control_begin(wmWindowManager *wm, const char *owner);
void Mixar_ui_control_end(wmWindowManager *wm, const char *owner);
int Mixar_ui_control_generation(wmWindowManager *wm);
int Mixar_ui_control_pending();
int Mixar_ui_control_modal_count(wmWindow *win);
bool Mixar_ui_control_input(wmWindowManager *wm, wmWindow *win,
                            const char *owner, const wmEvent *event);
bool Mixar_ui_control_event_valid(wmWindow *win, const wmEvent *event);
void Mixar_ui_control_event_forget(const wmEvent *event);
void Mixar_ui_control_human_input(wmWindowManager *wm);
wmEvent *Mixar_event_add_synthetic(wmWindow *win, const wmEvent *event);

/**
 * True while the OS window-resize callback is dispatching handlers, timers
 * and drawing (`wm_window.cc`). On macOS that callback sits inside AppKit's
 * autorelease pool ABOVE the Metal render boundary; a viewport render there
 * drains that boundary's pool and the app aborts. Render paths reachable from
 * a timer, a modal handler or a region draw must defer while this is set.
 * Python reads it as `WindowManager.mixar_window_resizing`.
 */
bool Mixar_window_resize_dispatch_active();

/**
 * Make `win`'s GPU context the active one for GPU work done outside a draw
 * (`wm_draw.cc`'s front-buffer reads do the same). A region's viewport
 * textures sample as black from another window's context on Metal, and the
 * island and pill are windows of their own, so the drawable window is often
 * not the host. Returns true when a switch happened; then call
 * #Mixar_window_gpu_context_pop when done.
 */
bool Mixar_window_gpu_context_push(const wmWindowManager *wm, wmWindow *win);
void Mixar_window_gpu_context_pop(const wmWindowManager *wm);

/**
 * Hide the Agent island and pill while a modal pop-up is open
 * (`wm_mixar_modal_dialog.cc`). Keyed by `owner` (the pop-up's data, or a
 * per-dialog static): a second hold by the same owner is ignored and a
 * release only undoes an existing hold, so a pop-up may release from both
 * its button handler and its free path. No-op hiding on Linux.
 *
 * Hold while `C`'s window is the one the pop-up opens in: when a dock has
 * the keyboard, the first hold makes that window's host
 * (#Mixar_modal_dialog_host_window) key, and the last release gives the
 * keyboard back to the dock.
 */
void Mixar_floating_docks_hold(bContext *C, const void *owner);
void Mixar_floating_docks_release(const void *owner);
/** Any modal dialog holds the docks hidden: the island must not treat a press
 * in that dialog as an outside click (it would come back minimised). */
bool Mixar_floating_docks_held();

/**
 * The window a dock-hiding dialog opened from `win` is hosted in: `win`
 * itself, unless it is an Agent Bubble window (hidden with the docks), then
 * its top-level main window.
 */
wmWindow *Mixar_modal_dialog_host_window(wmWindowManager *wm, wmWindow *win);
/** `win`'s active screen has an Agent Bubble area (the island or the pill). */
bool Mixar_window_has_agent_bubble(const wmWindow *win);

}  // namespace blender
