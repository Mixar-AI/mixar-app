/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

namespace blender {
struct ARegion;
struct wmWindow;
struct wmWindowManager;

/** Paint schedules one future HEADER frame. No context is retained. */
void agent_ui_cat_schedule(const wmWindow *window,
                           ARegion *region,
                           const void *host,
                           double seconds);
/** Existing hover policy only monitors availability; it never draws a frame. */
void agent_ui_cat_scheduler_sync(wmWindowManager *wm, const void *pill, bool minimized);
void agent_ui_cat_scheduler_forget(const ARegion *region = nullptr);
void agent_ui_cat_scheduler_window_freed(const void *ghostwin);
}  // namespace blender
