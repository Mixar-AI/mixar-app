/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "../interface_intern.hh"
#include "UI_mixar.hh"
#include <algorithm>

namespace blender::ui {

int64_t mixar_button_count(const Layout *layout)
{
  return layout->block()->buttons_ptrs.size();
}

static bool supports(const Button &button, const MixarComponent component)
{
  switch (component) {
    case MixarComponent::Action:
      return button.type == ButtonType::But;
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
      return button.type == ButtonType::Roundbox;
    case MixarComponent::Label:
      return button.type == ButtonType::Label;
    default:
      return false;
  }
}

void mixar_style_button(Button *button,
                        const MixarComponent component,
                        const MixarVariant variant,
                        const float unit)
{
  if (!button || !supports(*button, component)) {
    return;
  }
  auto &style = button->mixar_style;
  style.component = component;
  style.variant = variant;
  style.card = MixarCardElement::None;
  style.unit = std::max(0.0f, unit);
  if (!style.explicit_theme) {
    style.theme = unit > 0.0f ? MixarTheme::Zen : MixarTheme::LegacyMixar;
  }
}

void mixar_style_last(Layout *layout, const MixarComponent component, const MixarVariant variant)
{
  auto &buttons = layout->block()->buttons_ptrs;
  for (int64_t i = buttons.size(); i-- > 0;) {
    Button *button = buttons[i].get();
    Layout *owner = button->layout;
    while (owner && owner != layout) {
      owner = owner->parent();
    }
    if (!owner) {
      return;
    }
    if (supports(*button, component)) {
      mixar_style_button(button, component, variant);
      return;
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
