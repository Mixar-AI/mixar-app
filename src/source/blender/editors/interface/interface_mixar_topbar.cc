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
 * ours. Geometry and colour come from the design export (`UI.svg`, 1x
 * logical px): slider track 225x28 rx7 #1D1D1D with a 106x23 rx7 #393939
 * thumb inset 2px; Cinema pill 150x27 fully rounded, #0E0E0E fill,
 * #3F3F3F hairline border, label graded #505050 -> white.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_math_base.h"
#include "BLI_rect.h"
#include "BLI_time.h"

#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_profile_card.hh"

namespace {

/* -------------------------------------------------------------------- */
/** \name Design tokens
 * \{ */

const uchar SLIDER_TRACK[4] = {0x1D, 0x1D, 0x1D, 255};
const uchar SLIDER_THUMB[4] = {0x39, 0x39, 0x39, 255};
const uchar SLIDER_THUMB_HOVER[4] = {0x46, 0x46, 0x46, 255};
const uchar SLIDER_LABEL[4] = {255, 255, 255, 255};

const uchar PILL_FILL[4] = {0x0E, 0x0E, 0x0E, 255};
const uchar PILL_BORDER[4] = {0x3F, 0x3F, 0x3F, 255};
/* Active: the whole pill goes green — Cinema Mode is a state you are IN, and
 * the fill IS the indicator (no separate switch widget). Greens are the
 * island's own chip ramp (#205836 -> #3A8457). */
const uchar PILL_FILL_ON_A[4] = {0x20, 0x58, 0x36, 255};
const uchar PILL_FILL_ON_B[4] = {0x3A, 0x84, 0x57, 255};
const uchar PILL_BORDER_ON[4] = {0x57, 0xB0, 0x7C, 255};
/* Label gradient, left to right (paint3_linear in the export). */
const uchar PILL_LABEL_A[4] = {0x50, 0x50, 0x50, 255};
const uchar PILL_LABEL_B[4] = {255, 255, 255, 255};

/** Side/vertical inset of the thumb inside the track, px @1x. */
constexpr float SLIDER_THUMB_INSET = 2.0f;

/** Exponential-ease time constant. ~95% of the travel in 0.16s. */
constexpr double SLIDER_TAU = 0.055;

/** \} */

/* -------------------------------------------------------------------- */
/** \name Thumb animation
 *
 * Position is a file-static because the slider is a singleton surface (one
 * topbar per window, and both windows would agree on the mode anyway) and
 * uiButs are rebuilt every redraw, so there is no per-button place to keep
 * it. The pump that keeps frames coming while it travels is Python-side
 * (`workflow/ui/operators/mode_slider_anim.py`): a tag issued from inside a
 * draw callback does not wake Blender's idle loop, so the painter cannot
 * drive its own animation. If the pump ever fails to fire, the easing below
 * still lands exactly on the target on the next redraw — the animation is
 * lost, never the state.
 * \{ */

/** Eased travel for one animated control. */
struct EasedPos {
  float pos = -1.0f; /* <0 = unset, snaps on first draw. */
  double time = 0.0;

  float advance(const float target)
  {
    const double now = BLI_time_now_seconds();
    if (pos < 0.0f) {
      pos = target;
      time = now;
      return pos;
    }
    const double dt = std::clamp(now - time, 0.0, 0.25);
    time = now;
    const float k = float(1.0 - std::exp(-dt / SLIDER_TAU));
    pos += (target - pos) * k;
    if (std::abs(target - pos) < 0.001f) {
      pos = target;
    }
    return pos;
  }
};

EasedPos g_thumb; /* Mode slider: 0 = Zen half, 1 = Engine half. */

/** \} */

/* -------------------------------------------------------------------- */
/** \name Painters
 * \{ */

/* Zen viewport shading pills (UI.svg, second row): 130x23 rx11.5, fill
 * #050505, 1px border #676767, label #737373. The inactive pill is the same
 * chip at 49% opacity — the design distinguishes them by presence, not by a
 * sliding thumb. */
const uchar VIEW_PILL_FILL[4] = {0x05, 0x05, 0x05, 255};
const uchar VIEW_PILL_BORDER[4] = {0x67, 0x67, 0x67, 255};
const uchar VIEW_PILL_LABEL[4] = {0x73, 0x73, 0x73, 255};
const uchar VIEW_PILL_LABEL_ON[4] = {0xDE, 0xDE, 0xDE, 255};
constexpr float VIEW_PILL_DIM = 0.49f;

/* Account chip (UI.svg): #1B1B1B slab with the label, capped at the right by
 * a full-height avatar disc. The design's disc is a photo; with no profile
 * picture set we draw the stock person glyph on a neutral disc — the
 * placeholder every social platform uses — rather than a generated initial. */
const uchar PROFILE_FILL[4] = {0x1B, 0x1B, 0x1B, 255};
const uchar PROFILE_LABEL[4] = {0xEC, 0xEC, 0xEC, 255};
const uchar PROFILE_AVATAR[4] = {0x3C, 0x3C, 0x3C, 255};
const uchar PROFILE_GLYPH[4] = {0xD2, 0xD2, 0xD2, 255};

/** Centre \a str in \a rect using the theme widget font at \a scale. */
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
 * #UI_fontstyle_draw takes a single colour for the whole run.
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
  UI_fontstyle_set(&fs);
  const int font = fs.uifont_id;

  const size_t len = strlen(str);
  const float total_w = BLF_width(font, str, len);
  float x = float(rect->xmin) + (float(BLI_rcti_size_x(rect)) - total_w) * 0.5f;

  /* Vertical centring on the ink box, matching #UI_fontstyle_draw. */
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
void draw_slider_left(uiBut *but, const rcti *rect, const bool is_hover)
{
  const float half_w = float(BLI_rcti_size_x(rect));
  rctf track;
  track.xmin = float(rect->xmin);
  track.xmax = float(rect->xmax) + half_w;
  track.ymin = float(rect->ymin);
  track.ymax = float(rect->ymax);

  const float height = BLI_rctf_size_y(&track);
  const float rad = height * 0.25f;
  const float inset = SLIDER_THUMB_INSET * UI_SCALE_FAC;

  GPU_blend(GPU_BLEND_ALPHA);
  mixar_card_fill_round(&track, rad, SLIDER_TRACK);

  /* Payload is "this (left) half is live", so a live left half parks the
   * thumb at 0 and a live right half sends it to 1. */
  const float target = (but->hardmax >= 0.5f) ? 0.0f : 1.0f;
  const float pos = g_thumb.advance(target);

  rctf thumb;
  thumb.xmin = track.xmin + inset + pos * half_w;
  thumb.xmax = thumb.xmin + half_w - inset * 2.0f;
  thumb.ymin = track.ymin + inset;
  thumb.ymax = track.ymax - inset;
  mixar_card_fill_round(&thumb, rad, is_hover ? SLIDER_THUMB_HOVER : SLIDER_THUMB);

  draw_label_centred(rect, but->drawstr.c_str(), SLIDER_LABEL, 0.95f);
}

/** Mode slider, right half: label only — the left half drew the chrome. */
void draw_slider_right(uiBut *but, const rcti *rect)
{
  draw_label_centred(rect, but->drawstr.c_str(), SLIDER_LABEL, 0.95f);
}

/**
 * "Cinema Mode": fully rounded pill — the design's dark chip at rest, the
 * whole pill filled green while directing.
 *
 * No separate switch widget: the fill is the state. A knob read as "here is
 * a control inside a button" when the button already IS the control.
 */
void draw_cinema_pill(uiBut *but, const rcti *rect, const bool is_hover, const bool is_active)
{
  rctf pill;
  mixar_card_rect_to_rctf(rect, &pill);
  /* The design's pill is shorter than the topbar's button height; inset so
   * it reads as a floating chip rather than a full-height slab. */
  const float inset = 1.0f * UI_SCALE_FAC;
  BLI_rctf_pad(&pill, -inset, -inset);

  const float rad = BLI_rctf_size_y(&pill) * 0.5f;
  /* Payload first: the pill is an operator button, so Blender never sets
   * UI_SELECT on it — the "am I the live state" answer only ever comes from
   * the tag. (UI_SELECT is still honoured for the press flash.) */
  const bool lit = but->hardmax >= 0.5f || is_active || (but->flag & UI_SELECT) != 0;

  GPU_blend(GPU_BLEND_ALPHA);
  if (lit) {
    /* Vertical ramp, lighter at the top — same read as the island's green
     * chips, so the two surfaces look like one product. */
    float a[4];
    float b[4];
    mixar_card_to_float(PILL_FILL_ON_B, a);
    mixar_card_to_float(PILL_FILL_ON_A, b);
    if (is_hover) {
      for (int i = 0; i < 3; i++) {
        a[i] = std::min(1.0f, a[i] * 1.12f);
        b[i] = std::min(1.0f, b[i] * 1.12f);
      }
    }
    UI_draw_roundbox_corner_set(UI_CNR_ALL);
    /* shade_dir 1.0 = vertical ramp (inner1 at the top). */
    UI_draw_roundbox_4fv_ex(&pill, a, b, 1.0f, nullptr, 0.0f, rad);
    mixar_card_outline_round(&pill, rad, PILL_BORDER_ON, is_hover ? 1.0f : 0.9f);
  }
  else {
    mixar_card_fill_round(&pill, rad, PILL_FILL, is_hover ? 1.0f : 0.94f);
    mixar_card_outline_round(&pill, rad, PILL_BORDER, is_hover ? 1.0f : 0.85f);
  }

  /* Resting label carries the design's grey-to-white ramp; lit resolves it
   * to solid white so the green fill reads as the whole statement. */
  draw_label_gradient(rect,
                      but->drawstr.c_str(),
                      lit ? PILL_LABEL_B : PILL_LABEL_A,
                      PILL_LABEL_B,
                      0.95f);
}

/** Zen viewport shading pill: "Solid" / "Rendered". */
void draw_viewport_pill(uiBut *but, const rcti *rect, const bool is_hover, const bool is_active)
{
  const bool lit = is_active || (but->flag & UI_SELECT) != 0 || but->hardmax >= 0.5f;
  const float alpha = lit ? 1.0f : (is_hover ? 0.75f : VIEW_PILL_DIM);

  rctf pill;
  mixar_card_rect_to_rctf(rect, &pill);
  const float inset = 1.0f * UI_SCALE_FAC;
  BLI_rctf_pad(&pill, -inset, -inset);
  const float rad = BLI_rctf_size_y(&pill) * 0.5f;

  GPU_blend(GPU_BLEND_ALPHA);
  mixar_card_fill_round(&pill, rad, VIEW_PILL_FILL, alpha);
  mixar_card_outline_round(&pill, rad, VIEW_PILL_BORDER, alpha);

  uchar label[4];
  memcpy(label, lit ? VIEW_PILL_LABEL_ON : VIEW_PILL_LABEL, sizeof(label));
  label[3] = uchar(255.0f * alpha);
  draw_label_centred(rect, but->drawstr.c_str(), label, 0.95f);
}

/** Topbar account chip: slab + label + avatar disc with the person glyph. */
void draw_profile_pill(uiBut *but, const rcti *rect, const bool is_hover, const bool /*is_active*/)
{
  rctf chip;
  mixar_card_rect_to_rctf(rect, &chip);
  const float inset = 1.0f * UI_SCALE_FAC;
  BLI_rctf_pad(&chip, -inset, -inset);

  const float height = BLI_rctf_size_y(&chip);
  const float rad = height * 0.5f;

  GPU_blend(GPU_BLEND_ALPHA);
  mixar_card_fill_round(&chip, rad, PROFILE_FILL, is_hover ? 1.0f : 0.92f);

  /* Avatar disc caps the right end at full height, exactly as the design
   * has it (chip 27 tall, disc r=13.5). */
  rctf disc;
  disc.xmax = chip.xmax;
  disc.xmin = disc.xmax - height;
  disc.ymin = chip.ymin;
  disc.ymax = chip.ymax;
  mixar_card_fill_round(&disc, rad, PROFILE_AVATAR);

  /* Stock person silhouette — the "no picture set" placeholder. Drawn
   * through the icon system so it matches Blender's own weight. */
  const float glyph = height * 0.72f;
  float mono[4];
  mixar_card_to_float(PROFILE_GLYPH, mono);
  uchar mono_u[4];
  memcpy(mono_u, PROFILE_GLYPH, sizeof(mono_u));
  UI_icon_draw_ex(BLI_rctf_cent_x(&disc) - glyph * 0.5f,
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
  const uiFontStyle fs = mixar_card_font(0.95f, 0);
  mixar_card_draw_text(fs, &label_rect, but->drawstr.c_str(), PROFILE_LABEL, UI_STYLE_TEXT_LEFT);
}

/** \} */

}  // namespace

/* -------------------------------------------------------------------- */
/* Public API                                                            */

bool UI_mixar_topbar_draw_element(uiBut *but,
                                  rcti *rect,
                                  const MixarCardElement element,
                                  const bool is_hover,
                                  const bool is_active)
{
  switch (element) {
    case MixarCardElement::ModeSliderLeft:
      draw_slider_left(but, rect, is_hover);
      return true;
    case MixarCardElement::ModeSliderRight:
      draw_slider_right(but, rect);
      return true;
    case MixarCardElement::CinemaPill:
      draw_cinema_pill(but, rect, is_hover, is_active);
      return true;
    case MixarCardElement::ViewportPill:
      draw_viewport_pill(but, rect, is_hover, is_active);
      return true;
    case MixarCardElement::ProfilePill:
      draw_profile_pill(but, rect, is_hover, is_active);
      return true;
    default:
      return false;
  }
}
