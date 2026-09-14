/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar topbar chrome: the animated Zen/Engine mode slider and the
 * "Cinema Mode" pill.
 *
 * Both are ordinary operator buttons tagged with a #MixarCardElement kind
 * (see `interface_mixar_section.cc`'s tag helpers), so Blender still lays
 * them out, sizes them and dispatches their clicks — only the pixels are
 * ours. Colours and chrome label scale live in `UI_mixar_chrome.hh`
 * (UI.svg 1x: slider track 225x28 rx7 #1D1D1D with a 106x23 rx7 #393939
 * thumb inset 2px; Cinema pill 150x27 fully rounded, #3F3F3F hairline
 * border, label graded #505050 -> white). Geometry stays on the layout.
 * Compact is the chrome host; these widgets keep the UI.svg sizes rather
 * than Compact's 32-unit control height.
 *
 * Cinema, viewport shading, and account chips are panes (`MIXAR_GLASS_PILL`);
 * the slider track/thumb and the account avatar disc stay flat — grooves and
 * pictures must not show the bar through them.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_math_base.h"
#include "BLI_rect.h"

#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"
#include "UI_mixar_chrome.hh"
#include "UI_mixar_motion.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_profile_card.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

namespace {

using mixar_chrome::label_scale;

/** Keep palette endpoints exact while native button runtime owns the transition. */
void blend_color(const uchar from[4], const uchar to[4], const float factor, uchar result[4])
{
  for (int i = 0; i < 4; i++) {
    result[i] = uchar(std::round(float(from[i]) + (float(to[i]) - from[i]) * factor));
  }
}

/* -------------------------------------------------------------------- */
/** \name Painters
 * \{ */

/** Centre \a str in \a rect using the theme widget font at chrome scale. */
void draw_label_centred(const rcti *rect, const char *str, const uchar col[4], const float scale)
{
  const uiFontStyle fs = mixar_card_font(scale, 0);
  mixar_card_draw_text(fs, rect, str, col, UI_STYLE_TEXT_CENTER);
}

/**
 * Centre \a str in \a rect, colouring each glyph along a left-to-right
 * ramp from \a col_a to \a col_b.
 *
 * Per-glyph rather than a shader: the label is a handful of characters, so
 * stepping the colour per advance is indistinguishable from a smooth ramp
 * and needs no new GPU state. Drawn through BLF directly because
 * #fontstyle_draw takes a single colour for the whole run.
 */
void draw_label_gradient(const rcti *rect,
                         const char *str,
                         const uchar col_a[4],
                         const uchar col_b[4],
                         const float scale)
{
  if (str == nullptr || str[0] == '\0') {
    return;
  }
  uiFontStyle fs = mixar_card_font(scale, 0);
  fontstyle_set(&fs);
  const int font = fs.uifont_id;

  const size_t len = strlen(str);
  const float total_w = BLF_width(font, str, len);
  float x = float(rect->xmin) + (float(BLI_rcti_size_x(rect)) - total_w) * 0.5f;

  /* Vertical centring on the ink box, matching #fontstyle_draw. */
  rcti box;
  BLF_boundbox(font, str, len, &box);
  const float y = float(rect->ymin) +
                  (float(BLI_rcti_size_y(rect)) - float(BLI_rcti_size_y(&box))) * 0.5f -
                  float(box.ymin);

  BLF_disable(font, BLF_CLIPPING);
  for (size_t i = 0; i < len;) {
    /* Step whole UTF-8 sequences so multi-byte glyphs are not split. */
    size_t step = 1;
    while (i + step < len && (uchar(str[i + step]) & 0xC0) == 0x80) {
      step++;
    }
    const float t = (total_w > 0.0f) ? (x - (float(rect->xmin) +
                                             (float(BLI_rcti_size_x(rect)) - total_w) * 0.5f)) /
                                           total_w :
                                       0.0f;
    uchar col[4];
    for (int c = 0; c < 4; c++) {
      col[c] = uchar(roundf(float(col_a[c]) + (float(col_b[c]) - float(col_a[c])) * t));
    }
    BLF_color4ubv(font, col);
    BLF_position(font, x, y, 0.0f);
    BLF_draw(font, str + i, step);
    x += BLF_width(font, str + i, step);
    i += step;
  }
}

/**
 * Mode slider, left half: the whole track plus the animated thumb, then
 * this half's label.
 *
 * The track spans both halves; it is derived from this button's rect by
 * mirroring it to the right, which is exact because the builder pins both
 * halves to the same `ui_units_x`.
 */
void draw_slider_left(Button *but, const rcti *rect)
{
  const float half_w = float(BLI_rcti_size_x(rect));
  rctf track;
  track.xmin = float(rect->xmin);
  track.xmax = float(rect->xmax) + half_w;
  track.ymin = float(rect->ymin);
  track.ymax = float(rect->ymax);

  const float height = BLI_rctf_size_y(&track);
  const float rad = height * 0.25f;
  const float inset = mixar_chrome::slider_thumb_inset * UI_SCALE_FAC;

  GPU_blend(GPU_BLEND_ALPHA);
  mixar_card_fill_round(&track, rad, mixar_chrome::slider_track);

  /* Payload is "this (left) half is live", so a live left half parks the
   * thumb at 0 and a live right half sends it to 1. */
  const MixarInteraction motion = mixar_button_motion(*but);
  const float pos = 1.0f - motion.selected;

  rctf thumb;
  thumb.xmin = track.xmin + inset + pos * half_w;
  thumb.xmax = thumb.xmin + half_w - inset * 2.0f;
  thumb.ymin = track.ymin + inset;
  thumb.ymax = track.ymax - inset;
  uchar fill[4];
  blend_color(mixar_chrome::slider_thumb,
              mixar_chrome::slider_thumb_hover,
              std::max(motion.hover, motion.press),
              fill);
  mixar_card_fill_round(&thumb, rad, fill);

  draw_label_centred(rect, but->drawstr.c_str(), mixar_chrome::slider_label, label_scale);
}

/** Mode slider, right half: label only — the left half drew the chrome. */
void draw_slider_right(Button *but, const rcti *rect)
{
  draw_label_centred(rect, but->drawstr.c_str(), mixar_chrome::slider_label, label_scale);
}

/**
 * "Cinema Mode": fully rounded pill — the design's dark chip at rest, the
 * whole pill filled green while directing.
 *
 * No separate switch widget: the fill is the state. A knob read as "here is
 * a control inside a button" when the button already IS the control.
 */
void draw_cinema_pill(Button *but, const rcti *rect)
{
  rctf pill;
  mixar_card_rect_to_rctf(rect, &pill);
  /* The design's pill is shorter than the topbar's button height; inset so
   * it reads as a floating chip rather than a full-height slab. */
  const float inset = 1.0f * UI_SCALE_FAC;
  BLI_rctf_pad(&pill, -inset, -inset);

  const float rad = BLI_rctf_size_y(&pill) * 0.5f;
  /* Operator press is separate from the semantic selected state. The central
   * sampler reads `lit`, so holding the mouse never turns an idle pill green. */
  const MixarInteraction motion = mixar_button_motion(*but);
  const float emphasis = motion.hover + (1.0f - motion.hover) * motion.press;
  const float boost = 1.0f + 0.12f * motion.hover + (0.22f - 0.12f * motion.hover) * motion.press;
  float top[4], bottom[4];
  mixar_card_to_float(mixar_chrome::cinema_pill_fill_on_b, top);
  mixar_card_to_float(mixar_chrome::cinema_pill_fill_on_a, bottom);
  for (int i = 0; i < 3; i++) {
    top[i] = std::min(1.0f, top[i] * boost);
    bottom[i] = std::min(1.0f, bottom[i] * boost);
  }
  /* Only semantic selection reveals the green wash, over the glass bed. */
  top[3] = bottom[3] = motion.selected;

  GPU_blend(GPU_BLEND_ALPHA);
  mixar_card_glass_round(&pill, rad, MIXAR_GLASS_PILL, 0.84f + 0.16f * emphasis);
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv_ex(&pill, top, bottom, 1.0f, nullptr, 0.0f, rad);
  uchar border[4];
  blend_color(mixar_chrome::cinema_pill_border,
              mixar_chrome::cinema_pill_border_on,
              motion.selected,
              border);
  const float border_alpha = 0.85f + 0.05f * motion.selected;
  mixar_card_outline_round(&pill, rad, border, border_alpha + (1.0f - border_alpha) * emphasis);

  /* The label remains in place while its resting gradient resolves to white. */
  uchar label_start[4];
  blend_color(mixar_chrome::cinema_pill_label_a,
              mixar_chrome::cinema_pill_label_b,
              motion.selected,
              label_start);
  draw_label_gradient(
      rect, but->drawstr.c_str(), label_start, mixar_chrome::cinema_pill_label_b, label_scale);
}

/** Zen viewport shading pill: "Solid" / "Rendered". */
void draw_viewport_pill(Button *but, const rcti *rect)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  const float hover_alpha = mixar_chrome::viewport_pill_dim +
                            (0.75f - mixar_chrome::viewport_pill_dim) * motion.hover;
  const float press_alpha = hover_alpha + (0.85f - hover_alpha) * motion.press;
  const float alpha = press_alpha + (1.0f - press_alpha) * motion.selected;

  rctf pill;
  mixar_card_rect_to_rctf(rect, &pill);
  const float inset = 1.0f * UI_SCALE_FAC;
  BLI_rctf_pad(&pill, -inset, -inset);
  const float rad = BLI_rctf_size_y(&pill) * 0.5f;

  GPU_blend(GPU_BLEND_ALPHA);
  /* Dim/lit is the pane alpha so gloss and rim fade with the bed. */
  mixar_card_glass_round(&pill, rad, MIXAR_GLASS_PILL, alpha);
  mixar_card_outline_round(&pill, rad, mixar_chrome::viewport_pill_border, alpha);

  uchar label[4];
  blend_color(mixar_chrome::viewport_pill_label,
              mixar_chrome::viewport_pill_label_on,
              motion.selected,
              label);
  label[3] = uchar(255.0f * alpha);
  draw_label_centred(rect, but->drawstr.c_str(), label, label_scale);
}

/** Topbar account chip: slab + label + avatar disc with the person glyph. */
void draw_profile_pill(Button *but, const rcti *rect)
{
  rctf chip;
  mixar_card_rect_to_rctf(rect, &chip);
  const float inset = 1.0f * UI_SCALE_FAC;
  BLI_rctf_pad(&chip, -inset, -inset);

  const float height = BLI_rctf_size_y(&chip);
  const float rad = height * 0.5f;

  GPU_blend(GPU_BLEND_ALPHA);
  const MixarInteraction motion = mixar_button_motion(*but);
  mixar_card_glass_round(
      &chip, rad, MIXAR_GLASS_PILL, 0.9f + 0.1f * std::max(motion.hover, motion.press));

  /* Avatar disc caps the right end at full height, exactly as the design
   * has it (chip 27 tall, disc r=13.5). */
  rctf disc;
  disc.xmax = chip.xmax;
  disc.xmin = disc.xmax - height;
  disc.ymin = chip.ymin;
  disc.ymax = chip.ymax;
  mixar_card_fill_round(&disc, rad, mixar_chrome::profile_avatar);

  /* Stock person silhouette — the "no picture set" placeholder. Drawn
   * through the icon system so it matches Blender's own weight. */
  const float glyph = height * 0.72f;
  uchar mono_u[4];
  memcpy(mono_u, mixar_chrome::profile_glyph, sizeof(mono_u));
  icon_draw_ex(BLI_rctf_cent_x(&disc) - glyph * 0.5f,
               BLI_rctf_cent_y(&disc) - glyph * 0.5f,
               ICON_USER,
               /*aspect=*/16.0f / glyph,
               /*alpha=*/1.0f,
               /*desaturate=*/0.0f,
               mono_u,
               /*mono_border=*/false,
               /*text_overlay=*/nullptr);

  /* Label keeps the slab, clear of the disc. */
  rcti label_rect = *rect;
  label_rect.xmin += int(mixar_card_text_pad() * 2.0f);
  label_rect.xmax = int(disc.xmin - mixar_card_text_pad());
  const uiFontStyle fs = mixar_card_font(label_scale, 0);
  mixar_card_draw_text(
      fs, &label_rect, but->drawstr.c_str(), mixar_chrome::profile_label, UI_STYLE_TEXT_LEFT);
}

/** \} */

}  // namespace

/* -------------------------------------------------------------------- */
/* Public API                                                            */

bool UI_mixar_topbar_draw_element(Button *but,
                                  rcti *rect,
                                  const MixarCardElement element,
                                  const bool is_hover,
                                  const bool is_active)
{
  switch (element) {
    case MixarCardElement::ModeSliderLeft:
      draw_slider_left(but, rect);
      return true;
    case MixarCardElement::ModeSliderRight:
      draw_slider_right(but, rect);
      return true;
    case MixarCardElement::CinemaPill:
      draw_cinema_pill(but, rect);
      return true;
    case MixarCardElement::ViewportPill:
      draw_viewport_pill(but, rect);
      return true;
    case MixarCardElement::ProfilePill:
      draw_profile_pill(but, rect);
      return true;
    case MixarCardElement::CinemaRow:
      UI_mixar_cinema_row_draw(but, rect, is_hover, is_active);
      return true;
    default:
      return false;
  }
}

}  // namespace blender::ui
