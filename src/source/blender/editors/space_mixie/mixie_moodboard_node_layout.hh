/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "mixie_draw_moodboard_intern.hh"

namespace blender::ed::mixie {

rcti moodboard_visible_canvas_rect(const bContext *C);

/** One visibility/ownership gate for both tile hints and editable controls. */
bool moodboard_node_controls_rect(const bContext *C, View2D *v2d, PointerRNA *node, rcti *r_rect);
/** A full settings panel fits beside the card, or the caller uses a popup. */
bool moodboard_node_settings_rect(const bContext *C,
                                  PointerRNA *node,
                                  const rcti &card,
                                  rcti *r_rect);
void moodboard_draw_node_settings(ui::Block *block, PointerRNA *node, const rcti &panel);
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
