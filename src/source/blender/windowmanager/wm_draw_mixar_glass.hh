/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

namespace blender {
struct wmWindow;
struct wmWindowManager;

/** Track native moves and request a host capture when a glass window first appears. */
void wm_draw_mixar_glass_update(wmWindowManager *wm);
/** Called only for the real window framebuffer, after its completed UI draw. */
void wm_draw_mixar_glass(wmWindowManager *wm, wmWindow *win);
/** Called with the dying window's GPU context current, before discarding it. */
void wm_draw_mixar_glass_free(wmWindow *win);
}  // namespace blender
