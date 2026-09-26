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

}  // namespace blender
