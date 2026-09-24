/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

/** \file
 * \ingroup edinterface
 *
 * Theme slots for Mixar UI painted in the last interface wave: the shared
 * Zen palette, widget grays, topbar chrome, cinema rows and the three island
 * greens. Glass wash stays a platform-split literal, not a slot.
 *
 * A stored color of all zeros (an old preference that predates the field)
 * falls back to the compiled palette. `MIXAR_THEME_LOAD` is two statements;
 * use it where a `const float name[4] = TOKEN;` used to stand.
 */

namespace blender::ui {

enum class MixarThemeSlot : int {
  Canvas,
  Panel,
  Input,
  Control,
  Selected,
  Text,
  TextStrong,
  TextSecondary,
  Border,
  Focus,
  Primary,
  Danger,
  Warning,
  Action,
  Glyph,
  Chip,
  ChipActive,
  Gray800,
  Gray700,
  BorderStrong,
  Bg,
  Fg1,
  Fg2,
  Fg3,
  Fg4,
  PaneWash,
  PanePillDim,
  PanePillOn,
  Brand,
  BrandText,
  Queue,
  QueueCount,
  SliderTrack,
  SliderThumb,
  SliderThumbHover,
  SliderLabel,
  CinemaPillFill,
  CinemaPillBorder,
  CinemaPillOnA,
  CinemaPillOnB,
  CinemaPillBorderOn,
  CinemaPillLabel,
  CinemaPillLabelOn,
  ViewportFill,
  ViewportBorder,
  ViewportLabel,
  ViewportLabelOn,
  ProfileFill,
  ProfileLabel,
  ProfileAvatar,
  ProfileGlyph,
  CinemaRowTop,
  CinemaRowBottom,
  CinemaRowHover,
  CinemaRowTrack,
  CinemaRowTextOn,
  CinemaRowTextOff,
  CinemaRowTextDisabled,
  CinemaRowCaption,
  CinemaRowSliderOn,
  CinemaCardTop,
  CinemaCardBottom,
  CinemaLabel,
  CinemaDimmer,
  CinemaKeycap,
  CinemaPhone,
  CinemaChip,
  CinemaBrandTop,
  CinemaBrandBottom,
  CinemaGateFill,
  WidgetBorder,
  Ink,
  Sunken,
  AgentBorder,
  AgentTabActive,
  AgentAccent,
  Count,
};

void mixar_theme_color_u(MixarThemeSlot slot, unsigned char out[4]);
void mixar_theme_copy_u(MixarThemeSlot slot, const unsigned char fallback[4], unsigned char out[4]);
void mixar_theme_color_f(MixarThemeSlot slot, float out[4]);
const unsigned char *mixar_theme_color_ptr(MixarThemeSlot slot);

inline float mixar_theme_chan(MixarThemeSlot slot, int channel)
{
  float color[4];
  mixar_theme_color_f(slot, color);
  return color[channel];
}

}  // namespace blender::ui

#define MIXAR_THEME_LOAD(var, slot) \
  float var[4]; \
  blender::ui::mixar_theme_color_f(blender::ui::MixarThemeSlot::slot, var)

#define MIXAR_THEME_BRACE(slot) \
  {blender::ui::mixar_theme_chan(blender::ui::MixarThemeSlot::slot, 0), \
    blender::ui::mixar_theme_chan(blender::ui::MixarThemeSlot::slot, 1), \
    blender::ui::mixar_theme_chan(blender::ui::MixarThemeSlot::slot, 2), \
    blender::ui::mixar_theme_chan(blender::ui::MixarThemeSlot::slot, 3)}
