/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * The sheet's format tile (first drawn for the Export sheet): a rounded
 * square holding the button's icon over its label, the way the designer's
 * Export artboard lays out ".blend", ".glb", ".mp4"… A built-in icon draws as
 * its vector glyph and a preview icon (an engine's logo) from its full-size
 * image, so both stay sharp at any UI scale. See `interface_mixar_sheet.hh`
 * for the artboard the numbers come from.
 */

#include <algorithm>
#include <cmath>
#include <string>

#include "BKE_icons.hh"

#include "BLI_math_color.h"
#include "BLI_rect.h"

#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"
#include "UI_mixar_motion.hh"
#include "UI_resources.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_sheet.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

namespace mixar_sheet {

static void draw_tile_icon(const int icon, const float cx, const float cy, const float size,
                           const float alpha)
{
  if (icon == ICON_NONE || size <= 1.0f) {
    return;
  }
  GPU_blend(GPU_BLEND_ALPHA);
  const Icon *data = BKE_icon_get(icon);
  if (data != nullptr && data->obj_type == ICON_DATA_PREVIEW) {
    /* A preview (a logo loaded through `bpy.utils.previews`): its full-size
     * image, not the 32 px icon `icon_draw_ex` would scale up. */
    icon_draw_preview(cx - size * 0.5f, cy - size * 0.5f, icon, 1.0f, alpha, int(size));
    return;
  }
  /* `icon_draw_ex` draws ICON_DEFAULT_HEIGHT px at scale 1. */
  icon_draw_ex(cx - size * 0.5f,
               cy - size * 0.5f,
               icon,
               1.0f,
               alpha,
               0.0f,
               nullptr,
               false,
               nullptr,
               false,
               size / float(ICON_DEFAULT_HEIGHT));
}

void draw_tile(Button *but, const rcti *rect)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  const float fade = but_disabled(but) ? 0.45f : 1.0f;
  const float cue = but_disabled(but) ? 0.0f : hover_cue(motion.hover, motion.press);
  rctf tile;
  BLI_rctf_rcti_copy(&tile, rect);
  const float side = std::min(BLI_rctf_size_x(&tile), BLI_rctf_size_y(&tile));
  const float rad = std::min(px(tile_radius), side * 0.5f);

  /* Plate and hairline: a quiet slate at rest, lighter under the pointer,
   * and the picked tile lifted with a bright rim (the artboard's ".Blend"). */
  uchar fill[4], border[4];
  lerp_col(fill, tile_fill, tile_fill_lit, std::max(motion.selected, 0.5f * cue));
  lerp_col(border, tile_border, tile_border_lit, motion.selected);
  float fill_f[4], border_f[4];
  rgba_uchar_to_float(fill_f, fill);
  rgba_uchar_to_float(border_f, border);
  fill_f[3] *= fade;
  border_f[3] *= fade;
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv_ex(&tile, fill_f, fill_f, 0.0f, border_f, std::max(1.0f, px(2.0f)), rad);

  const float icon_size = side * tile_icon;
  const float icon_alpha = fade * (tile_icon_rest_alpha + (1.0f - tile_icon_rest_alpha) *
                                                              std::max(motion.selected, cue));
  draw_tile_icon(but->icon,
                 BLI_rctf_cent_x(&tile),
                 BLI_rctf_cent_y(&tile) + BLI_rctf_size_y(&tile) * tile_icon_lift,
                 icon_size,
                 icon_alpha);

  uchar col[4];
  lerp_col(col, text_dim, text_bright, std::max(motion.selected, cue));
  col[3] = uchar(std::lround(float(col[3]) * fade));
  const int font_id = font(tile_label_size,
                           motion.selected > 0.5f ? weight_strong : weight_medium);
  const float pad = px(10.0f);
  const std::string label = fit(font_id, but_label(but), BLI_rctf_size_x(&tile) - 2.0f * pad);
  const float x = BLI_rctf_cent_x(&tile) - text_width(font_id, label.c_str()) * 0.5f;
  text_at(font_id, x, tile.ymin + px(tile_label_bottom), label.c_str(), col);
}

}  // namespace mixar_sheet

}  // namespace blender::ui
