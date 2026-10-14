/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar account card — text, divider and credit-balance drawing.
 *
 * Every card element paints its own glyphs: the heading needs a size
 * the generic widget text path cannot give it, and the buttons need
 * their icon and label to travel as one group. Widget dispatch therefore
 * clears both stock passes for the whole card. Action buttons live in
 * `interface_mixar_card_button.cc`; shared primitives in
 * `interface_mixar_card_paint.hh`.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLI_math_color.h"
#include "BLI_math_vector.h"
#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "BLF_api.hh"

#include "DNA_userdef_types.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_mixar_chrome.hh"
#include "UI_resources.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_palette.hh"
#include "interface_mixar_profile_card.hh"
#include "UI_mixar_theme.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

namespace {

/* -------------------------------------------------------------------- */
/* Elements                                                              */

void draw_heading(Button *but, rcti *rect)
{
  uchar fg1_u[4];
  mixar_theme_copy_u(MixarThemeSlot::Fg1, MX_FG_1, fg1_u);
  rcti text_rect = *rect;
  text_rect.xmin += mixar_card_text_pad();
  text_rect.xmax -= mixar_card_text_pad();

  /* An unusually long name shrinks rather than losing its tail. The
   * layout sized this rect from the default font; the heading is drawn
   * at #mixar_chrome::card_heading_scale, and the clip that resolves the
   * difference is silent (#BLF_clipping, no ellipsis). Point size tracks
   * width closely enough that one measurement lands it. */
  float scale = mixar_chrome::card_heading_scale;
  const uiFontStyle probe = mixar_card_font(scale, mixar_chrome::card_heading_weight);
  const float width = float(fontstyle_string_width(&probe, but->drawstr.c_str()));
  const float avail = float(BLI_rcti_size_x(&text_rect));
  if (width > avail && width > 0.0f) {
    scale = std::max(1.0f, scale * avail / width);
  }

  mixar_card_draw_text(mixar_card_font(scale, mixar_chrome::card_heading_weight),
            &text_rect,
            but->drawstr.c_str(),
            fg1_u,
            UI_STYLE_TEXT_LEFT);
}

void draw_muted(Button *but, rcti *rect, const FontStyleAlign align, const uchar col[4])
{
  rcti text_rect = *rect;
  text_rect.xmin += mixar_card_text_pad();
  text_rect.xmax -= mixar_card_text_pad();
  mixar_card_draw_text(mixar_card_font(mixar_chrome::caption_scale, 0), &text_rect, but->drawstr.c_str(), col, align);
}

void draw_pill(Button *but, rcti *rect)
{
  uchar border_strong_u[4], fg2_u[4];
  mixar_theme_copy_u(MixarThemeSlot::BorderStrong, MX_BORDER_STRONG, border_strong_u);
  mixar_theme_copy_u(MixarThemeSlot::Fg2, MX_FG_2, fg2_u);
  const uiFontStyle fs = mixar_card_font(MIXAR_CARD_PILL_SCALE, 0);
  fontstyle_set(&fs);

  const char *label = but->drawstr.c_str();
  const float label_w = BLF_width(fs.uifont_id, label, but->drawstr.size());
  const float pad_x = MIXAR_CARD_PILL_PAD * UI_SCALE_FAC;
  const float height = std::min(float(BLI_rcti_size_y(rect)),
                                MIXAR_CARD_PILL_HEIGHT * UI_SCALE_FAC);

  rctf chip;
  chip.xmax = float(rect->xmax);
  chip.xmin = std::max(float(rect->xmin), chip.xmax - label_w - pad_x * 2.0f);
  const float y_center = float(rect->ymin + rect->ymax) * 0.5f;
  chip.ymin = y_center - height * 0.5f;
  chip.ymax = y_center + height * 0.5f;

  GPU_blend(GPU_BLEND_ALPHA);
  const float rad = height * mixar_chrome::card_pill_radius;
  /* Plan chip sits on the card pane — CHIP role, with its own stronger stroke. */
  mixar_card_glass_round(&chip, rad, MIXAR_GLASS_CHIP);
  mixar_card_outline_round(&chip, rad, border_strong_u, 1.0f);
  GPU_blend(GPU_BLEND_NONE);

  rcti text_rect;
  BLI_rcti_init(&text_rect, int(chip.xmin), int(chip.xmax), int(chip.ymin), int(chip.ymax));
  mixar_card_draw_text(fs, &text_rect, label, fg2_u, UI_STYLE_TEXT_CENTER);
}

void draw_divider(rcti *rect)
{
  uchar border_strong_u[4];
  mixar_theme_copy_u(MixarThemeSlot::BorderStrong, MX_BORDER_STRONG, border_strong_u);
  const float y = float(rect->ymin + rect->ymax) * 0.5f;
  const float thickness = std::max(1.0f, U.pixelsize);

  rctf line;
  line.xmin = float(rect->xmin);
  line.xmax = float(rect->xmax);
  line.ymin = y - thickness * 0.5f;
  line.ymax = line.ymin + thickness;

  GPU_blend(GPU_BLEND_ALPHA);
  mixar_card_fill_round(&line, 0.0f, border_strong_u);
  GPU_blend(GPU_BLEND_NONE);
}

/**
 * The credit balance, e.g. "6,800 credits": heading weight, left-aligned.
 *
 * A plain number rather than a meter — the web dashboard prints the same
 * figure, so the two can never disagree about a denominator. An empty
 * balance (payload 1) turns danger-red; nothing else changes colour,
 * because an absolute count has no honest "warning" band.
 */
void draw_credit_balance(Button *but, rcti *rect)
{
  uchar fg1_u[4], danger_u[4];
  mixar_theme_copy_u(MixarThemeSlot::Fg1, MX_FG_1, fg1_u);
  mixar_theme_copy_u(MixarThemeSlot::Danger, MX_DANGER, danger_u);
  const bool is_empty = but->mixar_style.progress >= 1.0f;

  rcti text_rect = *rect;
  text_rect.xmin += mixar_card_text_pad();
  text_rect.xmax -= mixar_card_text_pad();

  /* Shrink rather than clip a very large balance: the layout sized this
   * rect from the default font and #BLF_clipping has no ellipsis. */
  float scale = mixar_chrome::card_heading_scale;
  const uiFontStyle probe = mixar_card_font(scale, mixar_chrome::card_heading_weight);
  const float width = float(fontstyle_string_width(&probe, but->drawstr.c_str()));
  const float avail = float(BLI_rcti_size_x(&text_rect));
  if (width > avail && width > 0.0f) {
    scale = std::max(1.0f, scale * avail / width);
  }

  mixar_card_draw_text(mixar_card_font(scale, mixar_chrome::card_heading_weight),
                       &text_rect,
                       but->drawstr.c_str(),
                       is_empty ? danger_u : fg1_u,
                       UI_STYLE_TEXT_LEFT);
}

/* -------------------------------------------------------------------- */
}  // namespace

/* -------------------------------------------------------------------- */
/* Public API                                                            */

bool UI_mixar_card_element_is_button(const MixarCardElement element)
{
  return ELEM(element,
              MixarCardElement::AccentButton,
              MixarCardElement::CardButton,
              MixarCardElement::DangerButton,
              MixarCardElement::GhostButton,
              MixarCardElement::ModeSliderLeft,
              MixarCardElement::ModeSliderRight,
              MixarCardElement::CinemaPill,
              MixarCardElement::ViewportPill,
              MixarCardElement::ProfilePill);
}

void UI_mixar_profile_card_draw_element(
    Button *but, uiWidgetColors *wcol, rcti *rect, const bool is_hover, const bool is_active)
{
  const MixarCardElement element = UI_mixar_card_element_get(but);

  /* Every card element now owns its own glyphs, so `wcol` is unused —
   * kept in the signature because it is the widget-callback shape and
   * dropping it would make this the odd one out. */
  UNUSED_VARS(wcol);
  uchar fg3_u[4], fg4_u[4], danger_u[4];
  mixar_theme_copy_u(MixarThemeSlot::Fg3, MX_FG_3, fg3_u);
  mixar_theme_copy_u(MixarThemeSlot::Fg4, MX_FG_4, fg4_u);
  mixar_theme_copy_u(MixarThemeSlot::Danger, MX_DANGER, danger_u);

  /* Topbar elements are buttons too, but they own their own chrome — check
   * them before the card-button painter claims them. */
  if (UI_mixar_topbar_draw_element(but, rect, element, is_hover, is_active)) {
    return;
  }

  if (UI_mixar_card_element_is_button(element)) {
    UI_mixar_card_button_draw(but, rect, element, is_hover, is_active);
    return;
  }

  switch (element) {
    case MixarCardElement::Heading:
      draw_heading(but, rect);
      break;
    case MixarCardElement::Muted:
      draw_muted(but, rect, UI_STYLE_TEXT_LEFT, fg4_u);
      break;
    case MixarCardElement::SectionLabel:
      draw_muted(but, rect, UI_STYLE_TEXT_LEFT, fg3_u);
      break;
    case MixarCardElement::MetaRight:
      draw_muted(but, rect, UI_STYLE_TEXT_RIGHT, fg4_u);
      break;
    case MixarCardElement::Pill:
      draw_pill(but, rect);
      break;
    case MixarCardElement::CreditBalance:
      draw_credit_balance(but, rect);
      break;
    case MixarCardElement::Divider:
      draw_divider(rect);
      break;
    case MixarCardElement::DangerText:
      draw_muted(but, rect, UI_STYLE_TEXT_LEFT, danger_u);
      break;
    default:
      break;
  }
}
}  // namespace blender::ui
