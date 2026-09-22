/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "mixie_draw_moodboard_intern.hh"

namespace blender::ed::mixie {

rcti moodboard_canvas_host_rect(const bContext *C);
rcti moodboard_canvas_host_rect(const ScrArea *area, ARegion *region);
/** Full painting surface. Floating controls and the N-panel composite above it. */
rcti moodboard_canvas_draw_rect(const bContext *C);
rcti moodboard_canvas_draw_rect(const ScrArea *area, ARegion *region);
/** Canvas controls cannot capture the drawer resize sash. */
rcti moodboard_canvas_controls_rect(const bContext *C);
/** Unobstructed placement/framing area, not a painting clip. */
rcti moodboard_visible_canvas_rect(const ScrArea *area, ARegion *region);
rcti moodboard_visible_canvas_rect(const bContext *C);

/** One visibility/ownership gate for both tile hints and editable controls. */
bool moodboard_node_controls_rect(const bContext *C, View2D *v2d, PointerRNA *node, rcti *r_rect);
ui::Button *moodboard_screen_prop_button(ui::Block *block,
                                         PointerRNA *ptr,
                                         const char *property,
                                         const char *label,
                                         ui::ButtonType type,
                                         int x,
                                         int y,
                                         int width,
                                         int height,
                                         float minimum = 0.0f,
                                         float maximum = 0.0f);

}  // namespace blender::ed::mixie
