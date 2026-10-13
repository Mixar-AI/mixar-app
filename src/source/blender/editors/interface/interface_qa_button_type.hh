/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once

#include "UI_interface_c.hh"

namespace blender::mixar_qa {
inline const char *but_type_name(const blender::ui::ButtonType type)
{
  using blender::ui::ButtonType;
  switch (type) {
    case ButtonType::But:
      return "But";
    case ButtonType::Row:
      return "Row";
    case ButtonType::Text:
      return "Text";
    case ButtonType::Menu:
      return "Menu";
    case ButtonType::ButMenu:
      return "ButMenu";
    case ButtonType::Num:
      return "Num";
    case ButtonType::NumSlider:
      return "NumSlider";
    case ButtonType::Toggle:
      return "Toggle";
    case ButtonType::ToggleN:
      return "ToggleN";
    case ButtonType::IconToggle:
      return "IconToggle";
    case ButtonType::IconToggleN:
      return "IconToggleN";
    case ButtonType::ButToggle:
      return "ButToggle";
    case ButtonType::Checkbox:
      return "Checkbox";
    case ButtonType::CheckboxN:
      return "CheckboxN";
    case ButtonType::Color:
      return "Color";
    case ButtonType::Tab:
      return "Tab";
    case ButtonType::Popover:
      return "Popover";
    case ButtonType::Scroll:
      return "Scroll";
    case ButtonType::Block:
      return "Block";
    case ButtonType::Label:
      return "Label";
    case ButtonType::Pulldown:
      return "Pulldown";
    case ButtonType::ListBox:
      return "ListBox";
    case ButtonType::ListRow:
      return "ListRow";
    case ButtonType::SearchMenu:
      return "SearchMenu";
    case ButtonType::HotkeyEvent:
      return "HotkeyEvent";
    case ButtonType::Image:
      return "Image";
    case ButtonType::Progress:
      return "Progress";
    default:
      return "Other";
  }
}

}  // namespace blender::mixar_qa
