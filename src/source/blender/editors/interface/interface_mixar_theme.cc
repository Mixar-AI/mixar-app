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
    {false, offsetof(ThemeUI, mixar_canvas), {18, 18, 18, 255}},
    {false, offsetof(ThemeUI, mixar_panel), {45, 45, 45, 255}},
    {false, offsetof(ThemeUI, mixar_input), {18, 18, 18, 255}},
    {false, offsetof(ThemeUI, mixar_control), {49, 49, 49, 255}},
    {false, offsetof(ThemeUI, mixar_selected), {72, 72, 72, 255}},
    {false, offsetof(ThemeUI, mixar_text), {226, 226, 226, 255}},
    {false, offsetof(ThemeUI, mixar_text_strong), {255, 255, 255, 255}},
    {false, offsetof(ThemeUI, mixar_text_secondary), {117, 117, 117, 255}},
    {false, offsetof(ThemeUI, mixar_border), {65, 65, 65, 255}},
    {false, offsetof(ThemeUI, mixar_focus), {0, 192, 199, 255}},
    {false, offsetof(ThemeUI, mixar_primary), {26, 64, 38, 255}},
    {false, offsetof(ThemeUI, mixar_danger), {224, 72, 72, 255}},
    {false, offsetof(ThemeUI, mixar_warning), {224, 160, 48, 255}},
    {false, offsetof(ThemeUI, mixar_action), {29, 29, 29, 255}},
    {false, offsetof(ThemeUI, mixar_glyph), {228, 228, 228, 255}},
    {false, offsetof(ThemeUI, mixar_chip), {29, 29, 29, 255}},
    {false, offsetof(ThemeUI, mixar_chip_active), {50, 50, 50, 255}},
    {false, offsetof(ThemeUI, mixar_gray_800), {31, 31, 31, 255}},
    {false, offsetof(ThemeUI, mixar_gray_700), {42, 42, 42, 255}},
    {false, offsetof(ThemeUI, mixar_border_strong), {46, 46, 46, 255}},
    {false, offsetof(ThemeUI, mixar_bg), {20, 20, 20, 255}},
    {false, offsetof(ThemeUI, mixar_fg_1), {230, 230, 230, 255}},
    {false, offsetof(ThemeUI, mixar_fg_2), {200, 200, 200, 255}},
    {false, offsetof(ThemeUI, mixar_fg_3), {140, 140, 140, 255}},
    {false, offsetof(ThemeUI, mixar_fg_4), {90, 90, 90, 255}},
    {false, offsetof(ThemeUI, mixar_pane_wash), {19, 20, 19, 255}},
    {false, offsetof(ThemeUI, mixar_pane_pill_dim), {60, 60, 60, 255}},
    {false, offsetof(ThemeUI, mixar_pane_pill_on), {71, 71, 71, 255}},
    {false, offsetof(ThemeUI, mixar_brand), {52, 199, 110, 255}},
    {false, offsetof(ThemeUI, mixar_brand_text), {13, 19, 15, 255}},
    {false, offsetof(ThemeUI, mixar_queue), {66, 66, 66, 255}},
    {false, offsetof(ThemeUI, mixar_queue_count), {108, 108, 108, 255}},
    {false, offsetof(ThemeUI, mixar_slider_track), {29, 29, 29, 255}},
    {false, offsetof(ThemeUI, mixar_slider_thumb), {57, 57, 57, 255}},
    {false, offsetof(ThemeUI, mixar_slider_thumb_hover), {70, 70, 70, 255}},
    {false, offsetof(ThemeUI, mixar_slider_label), {255, 255, 255, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_fill), {14, 14, 14, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_border), {63, 63, 63, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_on_a), {32, 88, 54, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_on_b), {58, 132, 87, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_border_on), {87, 176, 124, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_label), {80, 80, 80, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_pill_label_on), {255, 255, 255, 255}},
    {false, offsetof(ThemeUI, mixar_viewport_fill), {5, 5, 5, 255}},
    {false, offsetof(ThemeUI, mixar_viewport_border), {103, 103, 103, 255}},
    {false, offsetof(ThemeUI, mixar_viewport_label), {115, 115, 115, 255}},
    {false, offsetof(ThemeUI, mixar_viewport_label_on), {222, 222, 222, 255}},
    {false, offsetof(ThemeUI, mixar_profile_fill), {27, 27, 27, 255}},
    {false, offsetof(ThemeUI, mixar_profile_label), {236, 236, 236, 255}},
    {false, offsetof(ThemeUI, mixar_profile_avatar), {60, 60, 60, 255}},
    {false, offsetof(ThemeUI, mixar_profile_glyph), {210, 210, 210, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_top), {88, 88, 88, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_bottom), {36, 36, 36, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_hover), {46, 46, 46, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_track), {38, 38, 38, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_text_on), {255, 255, 255, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_text_off), {180, 180, 180, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_text_disabled), {99, 99, 99, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_row_caption), {102, 102, 102, 217}},
    {false, offsetof(ThemeUI, mixar_cinema_row_slider_on), {42, 121, 73, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_card_top), {34, 35, 35, 245}},
    {false, offsetof(ThemeUI, mixar_cinema_card_bottom), {11, 11, 11, 245}},
    {false, offsetof(ThemeUI, mixar_cinema_label), {128, 128, 128, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_dimmer), {55, 55, 55, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_keycap), {100, 100, 100, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_phone), {56, 56, 56, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_chip), {80, 80, 80, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_brand_top), {11, 49, 26, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_brand_bottom), {15, 15, 15, 255}},
    {false, offsetof(ThemeUI, mixar_cinema_gate_fill), {217, 217, 217, 18}},
    {false, offsetof(ThemeUI, mixar_widget_border), {38, 38, 38, 255}},
    {false, offsetof(ThemeUI, mixar_ink), {10, 10, 10, 255}},
    {false, offsetof(ThemeUI, mixar_sunken), {15, 15, 15, 255}},
    {true, offsetof(ThemeSpace, agent_border), {0, 255, 140, 255}},
    {true, offsetof(ThemeSpace, agent_tab_active), {24, 62, 37, 255}},
    {true, offsetof(ThemeSpace, agent_accent), {43, 124, 75, 255}},
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
  const unsigned char *stored = mixar_theme_stored(slot);
  const unsigned char *src = (stored != nullptr && mixar_theme_is_set(stored)) ? stored : fallback;
  memcpy(out, src, sizeof(unsigned char[4]));
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
