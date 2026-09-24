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

#include <algorithm>
#include <string>

namespace blender::ui {
namespace {
using namespace mixar_chrome;

bool same_group(const Button &a, const Button &b)
{
  return a.alignnr != 0 && a.alignnr == b.alignnr &&
         b.mixar_style.component == MixarComponent::Toolbar &&
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
  const float u = UI_SCALE_FAC;
  const bool disabled = (button.flag & (BUT_DISABLED | BUT_INACTIVE)) != 0;
  const bool primary = button.mixar_style.variant == MixarVariant::Primary;
  const bool cinema = button.optype &&
                      (STREQ(button.optype->idname, "MIXAR_OT_director_enter") ||
                       STREQ(button.optype->idname, "MIXAR_OT_director_finish"));
  const bool ghost = button.mixar_style.variant == MixarVariant::Ghost;
  const bool compact = ghost && button.str.empty();
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
      MIXAR_THEME_LOAD(top, CinemaBrandTop);
      MIXAR_THEME_LOAD(bottom, CinemaBrandBottom);
      MIXAR_THEME_LOAD(active, CinemaPillOnB);
      /* Keep the banner's ramp in both states; brighten its green when active. */
      interp_v4_v4v4(top, top, active, motion.selected * 0.65f);
      draw_roundbox_corner_set(CNR_ALL);
      draw_roundbox_4fv_ex(&group, top, bottom, 1.0f, nullptr, 0.0f, radius);
    }
    else {
      mixar_card_fill_round(&group, radius, primary ? toolbar_primary : toolbar_background);
    }
    mixar_card_outline_round(&group, radius, primary ? toolbar_primary_border : toolbar_border, 1);
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
    const uchar *selected = compact ? toolbar_shading_selected :
                                     primary ? cinema_pill_fill_on_b : toolbar_primary;
    if (motion.selected > 0.0f && !cinema) {
      mixar_card_fill_round(&feedback, 3.0f * u, selected, motion.selected);
    }
    if (motion.hover > 0.0f) {
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
    const float x0 = cell.xmin + 12 * u, x1 = cell.xmax - 44 * u;
    if (x1 > x0) {
      rctf track{x0, x1, cy - 0.5f * u, cy + 0.5f * u};
      mixar_card_fill_round(&track, 0, toolbar_border);
      const double span = double(button.softmax) - button.softmin;
      const float factor = span > 0 ? std::clamp(
          float((button_value_get(&button) - button.softmin) / span), 0.0f, 1.0f) : 0.0f;
      const float x = x0 + (x1 - x0) * factor;
      rctf thumb{x - 2 * u, x + 2 * u, cy - 7 * u, cy + 7 * u};
      mixar_card_fill_round(&thumb, u, toolbar_border);
    }
    mixar_card_draw_text(font, &text, button.drawstr.c_str(), text_color, UI_STYLE_TEXT_RIGHT);
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
  mixar_card_draw_text(font, &text, label.c_str(), text_color,
                       (ghost || (primary && !menu)) && button.type != ButtonType::Label ?
                           UI_STYLE_TEXT_CENTER : UI_STYLE_TEXT_LEFT);
  return false;
}
}  // namespace blender::ui
