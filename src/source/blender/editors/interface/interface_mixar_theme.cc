/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 */

#include <cstring>

#include "BLI_listbase.h"

#include "DNA_theme_types.h"
#include "DNA_userdef_types.h"

#include "UI_mixar_theme.hh"
#include "UI_mixar_tokens.hh"

namespace blender::ui {

struct MixarThemeRec {
  bool agent_space;
  int offset;
  unsigned char fallback[4];
};

static const MixarThemeRec k_mixar_theme[] = {
    {false, offsetof(ThemeUI, mixar_canvas), {30, 30, 30, 255}},
    {false, offsetof(ThemeUI, mixar_panel), {38, 38, 38, 255}},
    {false, offsetof(ThemeUI, mixar_input), {30, 30, 30, 255}},
    {false, offsetof(ThemeUI, mixar_control), {51, 54, 53, 255}},
    {false, offsetof(ThemeUI, mixar_selected), {47, 89, 47, 255}},
    {false, offsetof(ThemeUI, mixar_text), {226, 226, 226, 255}},
    {false, offsetof(ThemeUI, mixar_text_strong), {244, 245, 243, 255}},
    {false, offsetof(ThemeUI, mixar_text_secondary), {168, 173, 168, 255}},
    {false, offsetof(ThemeUI, mixar_border), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_focus), {127, 155, 120, 255}},
    {false, offsetof(ThemeUI, mixar_primary), {47, 89, 47, 255}},
    {false, offsetof(ThemeUI, mixar_danger), {224, 72, 72, 255}},
    {false, offsetof(ThemeUI, mixar_warning), {224, 160, 48, 255}},
    {false, offsetof(ThemeUI, mixar_action), {38, 38, 38, 255}},
    {false, offsetof(ThemeUI, mixar_glyph), {226, 226, 226, 255}},
    {false, offsetof(ThemeUI, mixar_chip), {38, 38, 38, 255}},
    {false, offsetof(ThemeUI, mixar_chip_active), {47, 89, 47, 255}},
    {false, offsetof(ThemeUI, mixar_gray_800), {30, 30, 30, 255}},
    {false, offsetof(ThemeUI, mixar_gray_700), {51, 54, 53, 255}},
    {false, offsetof(ThemeUI, mixar_border_strong), {109, 111, 108, 255}},
    {false, offsetof(ThemeUI, mixar_bg), {38, 38, 38, 255}},
    {false, offsetof(ThemeUI, mixar_fg_1), {226, 226, 226, 255}},
    {false, offsetof(ThemeUI, mixar_fg_2), {199, 204, 199, 255}},
    {false, offsetof(ThemeUI, mixar_fg_3), {168, 173, 168, 255}},
    {false, offsetof(ThemeUI, mixar_fg_4), {109, 111, 108, 255}},
    {false, offsetof(ThemeUI, mixar_pane_wash), {38, 38, 38, 255}},
    {false, offsetof(ThemeUI, mixar_pane_pill_dim), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_pane_pill_on), {47, 89, 47, 255}},
    {false, offsetof(ThemeUI, mixar_brand), {47, 89, 47, 255}},
    {false, offsetof(ThemeUI, mixar_brand_text), {244, 245, 243, 255}},
    {false, offsetof(ThemeUI, mixar_queue), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_queue_count), {109, 111, 108, 255}},
    {false, offsetof(ThemeUI, mixar_slider_track), {38, 38, 38, 255}},
    {false, offsetof(ThemeUI, mixar_slider_thumb), {47, 89, 47, 255}},
    {false, offsetof(ThemeUI, mixar_slider_thumb_hover), {60, 107, 60, 255}},
    {false, offsetof(ThemeUI, mixar_slider_label), {244, 245, 243, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_fill), {30, 30, 30, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_border), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_on_a), {32, 88, 54, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_on_b), {58, 132, 87, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_border_on), {127, 155, 120, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_label), {80, 80, 80, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_label_on), {255, 255, 255, 255}},
    {false, offsetof(ThemeUI, mixar_viewport_fill), {30, 30, 30, 255}},
    {false, offsetof(ThemeUI, mixar_viewport_border), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_viewport_label), {168, 173, 168, 255}},
    {false, offsetof(ThemeUI, mixar_viewport_label_on), {226, 226, 226, 255}},
    {false, offsetof(ThemeUI, mixar_profile_fill), {38, 38, 38, 255}},
    {false, offsetof(ThemeUI, mixar_profile_label), {226, 226, 226, 255}},
    {false, offsetof(ThemeUI, mixar_profile_avatar), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_profile_glyph), {199, 204, 199, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_top), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_bottom), {38, 38, 38, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_hover), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_track), {38, 38, 38, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_text_on), {244, 245, 243, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_text_off), {199, 204, 199, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_text_disabled), {109, 111, 108, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_caption), {168, 173, 168, 217}},
    {false, offsetof(ThemeUI, mixar_cinema_row_slider_on), {47, 89, 47, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_card_top), {48, 51, 48, 245}},
    {false, offsetof(ThemeUI, mixar_cinema_card_bottom), {30, 30, 30, 245}},
    {false, offsetof(ThemeUI, mixar_cinema_label), {168, 173, 168, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_dimmer), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_keycap), {109, 111, 108, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_phone), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_chip), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_brand_top), {15, 15, 15, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_brand_bottom), {11, 49, 26, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_gate_fill), {217, 217, 217, 18}},
    {false, offsetof(ThemeUI, mixar_widget_border), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_ink), {244, 245, 243, 255}},
    {false, offsetof(ThemeUI, mixar_sunken), {30, 30, 30, 255}},
    {false, offsetof(ThemeUI, mixar_gradient_start), {38, 69, 21, 255}},
    {false, offsetof(ThemeUI, mixar_gradient_mid_a), {41, 76, 32, 255}},
    {false, offsetof(ThemeUI, mixar_gradient_mid_b), {44, 83, 40, 255}},
    {false, offsetof(ThemeUI, mixar_gradient_end), {47, 89, 47, 255}},
    {false, offsetof(ThemeUI, mixar_toolbar_background), {30, 30, 30, 255}},
    {false, offsetof(ThemeUI, mixar_toolbar_border), {63, 67, 66, 255}},
    {false, offsetof(ThemeUI, mixar_toolbar_primary), {38, 69, 21, 255}},
    {false, offsetof(ThemeUI, mixar_toolbar_primary_border), {47, 89, 47, 255}},
    {false, offsetof(ThemeUI, mixar_toolbar_text), {226, 226, 226, 255}},
    {false, offsetof(ThemeUI, mixar_toolbar_muted), {109, 111, 108, 255}},
    {false, offsetof(ThemeUI, mixar_toolbar_selected), {47, 89, 47, 255}},
    {false, offsetof(ThemeUI, mixar_glass_wash), {30, 30, 30, 51}},
    {false, offsetof(ThemeUI, mixar_sketch_ink), {105, 111, 108, 255}},
    {true, offsetof(ThemeSpace, agent_border), {109, 111, 108, 255}},
    {true, offsetof(ThemeSpace, agent_tab_active), {38, 69, 21, 255}},
    {true, offsetof(ThemeSpace, agent_accent), {47, 89, 47, 255}},
};

static_assert(sizeof(k_mixar_theme) / sizeof(k_mixar_theme[0]) == int(MixarThemeSlot::Count),
              "theme slot table must match MixarThemeSlot");

static const unsigned char *mixar_theme_stored(MixarThemeSlot slot)
{
  const int index = int(slot);
  if (index < 0 || index >= int(MixarThemeSlot::Count)) {
    return nullptr;
  }
  bTheme *theme = static_cast<bTheme *>(U.themes.first);
  if (theme == nullptr) {
    return nullptr;
  }
  const MixarThemeRec &rec = k_mixar_theme[index];
  unsigned char *base = rec.agent_space ? reinterpret_cast<unsigned char *>(&theme->space_agent_bubble) :
                                           reinterpret_cast<unsigned char *>(&theme->tui);
  return base + rec.offset;
}

static bool mixar_theme_is_set(const unsigned char color[4])
{
  return (color[0] | color[1] | color[2] | color[3]) != 0;
}

void mixar_theme_color_u(MixarThemeSlot slot, unsigned char out[4])
{
  const int index = int(slot);
  if (index < 0 || index >= int(MixarThemeSlot::Count)) {
    memset(out, 0, sizeof(unsigned char[4]));
    return;
  }
  const unsigned char *stored = mixar_theme_stored(slot);
  const unsigned char *src = (stored != nullptr && mixar_theme_is_set(stored)) ?
                                 stored :
                                 k_mixar_theme[index].fallback;
  memcpy(out, src, sizeof(unsigned char[4]));
}

void mixar_theme_copy_u(MixarThemeSlot slot, const unsigned char fallback[4], unsigned char out[4])
{
  if (int(slot) >= 0 && int(slot) < int(MixarThemeSlot::Count)) {
    /* Old preferences must use the current palette, not a caller's old artboard colors. */
    mixar_theme_color_u(slot, out);
  }
  else {
    memcpy(out, fallback, sizeof(unsigned char[4]));
  }
}

void mixar_theme_color_f(MixarThemeSlot slot, float out[4])
{
  unsigned char color[4];
  mixar_theme_color_u(slot, color);
  out[0] = float(color[0]) / 255.0f;
  out[1] = float(color[1]) / 255.0f;
  out[2] = float(color[2]) / 255.0f;
  out[3] = float(color[3]) / 255.0f;
}

const unsigned char *mixar_theme_color_ptr(MixarThemeSlot slot)
{
  static unsigned char cache[int(MixarThemeSlot::Count)][4];
  static unsigned char zero[4] = {};
  const int index = int(slot);
  if (index < 0 || index >= int(MixarThemeSlot::Count)) {
    return zero;
  }
  mixar_theme_color_u(slot, cache[index]);
  return cache[index];
}

void mixar_moodboard_canvas_color(float out[4])
{
  const bTheme *theme = static_cast<const bTheme *>(U.themes.first);
  /* TH_BACK chooses sidebar colors in TOOL_PROPS; the drawer is a canvas. */
  for (int i = 0; i < 3; i++) {
    out[i] = theme ? float(theme->space_mixie.back[i]) / 255.0f : 38.0f / 255.0f;
  }
  out[3] = 1.0f;
}

namespace mixar_tokens {

const Palette &mixar_zen()
{
  static Palette palette = zen;
  auto load = [](MixarThemeSlot slot, float out[4]) { mixar_theme_color_f(slot, out); };
  load(MixarThemeSlot::Canvas, palette.canvas);
  load(MixarThemeSlot::Panel, palette.panel);
  load(MixarThemeSlot::Input, palette.input);
  load(MixarThemeSlot::Control, palette.control);
  load(MixarThemeSlot::Selected, palette.selected);
  load(MixarThemeSlot::Text, palette.text);
  load(MixarThemeSlot::TextStrong, palette.strong);
  load(MixarThemeSlot::TextSecondary, palette.secondary);
  load(MixarThemeSlot::Border, palette.border);
  load(MixarThemeSlot::Focus, palette.focus);
  load(MixarThemeSlot::Primary, palette.primary);
  load(MixarThemeSlot::Danger, palette.danger);
  load(MixarThemeSlot::Warning, palette.warning);
  load(MixarThemeSlot::Action, palette.action);
  return palette;
}

}  // namespace mixar_tokens
}  // namespace blender::ui
