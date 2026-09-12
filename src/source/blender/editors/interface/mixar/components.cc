/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "../interface_intern.hh"
#include "BLI_math_vector.h"
#include "DNA_userdef_types.h"
#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"
#include "UI_mixar.hh"
#include "UI_mixar_motion.hh"
#include "UI_mixar_tokens.hh"
#include <algorithm>

namespace blender::ui {
bool mixar_component_draw(Button &button, uiWidgetColors &colors, const rcti &bounds)
{
  using namespace mixar_tokens;
  const auto &style = button.mixar_style;
  const float u = style.unit > 0.0f ? style.unit : UI_SCALE_FAC * 0.65f;
  const bool disabled = (button.flag & (BUT_DISABLED | BUT_INACTIVE)) != 0;
  const MixarInteraction motion = mixar_button_motion(button);
  const bool selected = style.lit || (button.type != ButtonType::But &&
                                      (button.flag & (UI_SELECT | UI_SELECT_DRAW)));
  const bool editing = button.editstr != nullptr;
  rctf rect = {float(bounds.xmin), float(bounds.xmax), float(bounds.ymin), float(bounds.ymax)};
  const bool input = style.component == MixarComponent::Input;
  const bool label = style.component == MixarComponent::Label;
  /* Custom surfaces draw their content first; a Ghost surface adds only native
   * interaction feedback over that same hit rectangle. No opaque backplate or
   * second label can hide the feature's text, icons, or exact value display. */
  if (style.component == MixarComponent::Surface && style.variant == MixarVariant::Ghost &&
      style.unit > 0.0f)
  {
    const float hover[4] = {1.0f, 1.0f, 1.0f, 0.055f * motion.hover};
    const float press[4] = {0.0f, 0.0f, 0.0f, 0.08f * motion.press};
    if (hover[3] > 0.0f) {
      mixar_fill_round(rect, radius * u, hover);
    }
    if (press[3] > 0.0f) {
      mixar_fill_round(rect, radius * u, press);
    }
    return button.icon != ICON_NONE;
  }
  const float *background = input ? zen.input : zen.control;
  if (style.component == MixarComponent::Surface) {
    background = button.type == ButtonType::But ? zen.action : zen.panel;
  }
  const float *foreground = disabled ? zen.secondary : zen.text;
  if (style.component == MixarComponent::Action) {
    switch (style.variant) {
      case MixarVariant::Primary:
        background = zen.primary;
        break;
      case MixarVariant::Secondary:
        background = zen.action;
        break;
      case MixarVariant::Ghost:
        background = zen.canvas;
        break;
      case MixarVariant::Danger:
        background = zen.danger;
        break;
    }
    foreground = disabled ? zen.secondary : zen.strong;
  }
  if (style.component == MixarComponent::Segment ||
      (style.component == MixarComponent::Toggle && style.unit == 0.0f))
  {
    background = zen.control;
    foreground = disabled || !selected ? zen.secondary : zen.text;
  }
  float fill[4];
  copy_v4_v4(fill, background);
  if (style.component == MixarComponent::Segment ||
      (style.component == MixarComponent::Toggle && style.unit == 0.0f) ||
      (style.component == MixarComponent::Surface && button.type == ButtonType::But))
  {
    interp_v4_v4v4(fill, background, zen.selected, motion.selected);
  }
  if (!input) {
    for (int i = 0; i < 3; i++) {
      fill[i] = std::clamp(
          (fill[i] + 0.035f * motion.hover) * (1.0f - 0.10f * motion.press), 0.0f, 1.0f);
    }
  }
  if (!label) {
    mixar_fill_round(rect, radius * u * (input ? 2.0f : 1.0f), fill);
    if (button.type == ButtonType::NumSlider && !editing) {
      const double range = double(button.softmax) - double(button.softmin);
      const float fraction =
          range > 0.0 ?
              float(std::clamp((button_value_get(&button) - button.softmin) / range, 0.0, 1.0)) :
              0.0f;
      rctf progress = rect;
      progress.xmax = progress.xmin + BLI_rctf_size_x(&rect) * fraction;
      if (fraction > 0.0f) {
        mixar_fill_round(progress, radius * u, zen.selected);
      }
    }
    if (editing || (button.flag & BUT_REDALERT)) {
      draw_roundbox_4fv(
          &rect, false, radius * u, (button.flag & BUT_REDALERT) ? zen.danger : zen.focus);
    }
  }
  for (int i = 0; i < 4; i++) {
    colors.text[i] = colors.text_sel[i] = uchar(foreground[i] * 255.0f);
  }
  /* Native text owns RNA formatting, icons, selection, caret and IME. Explicit
   * island controls use their already-resolved artboard font. */
  if (style.unit == 0.0f || input || style.component == MixarComponent::Number) {
    return true;
  }
  /* Explicit surfaces host feature-owned content. The button retains its
   * semantic label for accessibility and QA; only its backplate is painted. */
  if (style.component == MixarComponent::Surface) {
    return false;
  }
  const MixarTextStyle text_style = mixar_text_style(MixarTextRole::Body, u);
  const float cy = BLI_rctf_cent_y(&rect);
  float right = rect.xmax - padding * u;
  if (style.component == MixarComponent::Toggle) {
    const float on_w = mixar_text_width("ON", text_style) + 20.0f * u;
    const float off_w = mixar_text_width("OFF", text_style) + 20.0f * u;
    const float start = right + padding * u * 0.5f - on_w - off_w;
    rctf on = {start, start + on_w, rect.ymin + 4 * u, rect.ymax - 4 * u};
    rctf off = {on.xmax, on.xmax + off_w, on.ymin, on.ymax};
    rctf thumb = off;
    thumb.xmin = off.xmin + (on.xmin - off.xmin) * motion.selected;
    thumb.xmax = off.xmax + (on.xmax - off.xmax) * motion.selected;
    mixar_fill_round(thumb, radius * u, zen.selected);
    mixar_label_left(
        "ON", on.xmin + 10 * u, cy, text_style, selected ? foreground : zen.secondary);
    mixar_label_left(
        "OFF", off.xmin + 10 * u, cy, text_style, selected ? zen.secondary : foreground);
    right = start - gap * u;
  }
  if (style.component == MixarComponent::Dropdown) {
    right -= 18 * u;
    mixar_label_left("⌄", right + 6 * u, cy, text_style, foreground);
  }
  const float icon_space = button.icon ? (icon + icon_gap) * u : 0.0f;
  if (button.icon) {
    icon_draw_ex(rect.xmin + padding * u,
                 cy - icon * u * 0.5f,
                 button.icon,
                 1.0f,
                 disabled ? 0.45f : 1.0f,
                 0.0f,
                 colors.text,
                 false,
                 nullptr,
                 false,
                 icon * u / 16.0f);
  }
  /* Segment widths reserve 30 units total; the compact primary action is
   * only 114 units wide. Reusing dropdown padding would clip their labels.
   * Two physical pixels absorb integer button-rectangle rounding. */
  float text_width = right - rect.xmin - padding * u - icon_space;
  if (style.component == MixarComponent::Segment) {
    text_width = BLI_rctf_size_x(&rect) - 24.0f * u;
  }
  else if (style.component == MixarComponent::Action && !button.icon) {
    text_width = BLI_rctf_size_x(&rect) - 12.0f * u;
  }
  const std::string text = mixar_fit_text(
      button.str.c_str(), std::max(0.0f, text_width + 2.0f), text_style);
  const float x = (button.icon ||
                   ELEM(style.component, MixarComponent::Toggle, MixarComponent::Dropdown)) ?
                      rect.xmin + padding * u + icon_space :
                      BLI_rctf_cent_x(&rect) - mixar_text_width(text.c_str(), text_style) * 0.5f;
  mixar_label_left(text.c_str(), x, cy, text_style, foreground);
  return false;
}
}  // namespace blender::ui
