/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Drawing primitives shared by the Mixar account card's element
 * painters. Header-inline rather than a translation unit of its own —
 * these are all one-liners over the roundbox and font-style APIs, and
 * keeping them inline lets each painter file stay self-contained.
 *
 * Names are prefixed `mixar_card_` because they land in the enclosing
 * translation unit's namespace alongside Blender's own helpers.
 */

#pragma once

#include <cstring>

#include "BLI_math_color.h"
#include "BLI_rect.h"
#include "BLI_sys_types.h"

#include "DNA_userdef_types.h"

#include "UI_interface_c.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

inline void mixar_card_to_float(const uchar src[4], float dst[4])
{
  rgba_uchar_to_float(dst, src);
}

inline void mixar_card_rect_to_rctf(const rcti *src, rctf *dst)
{
  BLI_rctf_rcti_copy(dst, src);
}

/** Theme widget font, optionally rescaled/reweighted. */
inline uiFontStyle mixar_card_font(const float scale, const int weight)
{
  uiFontStyle fs = style_get()->widget;
  fs.points *= scale;
  if (weight > 0) {
    fs.character_weight = weight;
  }
  /* The card paints its own background; the theme's text shadow was
   * tuned for widgets on the region background and muddies it here. */
  fs.shadow = 0;
  return fs;
}

inline void mixar_card_draw_text(const uiFontStyle &fs,
                                 const rcti *rect,
                                 const char *str,
                                 const uchar col[4],
                                 const FontStyleAlign align)
{
  if (str == nullptr || str[0] == '\0') {
    return;
  }
  fontstyle_set(&fs);
  const FontStyleDrawParams params{align, 0};
  fontstyle_draw(&fs, rect, str, strlen(str), col, &params);
}

/** Horizontal inset so content never touches the popover edge. */
inline int mixar_card_text_pad()
{
  return int(6.0f * UI_SCALE_FAC);
}

/* Button chrome in px @1x, shared with the layout builder.
 *
 * These live here rather than in the painter because the builder has to
 * measure exactly what the painter will spend — the layout sizes buttons
 * from the default font and knows nothing about the card's padding, so
 * any drift between the two numbers is silently eaten off the end of the
 * label (see `card_units_for_text`). */
inline constexpr float MIXAR_CARD_BUTTON_INSET = 4.0f;
inline constexpr float MIXAR_CARD_BUTTON_PAD = 13.0f;
inline constexpr float MIXAR_CARD_BUTTON_ICON = 15.0f;
inline constexpr float MIXAR_CARD_BUTTON_ICON_GAP = 9.0f;

/* Plan-chip metrics, shared for the same reason: the builder pins the
 * chip's width so the greeting beside it keeps the rest of the row. */
inline constexpr float MIXAR_CARD_PILL_SCALE = 0.85f;
inline constexpr float MIXAR_CARD_PILL_PAD = 9.0f;
inline constexpr float MIXAR_CARD_PILL_HEIGHT = 20.0f;

/** Total horizontal chrome a card button draws around its label, in px. */
inline float mixar_card_button_chrome(const bool has_icon)
{
  float chrome = (MIXAR_CARD_BUTTON_PAD + MIXAR_CARD_BUTTON_INSET) * 2.0f;
  if (has_icon) {
    chrome += MIXAR_CARD_BUTTON_ICON + MIXAR_CARD_BUTTON_ICON_GAP;
  }
  return chrome * UI_SCALE_FAC;
}

inline void mixar_card_fill_round(const rctf *rect,
                                  const float rad,
                                  const uchar col[4],
                                  const float alpha = 1.0f)
{
  float c[4];
  mixar_card_to_float(col, c);
  c[3] *= alpha;
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv(rect, true, rad, c);
}

inline void mixar_card_outline_round(const rctf *rect,
                                     const float rad,
                                     const uchar col[4],
                                     const float alpha)
{
  float c[4];
  mixar_card_to_float(col, c);
  c[3] = alpha;
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv(rect, false, rad, c);
}
}  // namespace blender::ui
