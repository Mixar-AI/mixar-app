/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

namespace blender {
struct wmWindow;

/** What `wm_draw_window_onscreen` does with the window's areas this frame. */
enum class MixarBackdropPass {
  /** No blurred pop-up: draw as usual. */
  None,
  /** First frame of a blurred pop-up: the areas draw into an offscreen that
   * `wm_draw_mixar_backdrop_end` blurs and keeps. */
  Capture,
  /** A blur is kept: skip the areas, draw the kept blur instead. */
  Cached,
};

/**
 * Called after `wmWindowViewport` at the top of the window draw. Binds the
 * capture target for #MixarBackdropPass::Capture. Mono drawing only (`view`
 * -1); a stereo or screenshot pass draws normally.
 */
MixarBackdropPass wm_draw_mixar_backdrop_begin(wmWindow *win, int view);
/** Called just before the floating regions (menus, pop-ups) blend in: blur a
 * fresh capture, then lay the kept blur and its scrim over the window. */
void wm_draw_mixar_backdrop_end(wmWindow *win, MixarBackdropPass pass);
/** Called with the dying window's GPU context current, before discarding it. */
void wm_draw_mixar_backdrop_free(wmWindow *win);
}  // namespace blender
