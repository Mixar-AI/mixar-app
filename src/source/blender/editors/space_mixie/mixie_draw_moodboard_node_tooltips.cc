/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Owned native tooltips for node actions and the prompt. */

#include "mixie_draw_moodboard_intern.hh"

#include "UI_mixar.hh"

namespace blender::ed::mixie {

void moodboard_set_node_tooltip(ui::Button *but, const char *text)
{
  /* Share ownership with other Mixar controls so QA can read the same complete
   * text the hover popup paints, without invoking an arbitrary callback. */
  ui::mixar_button_tooltip_owned(but, text);
}

}  // namespace blender::ed::mixie
