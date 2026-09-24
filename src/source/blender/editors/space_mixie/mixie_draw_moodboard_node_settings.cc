/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Native fields shared by moodboard card composers.
 */

#include "mixie_draw_moodboard_intern.hh"
#include "mixie_moodboard_node_layout.hh"

#include "BLI_string.h"

#include <string>

#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"

namespace blender::ed::mixie {

ui::Button *moodboard_screen_prop_button(ui::Block *block,
                                         PointerRNA *ptr,
                                         const char *property,
                                         const char *label,
                                         const ui::ButtonType type,
                                         const int x,
                                         const int y,
                                         const int width,
                                         const int height,
                                         const float minimum,
                                         const float maximum)
{
  if (!RNA_struct_find_property(ptr, property)) {
    return nullptr;
  }
  ui::Button *button = ui::uiDefButR(block,
                                     type,
                                     label,
                                     x,
                                     y,
                                     short(width),
                                     short(height),
                                     ptr,
                                     property,
                                     -1,
                                     minimum,
                                     maximum,
                                     nullptr);
  const ui::MixarComponent component = type == ui::ButtonType::Menu ?
                                           ui::MixarComponent::Dropdown :
                                       type == ui::ButtonType::Checkbox ?
                                           ui::MixarComponent::Toggle :
                                       ELEM(type, ui::ButtonType::Num, ui::ButtonType::NumSlider) ?
                                           ui::MixarComponent::Number :
                                           ui::MixarComponent::Input;
  ui::mixar_style_button(button, component, ui::MixarVariant::Primary, UI_SCALE_FAC * 0.65f);
  return button;
}

}  // namespace blender::ed::mixie
