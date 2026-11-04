/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * The sheet's block painters (first drawn for the Connect MCP dialog):
 * the code snippet on the key field's backdrop, the track-and-knob switch,
 * the status line's dot, and the glyphs that lead the sidebar's foot row
 * (Local model's monitor, Other app's terminal). See
 * `interface_mixar_sheet.hh` for the artboard the numbers come from.
 */

#include <algorithm>
#include <cmath>
#include <cstring>
#include <string>

#include "BLI_math_color.h"
#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_mixar_motion.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_sheet.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

namespace mixar_sheet {

/* -- Snippet ---------------------------------------------------------------- */

/** "line\nline\n…" in the monospace face, top-down from the padding, on the
 * key field's backdrop. The backdrop runs #MixarButtonStyle::progress design
 * px past the button's right edge, under the pill docked in its corner; the
 * text stops at the button's own edge (less the padding). Python wraps the
 * lines to that width with this face's measured advance and sizes the block
 * to them, so the fit below only guards a rounding pixel. */
void draw_snippet(Button *but, const rcti *rect)
{
  rctf box;
  BLI_rctf_rcti_copy(&box, rect);
  const float text_right = box.xmax - px(snippet_pad_x);
  box.xmax += px(but->mixar_style.progress);
  const float fade = but_disabled(but) ? 0.5f : 1.0f;
  const float rad = std::min(px(input_radius), BLI_rctf_size_y(&box) * 0.5f);
  float fill[4], border[4];
  rgba_uchar_to_float(fill, input_fill);
  rgba_uchar_to_float(border, input_border);
  fill[3] *= fade;
  border[3] *= fade;
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv_ex(&box, fill, fill, 0.0f, border, line_px(), rad);

  uchar col[4];
  memcpy(col, text_body, 4);
  col[3] = uchar(std::lround(float(col[3]) * fade));
  const int font_id = font(snippet_size, weight_regular, true);
  const float x = box.xmin + px(snippet_pad_x);
  const float line_h = px(snippet_line_h);
  const float cap = cap_height(font_id);
  float top = box.ymax - px(snippet_pad_y);
  const std::string text = but_label(but);
  size_t start = 0;
  while (start <= text.size() && top - line_h >= box.ymin - 1.0f) {
    size_t end = text.find('\n', start);
    if (end == std::string::npos) {
      end = text.size();
    }
    const std::string line = text.substr(start, end - start);
    if (!line.empty()) {
      const float baseline = top - line_h * 0.5f - cap * 0.5f;
      text_at(font_id, x, baseline, fit(font_id, line.c_str(), text_right - x).c_str(), col);
    }
    top -= line_h;
    start = end + 1;
  }
}

/* -- Switch ----------------------------------------------------------------- */

/** Track and knob at the slot's left, its label after #switch_gap. `lit`
 * (on) glides the knob right and the track to the primary green. */
void draw_switch(Button *but, const rcti *rect)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  const float fade = but_disabled(but) ? 0.45f : 1.0f;
  const float cue = but_disabled(but) ? 0.0f : hover_cue(motion.hover, motion.press);
  rctf slot;
  BLI_rctf_rcti_copy(&slot, rect);
  const float w = px(switch_w);
  const float h = std::min(px(switch_h), BLI_rctf_size_y(&slot));
  const float cy = BLI_rctf_cent_y(&slot);
  const rctf track = {slot.xmin, slot.xmin + w, cy - h * 0.5f, cy + h * 0.5f};

  uchar off[4], on[4], fill[4];
  lerp_col(off, switch_track_off, switch_track_off_hover, cue);
  lerp_col(on, primary_fill, primary_fill_hover, cue);
  lerp_col(fill, off, on, motion.selected);
  mixar_card_fill_round(&track, h * 0.5f, fill, fade);

  const float knob = std::min(px(switch_knob), h);
  const float margin = (h - knob) * 0.5f;
  const float knob_x = track.xmin + margin + (w - h) * std::clamp(motion.selected, 0.0f, 1.0f);
  const rctf disc = {knob_x, knob_x + knob, cy - knob * 0.5f, cy + knob * 0.5f};
  mixar_card_fill_round(&disc, knob * 0.5f, text_bright, fade);

  uchar col[4];
  memcpy(col, text_body, 4);
  col[3] = uchar(std::lround(float(col[3]) * fade));
  const rctf text = {track.xmax + px(switch_gap), slot.xmax, slot.ymin, slot.ymax};
  text_in(font(body_size, weight_regular), text, but_label(but), col, false);
}

/* -- Status dot ------------------------------------------------------------- */

/** The disc at the slot's left: green while lit, the danger colour with a
 * payload of 1.0, dim otherwise. */
void draw_status_dot(Button *but, const rcti *rect)
{
  const uchar *col = but->mixar_style.lit                 ? row_dot :
                     but->mixar_style.progress >= 0.5f ? text_danger :
                                                         text_dim;
  rctf slot;
  BLI_rctf_rcti_copy(&slot, rect);
  const float r = px(status_dot) * 0.5f;
  const float cx = slot.xmin + r;
  const float cy = BLI_rctf_cent_y(&slot);
  const rctf dot = {cx - r, cx + r, cy - r, cy + r};
  mixar_card_fill_round(&dot, r, col, but_disabled(but) ? 0.5f : 1.0f);
}

/* -- Foot glyphs ------------------------------------------------------------ */

/** The artboard's monitor: a rounded screen on a stand over a base, stroked. */
static void draw_monitor(const float x, const float cy, const uchar col[4])
{
  const float w = px(footer_icon);
  const float screen_h = px(13.0f);
  const float stroke_w = px(footer_icon_stroke);
  const rctf screen = {x, x + w, cy + px(9.0f) - screen_h, cy + px(9.0f)};
  float c[4];
  rgba_uchar_to_float(c, col);
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv(&screen, false, px(4.0f), c);
  const float mid = x + w * 0.5f;
  stroke(mid, screen.ymin, mid, cy - px(9.0f), stroke_w, col, 1.0f);
  stroke(x + px(4.5f), cy - px(9.0f), x + w - px(4.5f), cy - px(9.0f), stroke_w, col, 1.0f);
}

/** A terminal: a rounded screen holding a `>` prompt and a `_` cursor. */
static void draw_terminal(const float x, const float cy, const uchar col[4])
{
  const float w = px(footer_icon);
  const float h = px(footer_terminal_h);
  const float stroke_w = px(footer_icon_stroke);
  const rctf screen = {x, x + w, cy - h * 0.5f, cy + h * 0.5f};
  float c[4];
  rgba_uchar_to_float(c, col);
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv(&screen, false, px(3.5f), c);
  /* The prompt's chevron, left of centre, and the cursor after it. */
  const float chevron_x = x + w * 0.28f;
  const float half = h * 0.17f;
  const float tip_y = cy + h * 0.02f;
  stroke(chevron_x, tip_y + half, chevron_x + half * 1.15f, tip_y, stroke_w, col, 1.0f);
  stroke(chevron_x + half * 1.15f, tip_y, chevron_x, tip_y - half, stroke_w, col, 1.0f);
  const float cursor_y = cy - h * 0.25f;
  stroke(x + w * 0.52f, cursor_y, x + w * 0.76f, cursor_y, stroke_w, col, 1.0f);
}

void draw_footer_glyph(Button *but, const float x, const float cy, const uchar col[4])
{
  if (but->mixar_style.progress >= footer_terminal) {
    draw_terminal(x, cy, col);
  }
  else {
    draw_monitor(x, cy, col);
  }
}

}  // namespace mixar_sheet

}  // namespace blender::ui
