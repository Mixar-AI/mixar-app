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
 * thumb inset 2px; Cinema pill with shared toolbar-height rounded geometry, #3F3F3F hairline
 * border, shared horizontal Cinema gradients, film-strip icon and inline italic V2
 * marker). Geometry stays on the layout.
 * Compact is the chrome host; these widgets keep the UI.svg sizes rather
 * than Compact's 32-unit control height.
 *
 * Viewport shading and account chips are panes (`MIXAR_GLASS_PILL`);
 * the slider track/thumb and the account avatar disc stay flat — grooves and
 * pictures must not show the bar through them.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLF_api.hh"
#include "BKE_context.hh"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "WM_api.hh"
#include "WM_types.hh"
#include "UI_view2d.hh"

#include "BLI_math_base.h"
#include "BLI_rect.h"
#include "BLI_string.h"

#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"
#include "UI_mixar_chrome.hh"
#include "UI_mixar_motion.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_profile_card.hh"
#include "UI_mixar_theme.hh"
#include "mixar/cinema_label.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

/* Resolve against the whole window after native layout. Paint, hit tests and
 * QA all receive these final button rectangles. Workspace tabs that would
 * reach the switch overflow into a dropdown placed, with the New Workspace
 * "+", right after the last visible tab (`interface_mixar_topbar_tabs.cc`). */
void mixar_topbar_center_mode_slider(const bContext *C, ARegion *region, Block *block)
{
  const ScrArea *area = C ? CTX_wm_area(C) : nullptr;
  if (!area || area->spacetype != SPACE_TOPBAR || !region ||
      RGN_ALIGN_ENUM_FROM_MASK(region->alignment) == RGN_ALIGN_RIGHT)
  {
    return;
  }
  Button *left = nullptr, *right = nullptr;
  for (Button &but : block->buttons()) {
    if (!but.optype) {
      continue;
    }
    if (STREQ(but.optype->idname, "MIXAR_OT_set_ui_mode_ai")) {
      left = &but;
    }
    else if (STREQ(but.optype->idname, "MIXAR_OT_set_ui_mode_pro")) {
      right = &but;
    }
  }
  if (!left || !right) {
    return;
  }
  rcti left_px, right_px;
  button_to_pixelrect(&left_px, region, block, left);
  button_to_pixelrect(&right_px, region, block, right);
  const float center = WM_window_native_pixel_size(CTX_wm_window(C))[0] * 0.5f -
                       region->winrct.xmin;
  const float delta = (center - (left_px.xmin + right_px.xmax) * 0.5f) /
                      view2d_scale_get_x(&region->v2d);
  BLI_rctf_translate(&left->rect, delta, 0);
  BLI_rctf_translate(&right->rect, delta, 0);
  /* Keep the native hit rectangles and painted track equally tall, with the
   * original header center retained at every UI scale. */
  const float center_y = BLI_rctf_cent_y(&left->rect);
  const float half_height = mixar_chrome::slider_height * UI_SCALE_FAC * 0.5f /
                            view2d_scale_get_y(&region->v2d);
  left->rect.ymin = right->rect.ymin = center_y - half_height;
  left->rect.ymax = right->rect.ymax = center_y + half_height;
  const float limit = left->rect.xmin - 8.0f * UI_SCALE_FAC;
  /* Tabs past the switch overflow into the dropdown; "+" stays beside them. */
  mixar_topbar_fit_workspace_tabs(C, block, limit);
  block_bounds_calc(block);
}

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
 * Mode slider, left half: the whole track plus the animated thumb, then
 * this half's label.
 *
 * The track spans both halves; it is derived from this button's rect by
 * mirroring it to the right, which is exact because the builder pins both
 * halves to the same `ui_units_x`.
 */
void draw_slider_left(Button *but, const rcti *rect)
{
  uchar slider_track_u[4], slider_thumb[4], slider_thumb_hover[4], slider_label[4];
  mixar_theme_copy_u(MixarThemeSlot::SliderTrack, mixar_chrome::slider_track, slider_track_u);
  mixar_theme_copy_u(MixarThemeSlot::SliderThumb, mixar_chrome::slider_thumb, slider_thumb);
  mixar_theme_copy_u(MixarThemeSlot::SliderThumbHover, mixar_chrome::slider_thumb_hover, slider_thumb_hover);
  mixar_theme_copy_u(MixarThemeSlot::SliderLabel, mixar_chrome::slider_label, slider_label);
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
  mixar_card_fill_round(&track, rad, slider_track_u);

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
  blend_color(slider_thumb,
              slider_thumb_hover,
              std::max(motion.hover, motion.press),
              fill);
  mixar_card_fill_round(&thumb, rad, fill);

  draw_label_centred(rect, but->drawstr.c_str(), slider_label, label_scale);
}

/** Mode slider, right half: label only — the left half drew the chrome. */
void draw_slider_right(Button *but, const rcti *rect)
{
  uchar slider_label[4];
  mixar_theme_copy_u(MixarThemeSlot::SliderLabel, mixar_chrome::slider_label, slider_label);
  draw_label_centred(rect, but->drawstr.c_str(), slider_label, label_scale);
}

/** Cinema shares horizontal background and text ramps in Zen and Engine,
 * with independently blended active endpoints. Native semantic selection remains separate from pressing. */
void draw_cinema_pill(Button *but, const rcti *rect)
{
  rctf pill;
  mixar_card_rect_to_rctf(rect, &pill);
  /* Operator press is separate from the semantic selected state. The central
   * sampler reads `lit`, so holding the mouse never activates Cinema Mode. */
  const MixarInteraction motion = mixar_button_motion(*but);
  const float emphasis = motion.hover + (1.0f - motion.hover) * motion.press;
  mixar_cinema_background(pill, motion.selected, emphasis);

  mixar_cinema_label(*rect, but->drawstr.c_str(), motion.selected,
                      (but->flag & (BUT_DISABLED | BUT_INACTIVE)) != 0, but->icon);
}

/** Zen viewport shading pill: "Solid" / "Rendered". */
void draw_viewport_pill(Button *but, const rcti *rect)
{
  uchar viewport_border[4], viewport_label[4], viewport_label_on[4];
  mixar_theme_copy_u(MixarThemeSlot::ViewportBorder, mixar_chrome::viewport_pill_border, viewport_border);
  mixar_theme_copy_u(MixarThemeSlot::ViewportLabel, mixar_chrome::viewport_pill_label, viewport_label);
  mixar_theme_copy_u(MixarThemeSlot::ViewportLabelOn, mixar_chrome::viewport_pill_label_on, viewport_label_on);
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
  mixar_card_outline_round(&pill, rad, viewport_border, alpha);

  uchar label[4];
  blend_color(viewport_label,
              viewport_label_on,
              motion.selected,
              label);
  label[3] = uchar(255.0f * alpha);
  draw_label_centred(rect, but->drawstr.c_str(), label, label_scale);
}

/** Topbar account chip: slab + label + avatar disc with the person glyph. */
void draw_profile_pill(Button *but, const rcti *rect)
{
  uchar profile_avatar[4], profile_glyph[4], profile_label[4];
  mixar_theme_copy_u(MixarThemeSlot::ProfileAvatar, mixar_chrome::profile_avatar, profile_avatar);
  mixar_theme_copy_u(MixarThemeSlot::ProfileGlyph, mixar_chrome::profile_glyph, profile_glyph);
  mixar_theme_copy_u(MixarThemeSlot::ProfileLabel, mixar_chrome::profile_label, profile_label);
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
  mixar_card_fill_round(&disc, rad, profile_avatar);

  /* Stock person silhouette — the "no picture set" placeholder. Drawn
   * through the icon system so it matches Blender's own weight. */
  const float glyph = height * 0.72f;
  uchar mono_u[4];
  memcpy(mono_u, profile_glyph, sizeof(mono_u));
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
      fs, &label_rect, but->drawstr.c_str(), profile_label, UI_STYLE_TEXT_LEFT);
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
