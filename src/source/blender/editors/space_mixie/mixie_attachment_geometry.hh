/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include "BLI_rect.h"
#include "mixie_attachment_motion.hh"
namespace blender {
struct bContext;
struct Image;
struct wmWindow;
struct Scene;
namespace ed::mixie {
float attachment_pixel_scale(const wmWindow *win);
FlightQuad attachment_desktop_quad(const wmWindow *win, const rctf &rect);
bool attachment_source(const bContext *C, Image *image, wmWindow **r_window, FlightQuad &quad);
bool attachment_window_visible(const wmWindow *win);
bool attachment_resting_target(wmWindow *win, FlightQuad &quad);
}  // namespace ed::mixie
}  // namespace blender
