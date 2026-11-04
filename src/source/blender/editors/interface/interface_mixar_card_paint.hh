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
 *
 * This is also the ONE seam the whole interface crosses to become liquid
 * glass: `mixar_card_fill_round` is the flat shape a control needs and
 * `mixar_card_glass_round` is the kit's pane a surface wants, side by side so
 * a painter file picks one per shape without learning the kit.
 */

#pragma once

#include <cstring>

#include "BLI_math_color.h"
#include "BLI_rect.h"
#include "BLI_sys_types.h"

#include "DNA_userdef_types.h"

#include "ED_mixar_glass.hh"

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

/**
 * The kit's pane, where a flat `mixar_card_fill_round` used to sit.
 *
 * The interface sorts into surfaces and controls. A surface is a pane the user
 * reads as a sheet of glass over something else — a button bed, a chip, a
 * card, a pill. A control is a shape that has to stay flat to read as
 * machinery — a slider track is a groove, a thumb is a knob, an avatar disc is
 * a picture. A glassed track shows the surface under it and stops reading as a
 * groove, so the two need different draws and this is where a painter picks
 * one. The kit itself never has to be learned to do so.
 *
 * A surface that crosses this seam adopts the role's material wholesale — no
 * call site chooses a tint, which is what keeps the family from drifting
 * (`ED_mixar_glass.hh`) and re-toning the UI to one table edit. Identity that
 * is not the bed stays where it was: an accent button keeps its teal ink and
 * its teal stroke, drawn as before.
 *
 * `rad` is passed rather than taken from the role because every surface
 * measured its own corner against its own height; a pane that changed shape on
 * conversion would be a different surface. The role still picks the material.
 *
 * `alpha` scales the WHOLE pane — every layer at once, see the header — so it
 * is a hover lift or a fade, never a tint strength. The flat fill's alphas
 * meant "this much colour over an opaque bed" and do not transfer to a pane,
 * which carries its own ramp and its own alphas.
 *
 * No outline: the kit draws the family's rim. A surface that needs a coloured
 * stroke keeps its own `mixar_card_outline_round` call after this one.
 *
 * Specular is always off here. Widget painters hand block coordinates, and the
 * streak's scissor is region-px — a streak placed from this seam lands wrong.
 * Region-space callers (island, chat, moodboard, viewport panel) go through
 * `mixar_glass_draw` / their own wrappers and can keep the streak.
 *
 * The kit takes region-px `rcti` and the design system works in `rctf`; the
 * conversion is exact for the integer rects the layout hands out.
 */
inline void mixar_card_glass_round(const rctf *rect,
                                   const float rad,
                                   const eMixarGlassRole role,
                                   const float alpha = 1.0f)
{
  rcti pane;
  BLI_rcti_rctf_copy(&pane, rect);
  MixarGlassStyle style;
  style.role = role;
  style.radius = rad;
  style.alpha = alpha;
  style.draw_specular = false;
  mixar_glass_draw(pane, style);
}
}  // namespace blender::ui
