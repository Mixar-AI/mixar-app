/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "../interface_intern.hh"
#include "BLI_string.h"
#include "RNA_access.hh"
#include "UI_mixar.hh"
#include <algorithm>

namespace blender::ui {

bool mixar_multiline_input_rect(const Button &button, const rcti &bounds, rcti &text_rect)
{
  /* Compact composers keep their native line budget. Tall editors need enough
   * room for the input's curved corners, for placeholder, selection and caret
   * alike. Work from the original bounds, never add to native left-only padding. */
  if (button.mixar_style.theme != MixarTheme::Zen ||
      button.mixar_style.component != MixarComponent::Input ||
      (button.rnaprop && STREQ(RNA_property_identifier(button.rnaprop), "mixie_chat_input")) ||
      BLI_rcti_size_y(&bounds) <= 2 * UI_UNIT_Y)
  {
    return false;
  }
  const int padding = std::min(
      int(mixar_density_metrics(MixarDensity::Compact, UI_SCALE_FAC).padding),
      std::max(0, BLI_rcti_size_x(&bounds) / 4));
  text_rect = bounds;
  BLI_rcti_pad(&text_rect, -padding, -padding);
  return true;
}

int64_t mixar_button_count(const Layout *layout)
{
  return layout->block()->buttons_ptrs.size();
}

static bool supports(const Button &button, const MixarComponent component)
{
  switch (component) {
    case MixarComponent::Toolbar:
      return ELEM(button.type, ButtonType::But, ButtonType::Menu, ButtonType::Pulldown,
                  ButtonType::Popover, ButtonType::Label, ButtonType::Row,
                  ButtonType::Num, ButtonType::NumSlider, ButtonType::Toggle,
                  ButtonType::IconToggle);
    case MixarComponent::Action:
      return ELEM(button.type, ButtonType::But, ButtonType::Menu, ButtonType::Block,
                  ButtonType::Popover, ButtonType::Pulldown);
    case MixarComponent::GlassTool:
      return button.icon != ICON_NONE && button.str.empty() &&
             ELEM(button.type, ButtonType::But, ButtonType::Menu, ButtonType::Block,
                  ButtonType::Popover);
    case MixarComponent::Dropdown:
      return ELEM(
          button.type, ButtonType::Menu, ButtonType::Block, ButtonType::Popover, ButtonType::But);
    case MixarComponent::Toggle:
      return ELEM(button.type,
                  ButtonType::Checkbox,
                  ButtonType::CheckboxN,
                  ButtonType::Toggle,
                  ButtonType::But);
    case MixarComponent::Input:
      return ELEM(button.type, ButtonType::Text, ButtonType::TextBox);
    case MixarComponent::Number:
      return ELEM(button.type, ButtonType::Num, ButtonType::NumSlider);
    case MixarComponent::Segment:
      return ELEM(button.type, ButtonType::Row, ButtonType::But);
    case MixarComponent::Surface:
      return ELEM(button.type, ButtonType::Roundbox, ButtonType::But, ButtonType::Menu,
                  ButtonType::Block, ButtonType::Popover);
    case MixarComponent::Label:
      return button.type == ButtonType::Label;
    default:
      return false;
  }
}

void mixar_style_button(Button *button,
                        const MixarComponent component,
                        const MixarVariant variant,
                        const float unit,
                        const float text_unit)
{
  if (!button || !supports(*button, component)) {
    return;
  }
  auto &style = button->mixar_style;
  style.component = component;
  style.variant = variant;
  style.card = MixarCardElement::None;
  style.unit = std::max(0.0f, unit);
  style.text_unit = std::max(0.0f, text_unit);
  if (!style.explicit_theme) {
    style.theme = unit > 0.0f ? MixarTheme::Zen : MixarTheme::LegacyMixar;
  }
}

void mixar_style_last(Layout *layout, const MixarComponent component, const MixarVariant variant,
                      const bool all_items, const bool selected)
{
  auto &buttons = layout->block()->buttons_ptrs;
  for (int64_t i = buttons.size(); i-- > 0;) {
    Button *button = buttons[i].get();
    Layout *owner = button->layout;
    while (owner && owner != layout) {
      owner = owner->parent();
    }
    if (!owner) {
      if (!all_items) {
        return;
      }
      continue;
    }
    if (supports(*button, component)) {
      mixar_style_button(button, component, variant);
      mixar_button_lit_set(button, selected);
      if (!all_items) {
        return;
      }
    }
  }
}

void mixar_button_lit_set(Button *button, const bool lit)
{
  if (button) {
    button->mixar_style.lit = lit;
  }
}

void mixar_style_new_buttons(Layout *layout,
                             const int64_t first,
                             const MixarComponent component,
                             const bool multiline)
{
  auto &buttons = layout->block()->buttons_ptrs;
  for (int64_t index = std::max<int64_t>(first, 0); index < buttons.size(); index++) {
    Button *button = buttons[index].get();
    mixar_style_button(button, component);
    if (multiline && component == MixarComponent::Input && button->type == ButtonType::Text) {
      button_flag_enable(button, BUT_TEXTEDIT_UPDATE);
    }
  }
}

void mixar_style_card(Button *button, const MixarCardElement element, const float payload)
{
  if (!button || element <= MixarCardElement::None || element >= MixarCardElement::Count) {
    return;
  }
  auto &style = button->mixar_style;
  style.component = MixarComponent::LegacyCard;
  style.card = element;
  style.lit = payload >= 0.5f;
  style.progress = std::clamp(payload, 0.0f, 1.0f);
  style.icon = MixarCardIcon(std::clamp(int(payload), 0, int(MixarCardIcon::Cross)));
  if (!style.explicit_theme) {
    style.theme = MixarTheme::LegacyMixar;
  }
}

const char *mixar_component_name(const MixarComponent component)
{
  switch (component) {
    case MixarComponent::Action:
      return "action";
    case MixarComponent::Dropdown:
      return "dropdown";
    case MixarComponent::Toggle:
      return "toggle";
    case MixarComponent::Input:
      return "input";
    case MixarComponent::Number:
      return "number";
    case MixarComponent::Segment:
      return "segment";
    case MixarComponent::Surface:
      return "surface";
    case MixarComponent::Label:
      return "label";
    case MixarComponent::GlassTool:
      return "glass_tool";
    case MixarComponent::Toolbar:
      return "toolbar";
    case MixarComponent::LegacyCard:
      return "legacy_card";
    default:
      return "native";
  }
}

const char *mixar_theme_name(const MixarTheme theme)
{
  switch (theme) {
    case MixarTheme::Zen:
      return "ZEN";
    case MixarTheme::LegacyMixar:
      return "LEGACY_MIXAR";
    default:
      return "NATIVE";
  }
}

const char *mixar_variant_name(const MixarVariant variant)
{
  switch (variant) {
    case MixarVariant::Secondary:
      return "SECONDARY";
    case MixarVariant::Ghost:
      return "GHOST";
    case MixarVariant::Danger:
      return "DANGER";
    default:
      return "PRIMARY";
  }
}

}  // namespace blender::ui
