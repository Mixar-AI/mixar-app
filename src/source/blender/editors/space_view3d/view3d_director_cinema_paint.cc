/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Drawing primitives for the Cinema Mode surface.
 *
 * Every painter here takes REGION pixels; callers convert from the design's
 * units through #cinema_unit() (`view3d_director_cinema_layout.cc` owns the
 * scale, the fit gate and the stage geometry). Interaction is always a
 * separate, invisible ui::Button laid over the painted pixels (see
 * #cinema_op_button) so Blender keeps owning hit-testing, tooltips and
 * operator dispatch.
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

#include "ED_mixar_glass.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "UI_resources.hh"

#include "view3d_director_cinema.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

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

void cinema_glass_panel(const rctf &rect, const float radius)
{
  rcti pane;
  BLI_rcti_rctf_copy(&pane, &rect);
  ui::MixarGlassStyle style;
  style.role = ui::MIXAR_GLASS_CARD;
  style.radius = radius;
  style.draw_shadow = false;
  style.draw_specular = false;
  ui::mixar_glass_draw(pane, style);
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

/** \} */

/* -------------------------------------------------------------------- */
/** \name Keycaps and meters
 * \{ */

float cinema_keycap_width(const char *label)
{
  const float u = cinema_unit();
  return std::max(CINEMA_KEYCAP_W * u,
                  cinema_text_width(label, CINEMA_KEYCAP_FONT * u) +
                      CINEMA_KEYCAP_PAD * 2.0f * u);
}

float cinema_keycap(const float x, const float y, const char *letter)
{
  const float u = cinema_unit();
  /* A single glyph keeps the square cap; a word ("Shift", "Mouse") widens
   * it rather than spilling out of one. */
  const float width = cinema_keycap_width(letter);
  const rctf cap = {x, x + width, y, y + CINEMA_KEYCAP_H * u};
  MIXAR_THEME_LOAD(fill, CinemaKeycap);
  const float glyph[4] = {1.0f, 1.0f, 1.0f, 1.0f};
  cinema_fill(cap, CINEMA_KEYCAP_RADIUS * u, fill);
  cinema_text_center(letter,
                     BLI_rctf_cent_x(&cap),
                     BLI_rctf_cent_y(&cap),
                     CINEMA_KEYCAP_FONT * u,
                     glyph);
  return width;
}

void cinema_tick_meter(const rctf &rect, const int count, const int filled)
{
  if (count <= 0) {
    return;
  }
  const float u = cinema_unit();
  const float tick_w = 3.0f * u;
  const float pitch = BLI_rctf_size_x(&rect) / float(count);
  MIXAR_THEME_LOAD(off, Queue);
  MIXAR_THEME_LOAD(on, CinemaRowSliderOn);
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

namespace {

/**
 * The painted rect as whole pixels that CONTAIN it.
 *
 * Paint is float and a uiBut's box is int, so truncating both corners lost
 * up to a pixel on each edge of every control on the surface — which is a
 * whole control when the control is a 3 px scroll track. Floor the origin,
 * ceil the far edge.
 */
rcti hit_box(const rctf &rect)
{
  rcti box;
  box.xmin = int(std::floor(rect.xmin));
  box.ymin = int(std::floor(rect.ymin));
  box.xmax = int(std::ceil(rect.xmax));
  box.ymax = int(std::ceil(rect.ymax));
  return box;
}

}  // namespace

ui::Button *cinema_op_button(ui::Block *block,
                        const char *operator_id,
                        const rctf &rect,
                        const char *tooltip)
{
  const rcti box = hit_box(rect);
  /* The panel already painted the control. The native button owns input and
   * a transparent, bounded feedback overlay over precisely those pixels. */
  ui::block_emboss_set(block, blender::ui::EmbossType::None);
  ui::Button *but = uiDefIconButO(block,
                             ui::ButtonType::But,
                             operator_id,
                             blender::wm::OpCallContext::InvokeRegionWin,
                             ICON_NONE,
                             box.xmin,
                             box.ymin,
                             BLI_rcti_size_x(&box),
                             BLI_rcti_size_y(&box),
                             tooltip);
  ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
  ui::mixar_style_button(but, ui::MixarComponent::Surface, ui::MixarVariant::Ghost, cinema_unit());
  return but;
}

ui::Button *cinema_blocker(ui::Block *block, const rctf &rect, const char *tooltip)
{
  const rcti box = hit_box(rect);
  /* No operator: a plain button that answers a click by doing nothing. What
   * it is for is STOPPING the click — an opaque card the surface paints has
   * to swallow presses on its own background, or they reach whatever keymap
   * item is polling the pixels behind it. */
  ui::block_emboss_set(block, blender::ui::EmbossType::None);
  ui::Button *but = ui::uiDefBut(block,
                                 ui::ButtonType::But,
                                 "",
                                 box.xmin,
                                 box.ymin,
                                 short(BLI_rcti_size_x(&box)),
                                 short(BLI_rcti_size_y(&box)),
                                 nullptr,
                                 0.0f,
                                 0.0f,
                                 tooltip);
  ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
  return but;
}

ui::Button *cinema_icon_button(ui::Block *block,
                               const char *operator_id,
                               const int icon,
                               const rctf &rect,
                               const char *tooltip)
{
  const rcti box = hit_box(rect);
  /* Emboss::None draws the icon and nothing else; the chip behind it is the
   * caller's paint. */
  ui::block_emboss_set(block, blender::ui::EmbossType::None);
  ui::Button *but = uiDefIconButO(block,
                                  ui::ButtonType::But,
                                  operator_id,
                                  blender::wm::OpCallContext::InvokeRegionWin,
                                  icon,
                                  box.xmin,
                                  box.ymin,
                                  BLI_rcti_size_x(&box),
                                  BLI_rcti_size_y(&box),
                                  tooltip);
  ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
  ui::mixar_style_button(but, ui::MixarComponent::Surface, ui::MixarVariant::Ghost, cinema_unit());
  return but;
}

namespace {
/* Bar widths handed to popups, one per slot: the popup create function runs
 * later, so the pointer it receives must outlive the draw. */
float g_popup_bar_width[int(CinemaPopupSlot::Count)] = {};
}  // namespace

ui::Button *cinema_popup_button(ui::Block *block,
                           ui::BlockCreateFunc block_func,
                           const rctf &rect,
                           const char *tooltip,
                           const CinemaPopupSlot slot)
{
  float *width = &g_popup_bar_width[int(slot)];
  *width = BLI_rctf_size_x(&rect);
  const rcti box = hit_box(rect);
  ui::block_emboss_set(block, blender::ui::EmbossType::None);
  ui::Button *but = uiDefIconBlockBut(block,
                                      block_func,
                                      width,
                                      ICON_NONE,
                                      box.xmin,
                                      box.ymin,
                                      short(BLI_rcti_size_x(&box)),
                                      short(BLI_rcti_size_y(&box)),
                                      tooltip);
  ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
  ui::mixar_style_button(but, ui::MixarComponent::Surface, ui::MixarVariant::Ghost, cinema_unit());
  return but;
}

ui::Button *cinema_prop_toggle(ui::Block *block,
                               PointerRNA *ptr,
                               const char *prop_name,
                               const int icon,
                               const rctf &rect,
                               const char *tooltip)
{
  const rcti box = hit_box(rect);
  ui::block_emboss_set(block, blender::ui::EmbossType::None);
  ui::Button *but = uiDefIconButR(block,
                                  ui::ButtonType::Toggle,
                                  icon,
                                  box.xmin,
                                  box.ymin,
                                  short(BLI_rcti_size_x(&box)),
                                  short(BLI_rcti_size_y(&box)),
                                  ptr,
                                  prop_name,
                                  0,
                                  0.0f,
                                  0.0f,
                                  tooltip);
  ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
  if (but != nullptr) {
    ui::mixar_style_button(
        but, ui::MixarComponent::Surface, ui::MixarVariant::Ghost, cinema_unit());
  }
  return but;
}

/** \} */

}  // namespace blender
