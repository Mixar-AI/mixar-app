/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Flat Zen scene-toolbar controls. Native layout, RNA and operators own input. */
#include "../interface_intern.hh"
#include "../interface_mixar_card_paint.hh"
#include "BLI_math_vector.h"
#include "BLI_string.h"
#include "RNA_access.hh"
#include "UI_interface_icons.hh"
#include "UI_mixar.hh"
#include "UI_mixar_chrome.hh"
#include "UI_mixar_motion.hh"
#include "UI_mixar_theme.hh"
#include "WM_types.hh"
#include "toolbar.hh"
#include "scenes_toggle.hh"
#include "cinema_label.hh"

#include <algorithm>
#include <cmath>
#include <string>

namespace blender::ui {
namespace {
using namespace mixar_chrome;

bool same_group(const Button &a, const Button &b)
{
  return a.alignnr != 0 && a.alignnr == b.alignnr &&
         (b.mixar_style.component == MixarComponent::Toolbar ||
          (a.mixar_style.theme == MixarTheme::Zen &&
           a.block->name == "VIEW3D_HT_tool_header" &&
           ELEM(b.type, ButtonType::Color, ButtonType::Num, ButtonType::NumSlider))) &&
         !(b.flag & (UI_HIDDEN | UI_SCROLLED));
}

rctf group_rect(const Button &button, const rcti &bounds, bool &first)
{
  rctf group = button.rect;
  first = true;
  bool seen_self = false;
  for (const Button &other : button.block->buttons()) {
    if (&other == &button) {
      seen_self = true;
    }
    else if (same_group(button, other)) {
      BLI_rctf_union(&group, &other.rect);
      if (!seen_self) {
        first = false;
      }
    }
  }
  const float sx = BLI_rcti_size_x(&bounds) / std::max(BLI_rctf_size_x(&button.rect), 0.001f);
  const float sy = BLI_rcti_size_y(&bounds) / std::max(BLI_rctf_size_y(&button.rect), 0.001f);
  return {bounds.xmin + (group.xmin - button.rect.xmin) * sx,
          bounds.xmax + (group.xmax - button.rect.xmax) * sx,
          bounds.ymin + (group.ymin - button.rect.ymin) * sy,
          bounds.ymax + (group.ymax - button.rect.ymax) * sy};
}

void icon(const int id, const float x, const float y, const uchar *color, const float size)
{
  icon_draw_ex(x, y, id, 1.0f, 1.0f, 0.0f, color, false, nullptr, false, size / 16.0f);
}

/** The floating Zen bar's light Brightness slider (Point/Area/Spot W, Sun W/m^2). */
bool adaptive_light_energy(const Button &button)
{
  if (button.block->name != "VIEW3D_HT_tool_header" ||
      button.mixar_style.theme != MixarTheme::Zen || !button.rnaprop || !button.rnapoin.type ||
      !STREQ(RNA_property_identifier(button.rnaprop), "energy"))
  {
    return false;
  }
  const char *owner = RNA_struct_identifier(button.rnapoin.type);
  return STREQ(owner, "PointLight") || STREQ(owner, "AreaLight") ||
         STREQ(owner, "SpotLight") || STREQ(owner, "SunLight");
}

/** Brightness reads as "5000 W" / "12.5" / "3.00": large wattages need no
 * thousandths, and the native string keeps units. Typing still edits the
 * full-precision value, because this only runs when no edit string exists. */
std::string adaptive_light_energy_label(Button &button)
{
  const double value = std::abs(button_value_get(&button));
  const int precision = value >= 100.0 ? 0 : value >= 10.0 ? 1 : 2;
  char str[UI_MAX_DRAW_STR];
  button_string_get_ex(&button, str, sizeof(str), precision, false, nullptr);
  return str;
}
}  // namespace

bool mixar_toolbar_sample_range(Button &button)
{
  if (button.mixar_style.component != MixarComponent::Toolbar ||
      button.type != ButtonType::NumSlider || !button.rnaprop || !button.rnapoin.type)
  {
    return false;
  }
  const char *owner = RNA_struct_identifier(button.rnapoin.type);
  const char *property = RNA_property_identifier(button.rnaprop);
  float maximum;
  if (STREQ(owner, "CyclesRenderSettings") &&
      (STREQ(property, "samples") || STREQ(property, "preview_samples"))) {
    maximum = 1024.0f;
  }
  else if (STREQ(owner, "SceneEEVEE") &&
           (STREQ(property, "taa_render_samples") || STREQ(property, "taa_samples"))) {
    maximum = 256.0f;
  }
  else if (adaptive_light_energy(button)) {
    maximum = STREQ(owner, "SunLight") ? 10.0f : 5000.0f;
    button.softmin = 0.0f;
    button.softmax = maximum;
    return true;
  }
  else {
    return false;
  }
  /* Keep the track useful even when a file or typed edit contains a larger
   * value. Only dragging is bounded: native text editing uses the hard range. */
  button.softmin = std::clamp(1.0f, button.hardmin, button.hardmax);
  button.softmax = std::clamp(maximum, button.softmin, button.hardmax);
  return true;
}

bool mixar_toolbar_draw(Button &button, uiWidgetColors &colors, const rcti &bounds)
{
  if (mixar_scenes_toggle_is_button(button)) {
    mixar_scenes_toggle_draw(button, bounds);
    return false;
  }
  const bool adaptive = button.mixar_style.theme == MixarTheme::Zen &&
                        button.block->name == "VIEW3D_HT_tool_header";
  const uchar *toolbar_background = mixar_theme_color_ptr(MixarThemeSlot::ToolbarBackground);
  const uchar *toolbar_border = mixar_theme_color_ptr(MixarThemeSlot::ToolbarBorder);
  const uchar *toolbar_primary = mixar_theme_color_ptr(MixarThemeSlot::ToolbarPrimary);
  const uchar *toolbar_primary_border = mixar_theme_color_ptr(MixarThemeSlot::ToolbarPrimaryBorder);
  const uchar *toolbar_text = mixar_theme_color_ptr(MixarThemeSlot::ToolbarText);
  const uchar *toolbar_muted = mixar_theme_color_ptr(MixarThemeSlot::ToolbarMuted);
  const uchar *toolbar_selected = mixar_theme_color_ptr(MixarThemeSlot::ToolbarSelected);
  const float u = UI_SCALE_FAC;
  const bool disabled = (button.flag & (BUT_DISABLED | BUT_INACTIVE)) != 0;
  const bool primary = button.mixar_style.variant == MixarVariant::Primary;
  const bool cinema = button.optype &&
                      (STREQ(button.optype->idname, "MIXAR_OT_director_enter") ||
                       STREQ(button.optype->idname, "MIXAR_OT_director_finish"));
  const bool ghost = button.mixar_style.variant == MixarVariant::Ghost;
  const bool compact = !adaptive && ghost && button.str.empty();
  const MixarInteraction motion = mixar_button_motion(button);
  const uchar *text_color = disabled ? toolbar_muted : toolbar_text;
  copy_v4_v4_uchar(colors.text, text_color);
  copy_v4_v4_uchar(colors.text_sel, text_color);

  bool first;
  rctf group = group_rect(button, bounds, first);
  rctf cell;
  BLI_rctf_rcti_copy(&cell, &bounds);
  if (compact) {
    const float cy = BLI_rctf_cent_y(&cell);
    group.ymin = cell.ymin = cy - 10.0f * u;
    group.ymax = cell.ymax = cy + 10.0f * u;
  }
  const float radius = (compact ? 5.0f : 8.0f) * u;
  if (first) {
    if (cinema) {
      const float emphasis = motion.hover + (1.0f - motion.hover) * motion.press;
      mixar_cinema_background(group, motion.selected, emphasis);
    }
    else {
      mixar_card_fill_round(&group, radius,
                            adaptive ? mixar_theme_color_ptr(MixarThemeSlot::Gray700) :
                            primary ? toolbar_primary : toolbar_background);
      mixar_card_outline_round(
          &group, radius, primary ? toolbar_primary_border : toolbar_border, 1);
    }
  }

  /* The adaptive bar has a solid outer container and inset section controls.
   * Native button bounds still own popover placement, focus and hit testing. */
  if (adaptive && button.type == ButtonType::Popover) {
    rctf inset = cell;
    BLI_rctf_pad(&inset, -6.0f * u, -6.0f * u);
    mixar_card_fill_round(&inset, 5.0f * u,
                         mixar_theme_color_ptr(MixarThemeSlot::Input));
  }

  if (button.type == ButtonType::Label) {
    /* Captions are real labels within the group's native alignment number. */
    if (!ghost) {
      rctf divider = {cell.xmax - u * 0.5f, cell.xmax, cell.ymin, cell.ymax};
      mixar_card_fill_round(&divider, 0, toolbar_border);
    }
  }
  else {
    rctf feedback = cell;
    const float inset = ghost && !compact ? 4.0f * u : 1.0f * u;
    BLI_rctf_pad(&feedback, -inset, -inset);
    const uchar *selected = compact ? toolbar_selected :
                            primary ? mixar_theme_color_ptr(MixarThemeSlot::Selected) :
                                      toolbar_primary;
    if (motion.selected > 0.0f && !cinema) {
      mixar_card_fill_round(&feedback, 3.0f * u, selected, motion.selected);
    }
    if (motion.hover > 0.0f && !cinema) {
      mixar_card_fill_round(&feedback, 3.0f * u, toolbar_text, motion.hover * 0.07f);
    }
  }

  if (button.editstr) {
    /* Native caret, selection, numeric parsing, Enter and Escape stay intact. */
    return true;
  }
  uiFontStyle font = mixar_card_font(ghost && !compact && button.type != ButtonType::Label ?
                                       0.70f : 0.95f, 0);
  rcti text = bounds;
  const float pad = (ghost && button.type != ButtonType::Label ? 2 : 12) * u;
  text.xmin += pad;
  text.xmax -= pad;

  if (ELEM(button.type, ButtonType::Num, ButtonType::NumSlider)) {
    const float cy = BLI_rctf_cent_y(&cell);
    const std::string value = adaptive_light_energy(button) ? adaptive_light_energy_label(button) :
                                                              button.drawstr;
    /* The value owns a right-aligned column the track never enters. Lights reserve
     * one fixed column ("5000" wide) so Point, Spot, Area and Sun tracks match
     * and dragging never moves the track end; wider text (a typed 100000) still
     * pushes the track left instead of drawing over it. The gap clears the
     * thumb, which extends 2u past the track end at full value. */
    const float reserve = adaptive_light_energy(button) ?
                              float(fontstyle_string_width(&font, "00000")) :
                              0.0f;
    const float value_width = std::max(reserve,
                                       float(fontstyle_string_width(&font, value.c_str())));
    const float x0 = cell.xmin + 12 * u;
    const float x1 = std::min(cell.xmax - 44 * u, float(text.xmax) - value_width - 8 * u);
    if (x1 > x0) {
      rctf track{x0, x1, cy - (adaptive ? 1.0f : 0.5f) * u, cy + (adaptive ? 1.0f : 0.5f) * u};
      mixar_card_fill_round(&track, 0, adaptive ? toolbar_muted : toolbar_border);
      const double span = double(button.softmax) - button.softmin;
      const float factor = span > 0 ? std::clamp(
          float((button_value_get(&button) - button.softmin) / span), 0.0f, 1.0f) : 0.0f;
      const float x = x0 + (x1 - x0) * factor;
      rctf thumb{x - 2 * u, x + 2 * u, cy - 7 * u, cy + 7 * u};
      mixar_card_fill_round(&thumb, u, adaptive ? toolbar_text : toolbar_border);
    }
    mixar_card_draw_text(font, &text, value.c_str(), text_color, UI_STYLE_TEXT_RIGHT);
    return false;
  }
  if (button.str.empty() && button.icon) {
    const float size = 16 * u;
    icon(button.icon, BLI_rctf_cent_x(&cell) - size / 2,
         BLI_rctf_cent_y(&cell) - size / 2, text_color, size);
    return false;
  }

  const bool menu = ELEM(button.type, ButtonType::Menu, ButtonType::Pulldown, ButtonType::Popover);
  if (menu) {
    const float size = 12 * u;
    const bool export_action = button.icon == ICON_EXPORT;
    icon(export_action ? ICON_FORWARD : ICON_DOWNARROW_HLT,
         cell.xmax - 24 * u, BLI_rctf_cent_y(&cell) - size / 2, text_color, size);
    text.xmax -= 14 * u;
  }
  std::string label = button.drawstr.empty() ? button.str : button.drawstr;
  while (!label.empty() && (label.back() == ':' || label.back() == ' ')) {
    label.pop_back();
  }
  if (button.type == ButtonType::Menu) {
    /* Value chips use capitals; preserve UTF-8 bytes and native enum identities. */
    for (char &c : label) {
      if (c >= 'a' && c <= 'z') {
        c -= 'a' - 'A';
      }
    }
  }
  /* Standalone actions center their label inside equal horizontal padding.
   * Menus retain their left label and reserved trailing chevron. */
  if (cinema) {
    /* The shared painter owns its padding, exactly as in the Engine host. */
    mixar_cinema_label(bounds, label.c_str(), motion.selected, disabled, button.icon);
    return false;
  }
  mixar_card_draw_text(font, &text, label.c_str(), text_color,
                       (ghost || (primary && !menu)) && button.type != ButtonType::Label ?
                           UI_STYLE_TEXT_CENTER : UI_STYLE_TEXT_LEFT);
  return false;
}
}  // namespace blender::ui
