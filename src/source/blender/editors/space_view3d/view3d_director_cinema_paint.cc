/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Drawing primitives for the Cinema Mode surface.
 *
 * Every painter here takes REGION pixels; callers convert from the design's
 * units through #cinema_unit(). Interaction is always a separate, invisible
 * ui::Button laid over the painted pixels (see #cinema_op_button) so Blender keeps
 * owning hit-testing, tooltips and operator dispatch.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_rect.h"

#include "BKE_image.hh"

#include "DNA_image_types.h"
#include "DNA_screen_types.h"

#include "IMB_imbuf_types.hh"

#include "BIF_glutil.hh"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director_cinema.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Scale
 * \{ */

float cinema_unit()
{
  /* The design is a 1x window mock, so a design px IS a UI px before DPI. */
  return UI_SCALE_FAC;
}

float cinema_margin(const ARegion *region)
{
  const float avail = float(region->winx) / cinema_unit();
  const float slack = (avail - CINEMA_PANEL_W * 2.0f - CINEMA_GATE_MIN_W) * 0.5f;
  return std::clamp(slack, CINEMA_MARGIN_MIN, CINEMA_MARGIN);
}

rctf cinema_design_rect(
    const ARegion *region, const float x, const float y, const float w, const float h)
{
  const float u = cinema_unit();
  rctf rect;
  rect.xmin = x * u;
  rect.xmax = (x + w) * u;
  rect.ymax = float(region->winy) - (y - CINEMA_VIEWPORT_TOP) * u;
  rect.ymin = rect.ymax - h * u;
  return rect;
}

bool cinema_surface_fits(const ARegion *region)
{
  const float u = cinema_unit();
  /* Both columns, the floor margins and a usable gate between them, plus
   * enough height for every card. The height is DERIVED from the lowest
   * content in either column (the Speed card's foot and the Export button's)
   * rather than guessed: #cinema_design_rect anchors on
   * #CINEMA_VIEWPORT_TOP, so a shorter region pushes `rect.ymin` negative and
   * lays the Speed slider and the Export button out below the region — drawn
   * clipped, and not hit-testable, with no compact fallback to fall back on. */
  const float min_w = CINEMA_PANEL_W * 2.0f + CINEMA_MARGIN_MIN * 2.0f + CINEMA_GATE_MIN_W;
  const float content_bottom = std::max(CINEMA_SPEED_CARD_Y + CINEMA_SPEED_CARD_H,
                                        CINEMA_EXPORT_Y + CINEMA_EXPORT_H);
  const float min_h = content_bottom - CINEMA_VIEWPORT_TOP;
  return float(region->winx) / u >= min_w && float(region->winy) / u >= min_h;
}

float cinema_list_row_h()
{
  return std::min(CINEMA_ROW_H, CINEMA_LIST_PITCH);
}

int cinema_list_window_start(const int count, const int active)
{
  /* The card only has room for #CINEMA_LIST_MAX_ROWS. Window the list around
   * the live entry rather than always showing the head: with the active shot
   * off the end no row highlighted at all, so "My Cameras" claimed none was
   * being directed. */
  if (count <= CINEMA_LIST_MAX_ROWS) {
    return 0;
  }
  const int centred = std::clamp(active, 0, count - 1) - CINEMA_LIST_MAX_ROWS / 2;
  return std::clamp(centred, 0, count - CINEMA_LIST_MAX_ROWS);
}

void cinema_draw_stage(const ARegion *region)
{
  const float u = cinema_unit();
  const float margin = cinema_margin(region);
  const float inset = 18.0f * u;
  rctf stage;
  stage.xmin = (margin + CINEMA_PANEL_W) * u + inset;
  stage.xmax = float(region->winx) - (margin + CINEMA_PANEL_W) * u - inset;
  stage.ymax = float(region->winy) - 125.0f * u;
  stage.ymin = 70.0f * u;
  if (BLI_rctf_size_x(&stage) <= 0.0f || BLI_rctf_size_y(&stage) <= 0.0f) {
    return;
  }
  const float fill[4] = CINEMA_COL_GATE_FILL;
  const float line[4] = CINEMA_COL_GATE_LINE;
  cinema_fill(stage, 18.5f * u, fill);
  cinema_outline(stage, 18.5f * u, line, u);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Shapes
 * \{ */

void cinema_panel(const rctf &rect,
                  const float radius,
                  const float top[4],
                  const float bottom[4])
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  /* shade_dir 1.0 = vertical ramp with `inner1` at the top. The design's
   * ramps are slightly diagonal; at panel scale the difference is under a
   * level of quantisation and a vertical ramp needs no custom geometry. */
  ui::draw_roundbox_4fv_ex(&rect, top, bottom, 1.0f, nullptr, 0.0f, radius);
}

void cinema_fill(const rctf &rect, const float radius, const float color[4])
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&rect, true, radius, color);
}

void cinema_outline(const rctf &rect,
                    const float radius,
                    const float color[4],
                    const float width)
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv_ex(&rect, nullptr, nullptr, 1.0f, color, width, radius);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Text
 * \{ */

namespace {

/** Baseline that centres \a text's ink box on \a center_y. */
float baseline_for(const int font, const char *text, const float center_y)
{
  rcti box;
  BLF_boundbox(font, text, strlen(text), &box);
  return center_y - float(box.ymin + box.ymax) * 0.5f;
}

}  // namespace

float cinema_text_width(const char *text, const float size)
{
  if (text == nullptr || text[0] == '\0') {
    return 0.0f;
  }
  const int font = BLF_default();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}

void cinema_text_left(
    const char *text, const float x, const float center_y, const float size, const float col[4])
{
  if (text == nullptr || text[0] == '\0') {
    return;
  }
  const int font = BLF_default();
  BLF_size(font, size);
  /* The surface clips with its own rects; BLF's clipping is left over from
   * whichever widget drew last and would crop these labels. */
  BLF_disable(font, BLF_CLIPPING);
  BLF_color4fv(font, col);
  BLF_position(font, x, baseline_for(font, text, center_y), 0.0f);
  BLF_draw(font, text, strlen(text));
}

void cinema_text_center(
    const char *text, const float cx, const float center_y, const float size, const float col[4])
{
  cinema_text_left(text, cx - cinema_text_width(text, size) * 0.5f, center_y, size, col);
}

void cinema_text_right(
    const char *text, const float right, const float cy, const float size, const float col[4])
{
  cinema_text_left(text, right - cinema_text_width(text, size), cy, size, col);
}

void cinema_chevron(const float cx, const float cy, const float size, const float col[4])
{
  /* Solid triangle, the design's ▼. Drawn from the roundbox helper's sibling
   * immediate mode so it shares the surface's blend state. */
  const float half = size * 0.5f;
  uint pos = GPU_vertformat_attr_add(
      immVertexFormat(), "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(col);
  immBegin(GPU_PRIM_TRIS, 3);
  immVertex2f(pos, cx - half, cy + half * 0.6f);
  immVertex2f(pos, cx + half, cy + half * 0.6f);
  immVertex2f(pos, cx, cy - half * 0.7f);
  immEnd();
  immUnbindProgram();
}

void cinema_triangle(
    const float x, const float cy, const float dx, const float half_h, const float col[4])
{
  uint pos = GPU_vertformat_attr_add(
      immVertexFormat(), "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(col);
  immBegin(GPU_PRIM_TRIS, 3);
  immVertex2f(pos, x, cy - half_h);
  immVertex2f(pos, x, cy + half_h);
  immVertex2f(pos, x + dx, cy);
  immEnd();
  immUnbindProgram();
}

void cinema_keycap(const float x, const float y, const char *letter)
{
  const float u = cinema_unit();
  const rctf cap = {x, x + CINEMA_KEYCAP_W * u, y, y + CINEMA_KEYCAP_H * u};
  const float fill[4] = CINEMA_COL_KEYCAP;
  const float glyph[4] = {1.0f, 1.0f, 1.0f, 1.0f};
  cinema_fill(cap, CINEMA_KEYCAP_RADIUS * u, fill);
  cinema_text_center(letter,
                     BLI_rctf_cent_x(&cap),
                     BLI_rctf_cent_y(&cap),
                     11.0f * u,
                     glyph);
}

void cinema_tick_meter(const rctf &rect, const int count, const int filled)
{
  if (count <= 0) {
    return;
  }
  const float u = cinema_unit();
  const float tick_w = 3.0f * u;
  const float pitch = BLI_rctf_size_x(&rect) / float(count);
  const float off[4] = CINEMA_COL_SPEED_OFF;
  const float on[4] = CINEMA_COL_SPEED_ON;
  for (int index = 0; index < count; index++) {
    rctf tick;
    tick.xmin = rect.xmin + pitch * float(index);
    tick.xmax = tick.xmin + tick_w;
    tick.ymin = rect.ymin;
    tick.ymax = rect.ymax;
    if (index < filled) {
      /* The design ramps the lit ticks from near-black green up to the
       * accent, so the bar reads as a level rather than a row of dots. */
      const float t = float(index + 1) / float(std::max(filled, 1));
      const float col[4] = {on[0] * t, on[1] * t, on[2] * t, 1.0f};
      cinema_fill(tick, tick_w * 0.5f, col);
    }
    else {
      cinema_fill(tick, tick_w * 0.5f, off);
    }
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Image preview
 * \{ */

void cinema_image_preview(Image *image, const rctf &rect, const float radius)
{
  if (image == nullptr) {
    return;
  }
  void *lock = nullptr;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (ibuf == nullptr || ibuf->x <= 0 || ibuf->y <= 0) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return;
  }

  const float box_w = BLI_rctf_size_x(&rect);
  const float box_h = BLI_rctf_size_y(&rect);
  const float aspect = float(ibuf->x) / float(ibuf->y);
  float draw_w = box_w;
  float draw_h = box_w / aspect;
  if (draw_h > box_h) {
    draw_h = box_h;
    draw_w = box_h * aspect;
  }
  const float draw_x = rect.xmin + (box_w - draw_w) * 0.5f;
  const float draw_y = rect.ymin + (box_h - draw_h) * 0.5f;

  PixelBitmapDrawer bitmap_drawer(GPU_SHADER_3D_IMAGE);
  GPU_blend(GPU_BLEND_ALPHA_PREMULT);
  if (ibuf->float_buffer.data) {
    bitmap_drawer.draw(draw_x,
                                   draw_y,
                                   ibuf->x,
                                   ibuf->y,
                                   blender::gpu::TextureFormat::SFLOAT_16_16_16_16,
                                   true,
                                   ibuf->float_buffer.data,
                                   draw_w / float(ibuf->x),
                                   draw_h / float(ibuf->y),
                                   nullptr);
  }
  else if (ibuf->byte_buffer.data) {
    bitmap_drawer.draw(draw_x,
                                   draw_y,
                                   ibuf->x,
                                   ibuf->y,
                                   blender::gpu::TextureFormat::UNORM_8_8_8_8,
                                   false,
                                   ibuf->byte_buffer.data,
                                   draw_w / float(ibuf->x),
                                   draw_h / float(ibuf->y),
                                   nullptr);
  }
  GPU_blend(GPU_BLEND_ALPHA);
  BKE_image_release_ibuf(image, ibuf, lock);
  UNUSED_VARS(radius);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name QA targets
 * \{ */

namespace {
std::vector<CinemaQARecord> g_qa_records;
}

void cinema_qa_begin(const ARegion *region)
{
  g_qa_records.erase(std::remove_if(g_qa_records.begin(),
                                    g_qa_records.end(),
                                    [region](const CinemaQARecord &record) {
                                      return record.region == region;
                                    }),
                     g_qa_records.end());
}

void cinema_qa_record(const ARegion *region,
                      const rctf &rect,
                      const char *surface,
                      const char *value,
                      const int index)
{
  CinemaQARecord record;
  record.region = region;
  record.rect = rect;
  record.surface = surface;
  record.value = value ? value : "";
  record.index = index;
  g_qa_records.push_back(std::move(record));
}

const std::vector<CinemaQARecord> &cinema_qa_records()
{
  return g_qa_records;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Hit areas
 * \{ */

ui::Button *cinema_op_button(ui::Block *block,
                        const char *operator_id,
                        const rctf &rect,
                        const char *tooltip)
{
  /* Emboss::None and no label: the panel already painted this control, so the
   * button contributes hit-testing and dispatch only. */
  ui::block_emboss_set(block, blender::ui::EmbossType::None);
  ui::Button *but = uiDefIconButO(block,
                             ui::ButtonType::But,
                             operator_id,
                             blender::wm::OpCallContext::InvokeRegionWin,
                             ICON_NONE,
                             int(rect.xmin),
                             int(rect.ymin),
                             int(BLI_rctf_size_x(&rect)),
                             int(BLI_rctf_size_y(&rect)),
                             tooltip);
  ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
  return but;
}

ui::Button *cinema_popup_button(ui::Block *block,
                           ui::BlockCreateFunc block_func,
                           const rctf &rect,
                           const char *tooltip)
{
  ui::block_emboss_set(block, blender::ui::EmbossType::None);
  ui::Button *but = uiDefIconBlockBut(block,
                                      block_func,
                                      nullptr,
                                      ICON_NONE,
                                      int(rect.xmin),
                                      int(rect.ymin),
                                      short(BLI_rctf_size_x(&rect)),
                                      short(BLI_rctf_size_y(&rect)),
                                      tooltip);
  ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
  return but;
}

/** \} */

}  // namespace blender
