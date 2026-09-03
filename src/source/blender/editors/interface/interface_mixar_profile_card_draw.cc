/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar account card — text, divider and quota-bar drawing.
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
#include "UI_resources.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_palette.hh"
#include "interface_mixar_profile_card.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

namespace {

/* Quota bar bands, keyed on the fraction REMAINING. Must stay in step
 * with `modules/common/usage/constants.py` — the bar's colour and the
 * popover's wording come from two different languages. */
constexpr float CARD_USAGE_CRITICAL_FACTOR = 0.20f;
constexpr float CARD_USAGE_WARNING_FACTOR = 0.50f;

/* The quota bar's healthy ramp: deep teal into the brand cyan, matching
 * the dashboard's usage bar rather than the app-wide Generate gradient
 * (which runs through lime and would read as a different semantic).
 *
 * The trailing 255 is load-bearing: these are uchar[4] and a three-value
 * initializer zero-fills alpha, which draws the whole fill invisible. */
constexpr uchar CARD_USAGE_RAMP_START[4] = {6, 122, 128, 255};
constexpr uchar CARD_USAGE_RAMP_END[4] = {0, 192, 199, 255};

/** Heading point-size multiplier over the theme's widget font. */
constexpr float CARD_HEADING_SCALE = 1.45f;
constexpr int CARD_HEADING_WEIGHT = 700;

/**
 * Left-to-right two-stop ramp, clipped to a rounded rect.
 *
 * Same tri-strip approach as `mixar_draw_gradient_hbar`, sampled about
 * once per pixel so the corners don't facet.
 */
void fill_ramp(const rctf *rect, float rad, const uchar from[4], const uchar to[4])
{
  const float w = rect->xmax - rect->xmin;
  const float h = rect->ymax - rect->ymin;
  if (w <= 0.0f || h <= 0.0f) {
    return;
  }
  rad = std::min(rad, std::min(w, h) * 0.5f);

  const int cols = std::max(2, int(w));
  const float xc_l = rect->xmin + rad;
  const float xc_r = rect->xmax - rad;

  float c0[4], c1[4];
  mixar_card_to_float(from, c0);
  mixar_card_to_float(to, c1);

  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  const uint col = GPU_vertformat_attr_add(
      format, "color", blender::gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);

  GPU_blend(GPU_BLEND_ALPHA);
  immBegin(GPU_PRIM_TRI_STRIP, (cols + 1) * 2);
  for (int i = 0; i <= cols; i++) {
    const float t = float(i) / float(cols);
    const float x = rect->xmin + t * w;
    float top = rect->ymax;
    float bot = rect->ymin;
    if (x < xc_l || x > xc_r) {
      const float dx = (x < xc_l) ? (xc_l - x) : (x - xc_r);
      const float dy = sqrtf(std::max(0.0f, rad * rad - dx * dx));
      top = rect->ymax - rad + dy;
      bot = rect->ymin + rad - dy;
    }
    float c[4];
    interp_v4_v4v4(c, c0, c1, t);
    immAttr4fv(col, c);
    immVertex2f(pos, x, bot);
    immAttr4fv(col, c);
    immVertex2f(pos, x, top);
  }
  immEnd();
  immUnbindProgram();
  GPU_blend(GPU_BLEND_NONE);
}

/* -------------------------------------------------------------------- */
/* Elements                                                              */

void draw_heading(Button *but, rcti *rect)
{
  rcti text_rect = *rect;
  text_rect.xmin += mixar_card_text_pad();
  text_rect.xmax -= mixar_card_text_pad();

  /* An unusually long name shrinks rather than losing its tail. The
   * layout sized this rect from the default font; the heading is drawn
   * at #CARD_HEADING_SCALE, and the clip that resolves the difference is
   * silent (#BLF_clipping, no ellipsis). Point size tracks width closely
   * enough that one measurement lands it. */
  float scale = CARD_HEADING_SCALE;
  const uiFontStyle probe = mixar_card_font(scale, CARD_HEADING_WEIGHT);
  const float width = float(fontstyle_string_width(&probe, but->drawstr.c_str()));
  const float avail = float(BLI_rcti_size_x(&text_rect));
  if (width > avail && width > 0.0f) {
    scale = std::max(1.0f, scale * avail / width);
  }

  mixar_card_draw_text(mixar_card_font(scale, CARD_HEADING_WEIGHT),
            &text_rect,
            but->drawstr.c_str(),
            MX_FG_1,
            UI_STYLE_TEXT_LEFT);
}

void draw_muted(Button *but, rcti *rect, const FontStyleAlign align, const uchar col[4])
{
  rcti text_rect = *rect;
  text_rect.xmin += mixar_card_text_pad();
  text_rect.xmax -= mixar_card_text_pad();
  mixar_card_draw_text(mixar_card_font(0.9f, 0), &text_rect, but->drawstr.c_str(), col, align);
}

void draw_pill(Button *but, rcti *rect)
{
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
  const float rad = height * 0.35f;
  mixar_card_fill_round(&chip, rad, MX_GRAY_800);
  mixar_card_outline_round(&chip, rad, MX_BORDER_STRONG, 1.0f);
  GPU_blend(GPU_BLEND_NONE);

  rcti text_rect;
  BLI_rcti_init(&text_rect, int(chip.xmin), int(chip.xmax), int(chip.ymin), int(chip.ymax));
  mixar_card_draw_text(fs, &text_rect, label, MX_FG_2, UI_STYLE_TEXT_CENTER);
}

void draw_divider(rcti *rect)
{
  const float y = float(rect->ymin + rect->ymax) * 0.5f;
  const float thickness = std::max(1.0f, U.pixelsize);

  rctf line;
  line.xmin = float(rect->xmin);
  line.xmax = float(rect->xmax);
  line.ymin = y - thickness * 0.5f;
  line.ymax = line.ymin + thickness;

  GPU_blend(GPU_BLEND_ALPHA);
  mixar_card_fill_round(&line, 0.0f, MX_BORDER_STRONG);
  GPU_blend(GPU_BLEND_NONE);
}

/**
 * Slim quota bar with the percentage in its own slot to the right.
 *
 * The label deliberately does NOT sit inside the fill. Text on the fill
 * has to switch colour depending on how far the fill reaches, which
 * makes the most important number on the card least readable exactly
 * when it matters — at the extremes. A reserved slot is legible at every
 * value and lets the track keep a constant width.
 */
void draw_usage_bar(Button *but, rcti *rect)
{
  const float factor = std::clamp(float(but->hardmax), 0.0f, 1.0f);

  const float pad = float(mixar_card_text_pad());
  const float gap = 10.0f * UI_SCALE_FAC;

  /* Severity drives the fill and the label together, so a red bar can
   * never sit beside a neutral-looking number. */
  const bool is_critical = factor < CARD_USAGE_CRITICAL_FACTOR;
  const bool is_warning = !is_critical && factor < CARD_USAGE_WARNING_FACTOR;
  const bool is_healthy = !is_critical && !is_warning;
  const uchar *accent_col = is_critical ? MX_DANGER : (is_warning ? MX_WARNING : MX_FG_1);

  /* Measure the label first; the track takes whatever is left. */
  const uiFontStyle fs = mixar_card_font(1.0f, CARD_HEADING_WEIGHT);
  fontstyle_set(&fs);
  const float label_w = but->drawstr.empty() ?
                            0.0f :
                            BLF_width(fs.uifont_id, but->drawstr.c_str(), but->drawstr.size());

  rcti text_rect = *rect;
  text_rect.xmax = int(float(rect->xmax) - pad);
  text_rect.xmin = int(float(text_rect.xmax) - label_w);

  const float height = std::min(float(BLI_rcti_size_y(rect)), 16.0f * UI_SCALE_FAC);
  const float y_center = float(rect->ymin + rect->ymax) * 0.5f;

  rctf track;
  track.xmin = float(rect->xmin) + pad;
  track.xmax = float(text_rect.xmin) - gap;
  track.ymin = y_center - height * 0.5f;
  track.ymax = y_center + height * 0.5f;

  /* A card squeezed narrow can leave no room for a track; the percentage
   * alone still tells the whole story, so drop the bar rather than draw
   * a degenerate sliver. */
  if (track.xmax - track.xmin > height * 2.0f) {
    const float rad = height * 0.5f;

    GPU_blend(GPU_BLEND_ALPHA);
    mixar_card_fill_round(&track, rad, MX_BG_SUNKEN);
    mixar_card_outline_round(&track, rad, MX_BORDER_STRONG, 1.0f);

    if (factor > 0.0f) {
      rctf fill = track;
      /* Never round a non-zero remainder away to nothing: a sliver of
       * colour is the difference between "almost out" and "out". */
      const float span = track.xmax - track.xmin;
      fill.xmax = std::min(track.xmin + std::max(factor * span, height), track.xmax);

      if (is_healthy) {
        fill_ramp(&fill, rad, CARD_USAGE_RAMP_START, CARD_USAGE_RAMP_END);
        GPU_blend(GPU_BLEND_ALPHA);
      }
      else {
        /* Warning and critical stay flat — a two-tone alarm reads as a
         * gradient artifact rather than a signal. */
        mixar_card_fill_round(&fill, rad, accent_col);
      }
    }
    GPU_blend(GPU_BLEND_NONE);
  }

  mixar_card_draw_text(fs, &text_rect, but->drawstr.c_str(), accent_col, UI_STYLE_TEXT_RIGHT);
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
      draw_muted(but, rect, UI_STYLE_TEXT_LEFT, MX_FG_4);
      break;
    case MixarCardElement::SectionLabel:
      draw_muted(but, rect, UI_STYLE_TEXT_LEFT, MX_FG_3);
      break;
    case MixarCardElement::MetaRight:
      draw_muted(but, rect, UI_STYLE_TEXT_RIGHT, MX_FG_4);
      break;
    case MixarCardElement::Pill:
      draw_pill(but, rect);
      break;
    case MixarCardElement::UsageBar:
      draw_usage_bar(but, rect);
      break;
    case MixarCardElement::Divider:
      draw_divider(rect);
      break;
    case MixarCardElement::DangerText:
      draw_muted(but, rect, UI_STYLE_TEXT_LEFT, MX_DANGER);
      break;
    default:
      break;
  }
}
}  // namespace blender::ui
