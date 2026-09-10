/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "../interface_intern.hh"
#include "../interface_mixar_profile_card.hh"
#include "BKE_context.hh"
#include "DNA_userdef_types.h"
#include "UI_mixar.hh"
#include "testing/testing.h"

namespace blender::ui::tests {
TEST(MixarStyle, NativeDefaults)
{
  Button button;
  EXPECT_EQ(button.mixar_style.theme, MixarTheme::Native);
  EXPECT_EQ(button.mixar_style.component, MixarComponent::None);
  EXPECT_EQ(sizeof(MixarButtonStyle), 16);
}

TEST(MixarStyle, EnumValuesAreNeverPresentation)
{
  for (const int value : {3, 11, 27}) {
    Button button;
    button.type = ButtonType::Row;
    button.hardmin = -1;
    button.hardmax = value;
    mixar_style_button(&button, MixarComponent::Segment, MixarVariant::Primary, 1.0f);
    EXPECT_EQ(button.hardmin, -1);
    EXPECT_EQ(button.hardmax, value);
    UI_mixar_cinema_row_tag(&button, MixarCinemaRowKind::Action);
    EXPECT_EQ(button.hardmin, -1);
    EXPECT_EQ(button.hardmax, value);
    EXPECT_EQ(UI_mixar_card_element_get(&button), MixarCardElement::CinemaRow);
    EXPECT_EQ(UI_mixar_cinema_row_kind_get(&button), MixarCinemaRowKind::Option);
  }
}

TEST(MixarStyle, RangeAndBindingSurviveStyleChanges)
{
  for (const ButtonType type : {ButtonType::Num, ButtonType::NumSlider, ButtonType::Text}) {
    Button button;
    button.type = type;
    button.hardmin = -17;
    button.hardmax = 4096;
    button.softmin = -3;
    button.softmax = 27;
    int value = 11;
    button.poin = reinterpret_cast<char *>(&value);
    const MixarComponent component = type == ButtonType::Text ? MixarComponent::Input :
                                                                MixarComponent::Number;
    mixar_style_button(&button, component, MixarVariant::Primary, 1.5f);
    UI_mixar_cinema_row_tag(&button, MixarCinemaRowKind::Option);
    EXPECT_EQ(button.hardmin, -17);
    EXPECT_EQ(button.hardmax, 4096);
    EXPECT_EQ(button.softmin, -3);
    EXPECT_EQ(button.softmax, 27);
    EXPECT_EQ(button.poin, reinterpret_cast<char *>(&value));
    EXPECT_EQ(value, 11);
  }
}

TEST(MixarStyle, ExplicitNativeScopeAndUnsupportedType)
{
  Button button;
  button.type = ButtonType::Text;
  button.mixar_style.explicit_theme = true;
  mixar_style_button(&button, MixarComponent::Input);
  EXPECT_EQ(button.mixar_style.theme, MixarTheme::Native);
  mixar_style_button(&button, MixarComponent::Action);
  EXPECT_EQ(button.mixar_style.component, MixarComponent::Input);
  EXPECT_EQ(button.type, ButtonType::Text);
}

TEST(MixarStyle, CompatibilityPayloadIsBounded)
{
  Button button;
  button.type = ButtonType::But;
  button.hardmax = 27;
  mixar_style_card(&button, MixarCardElement::UsageBar, 2.0f);
  EXPECT_EQ(button.mixar_style.progress, 1.0f);
  EXPECT_EQ(button.hardmax, 27);
  EXPECT_EQ(button.mixar_style.theme, MixarTheme::LegacyMixar);
}
TEST(MixarStyle, NestedScopesAndEmptyCreation)
{
  Block block;
  uiStyle style{};
  Layout &root = block_layout(
      &block, LayoutDirection::Vertical, LayoutType::Panel, 0, 0, 400, 10, 0, &style);
  Layout &zen = root.column(false);
  zen.mixar_scope_set({MixarTheme::Zen, true});
  Layout &child = zen.column(false);
  EXPECT_EQ(child.mixar_scope().theme, MixarTheme::Zen);
  child.mixar_scope_set({MixarTheme::Native, true});
  EXPECT_EQ(zen.column(false).mixar_scope().theme, MixarTheme::Zen);
  EXPECT_EQ(root.column(false).mixar_scope().theme, MixarTheme::Native);
  auto earlier = std::make_unique<Button>();
  earlier->type = ButtonType::Text;
  block.buttons_ptrs.append(std::move(earlier));
  const int64_t start = mixar_button_count(&zen);
  /* A failed RNA item creates no buttons: previous siblings stay native. */
  mixar_style_new_buttons(&zen, start, MixarComponent::Input);
  EXPECT_EQ(block.buttons_ptrs.first()->mixar_style.component, MixarComponent::None);
  block_layout_free(&block);
}
}  // namespace blender::ui::tests
