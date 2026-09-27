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

namespace blender {

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

}  // namespace blender
