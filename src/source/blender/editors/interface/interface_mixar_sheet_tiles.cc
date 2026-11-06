/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * The sheet's app-icon tile (the Export card's target grid): a rounded
 * square plate carrying the button's preview icon (a format's logo), the
 * label centred under it, and a focus ring around the plate on the current
 * choice. The slot Python hands over is the whole tile — plate on top,
 * #tile_label_h of label underneath — so the grid is laid out with ordinary
 * sized rows (`kit.tile`).
 */

#include <algorithm>
#include <cmath>

#include "BLI_math_color.h"
#include "BLI_rect.h"

#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_mixar_motion.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_sheet.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui::mixar_sheet {

void draw_tile(Button *but, const rcti *rect)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  const float fade = but_disabled(but) ? 0.45f : 1.0f;
  const float lift = std::max(motion.selected, hover_cue(motion.hover, motion.press));
  rctf slot;
  BLI_rctf_rcti_copy(&slot, rect);

  /* The plate: a square as wide as the slot allows above the label band,
   * centred horizontally, lifted a pixel under the pointer. */
  const float label_h = px(tile_label_h);
  const float side = std::max(
      0.0f, std::min(BLI_rctf_size_x(&slot) - 2.0f * px(tile_ring_out), BLI_rctf_size_y(&slot) - label_h - px(tile_ring_out)));
  const float cx = BLI_rctf_cent_x(&slot);
  const float top = slot.ymax - px(tile_ring_out) + px(1.0f) * hover_cue(motion.hover, motion.press) *
                                                        (1.0f - motion.selected);
  rctf plate = {cx - side * 0.5f, cx + side * 0.5f, top - side, top};
  const float rad = std::min(px(tile_radius), side * 0.5f);

  float fill[4], border[4];
  uchar fill_col[4];
  lerp_col(fill_col, tile_fill, tile_fill_hover, lift);
  rgba_uchar_to_float(fill, fill_col);
  rgba_uchar_to_float(border, tile_border);
  fill[3] *= fade;
  border[3] *= fade;
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv_ex(&plate, fill, fill, 0.0f, border, line_px(), rad);
  /* A soft sheen along the top edge reads as the icon's bevel. */
  rctf sheen = plate;
  sheen.ymin = plate.ymax - side * 0.5f;
  mixar_card_fill_round(&sheen, rad, text_bright, 0.035f * fade);

  if (motion.selected > 0.0f) {
    /* The ring sits #tile_ring_gap outside the plate, card-coloured in between. */
    rctf ring = plate;
    const float out = px(tile_ring_gap) + px(tile_ring_w) * 0.5f;
    BLI_rctf_pad(&ring, out, out);
    float ring_col[4], clear[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    rgba_uchar_to_float(ring_col, tile_ring);
    ring_col[3] *= motion.selected * fade;
    draw_roundbox_corner_set(CNR_ALL);
    draw_roundbox_4fv_ex(&ring, clear, clear, 0.0f, ring_col, px(tile_ring_w), rad + out);
  }

  /* The logo, from the full-size preview so it stays sharp at any UI scale;
   * a rest tile is dimmed until hovered. */
  if (but->icon != ICON_NONE) {
    const float size = side * tile_icon_ratio;
    const float alpha = fade * (tile_icon_rest_alpha + (1.0f - tile_icon_rest_alpha) * lift);
    GPU_blend(GPU_BLEND_ALPHA);
    icon_draw_preview(cx - size * 0.5f,
                      BLI_rctf_cent_y(&plate) - size * 0.5f,
                      but->icon,
                      1.0f,
                      alpha,
                      int(size));
  }

  uchar col[4];
  lerp_col(col, row_text_off, text_bright, lift);
  col[3] = uchar(std::lround(float(col[3]) * fade));
  const rctf label = {slot.xmin, slot.xmax, slot.ymin, plate.ymin - px(tile_ring_out)};
  text_in(font(tile_label_size, motion.selected > 0.5f ? weight_strong : weight_medium),
          label,
          but_label(but),
          col,
          true);
}

}  // namespace blender::ui::mixar_sheet
