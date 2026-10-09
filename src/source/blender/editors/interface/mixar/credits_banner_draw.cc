/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Out-of-credits card: native heading, centered artwork, two green actions,
 * and a deliberate slide-to-continue control. Everything is drawn in
 * window pixels by a WM draw callback, so it sits above every editor.
 *
 * Geometry lives in `layout_compute`, shared with the click handler and the
 * QA targets; this file only paints.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_rect.h"
#include "BLI_time.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"

#include "IMB_imbuf.hh"
#include "IMB_imbuf_types.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar_motion.hh"
#include "UI_resources.hh"

#include "WM_api.hh"

#include "credits_banner.hh"

namespace blender::ui::credits_banner {

static const float GREEN_TOP[3] = {0.10f, 0.59f, 0.28f};
static const float GREEN_BOTTOM[3] = {0.025f, 0.25f, 0.10f};

/* -------------------------------------------------------------------- */
/** \name Texture
 * \{ */

static bool texture_ensure(State &state)
{
  if (state.texture || state.image_failed) {
    return state.texture != nullptr;
  }
  ImBuf *ibuf = state.image_path.empty() ?
                    nullptr :
                    IMB_load_image_from_filepath(state.image_path.c_str(), ImBufFlags::ByteData);
  if (!ibuf || !ibuf->byte_buffer.data || ibuf->x <= 0 || ibuf->y <= 0) {
    if (ibuf) {
      IMB_freeImBuf(ibuf);
    }
    state.image_failed = true;
    return false;
  }
  /* Raw sRGB bytes, like the moodboard: the UI framebuffer shows them as-is.
   * A full mip chain keeps the art clean when it is drawn smaller than 1:1. */
  const int mips = 1 + int(std::floor(std::log2(float(std::max(ibuf->x, ibuf->y)))));
  state.texture = GPU_texture_create_2d("mixar_credits_banner",
                                        ibuf->x,
                                        ibuf->y,
                                        mips,
                                        gpu::TextureFormat::UNORM_8_8_8_8,
                                        GPU_TEXTURE_USAGE_GENERAL,
                                        nullptr);
  if (state.texture) {
    GPU_texture_update(state.texture, GPU_DATA_UBYTE, ibuf->byte_buffer.data);
    GPU_texture_update_mipmap_chain(state.texture);
    GPU_texture_filter_mode(state.texture, true);
    GPU_texture_mipmap_mode(state.texture, true, true);
    state.image_w = ibuf->x;
    state.image_h = ibuf->y;
  }
  else {
    state.image_failed = true;
  }
  IMB_freeImBuf(ibuf);
  return state.texture != nullptr;
}

void texture_free(State &state)
{
  if (state.texture) {
    GPU_texture_free(state.texture);
    state.texture = nullptr;
  }
}

static void draw_texture(gpu::Texture *tex, const rctf &r, const float alpha)
{
  GPU_texture_bind(tex, 0);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint uv = GPU_vertformat_attr_add(format, "texCoord", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_IMAGE_COLOR);
  immUniformColor4f(1.0f, 1.0f, 1.0f, alpha);
  immBegin(GPU_PRIM_TRI_FAN, 4);
  immAttr2f(uv, 0.0f, 0.0f);
  immVertex2f(pos, r.xmin, r.ymin);
  immAttr2f(uv, 1.0f, 0.0f);
  immVertex2f(pos, r.xmax, r.ymin);
  immAttr2f(uv, 1.0f, 1.0f);
  immVertex2f(pos, r.xmax, r.ymax);
  immAttr2f(uv, 0.0f, 1.0f);
  immVertex2f(pos, r.xmin, r.ymax);
  immEnd();
  immUnbindProgram();
  GPU_texture_unbind(tex);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Primitives
 * \{ */

static void rgba(float out[4], const float rgb[3], const float a)
{
  out[0] = rgb[0];
  out[1] = rgb[1];
  out[2] = rgb[2];
  out[3] = a;
}

static rctf expanded(const rctf &r, const float by)
{
  rctf e = r;
  BLI_rctf_pad(&e, by, by);
  return e;
}

/** Vertical gradient round box, `top` over `bottom`, optional outline. */
static void round_box(const rctf &r,
                      const float radius,
                      const float top[4],
                      const float bottom[4],
                      const float outline[4] = nullptr,
                      const float outline_width = 0.0f)
{
  const float clear[4] = {0.0f, 0.0f, 0.0f, 0.0f};
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv_ex(&r,
                       top,
                       bottom,
                       1.0f,
                       outline ? outline : clear,
                       outline ? outline_width : 0.0f,
                       std::min(radius, std::min(BLI_rctf_size_x(&r), BLI_rctf_size_y(&r)) * 0.5f));
}

/** Soft halo: stacked translucent round boxes fading outwards. */
static void glow(const rctf &r,
                 const float radius,
                 const float rgb[3],
                 const float strength,
                 const float reach,
                 const int layers)
{
  if (strength <= 0.001f) {
    return;
  }
  for (int i = layers; i >= 1; i--) {
    const float f = float(i) / float(layers);
    const float grow = reach * f;
    float c[4];
    rgba(c, rgb, strength * (1.0f - f) * (1.0f - f) * 0.9f + strength * 0.02f);
    round_box(expanded(r, grow), radius + grow, c, c);
  }
}

static void text_centered(const int font,
                          const char *str,
                          const float cx,
                          const float cy,
                          const float color[4])
{
  const size_t len = strlen(str);
  rcti bb;
  BLF_boundbox(font, str, len, &bb);
  const float w = BLF_width(font, str, len);
  const float x = cx - w * 0.5f;
  const float y = cy - float(BLI_rcti_size_y(&bb)) * 0.5f - float(bb.ymin);
  BLF_color4fv(font, color);
  BLF_position(font, x, y, 0.0f);
  BLF_draw(font, str, len);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Buttons
 * \{ */

static float label_size(const Layout &layout)
{
  return layout.button_h * 0.28f;
}

/** Draw the supplied vector art in native pixels, preserving its embedded colors. */
static void draw_icon(const int icon, const float cx, const float cy,
                      const float size, const float alpha)
{
  const float color[4] = {1.0f, 1.0f, 1.0f, alpha};
  BLF_draw_svg_icon(uint(icon), cx - size * 0.5f, cy - size * 0.5f,
                    size, color, 0.0f, true, nullptr);
}

static void draw_button(const State &state, const Layout &layout, const Target target,
                        const float alpha)
{
  const rctf &r = layout.targets[target];
  const float hover = state.hover_mix[target];
  float top[4], bottom[4];
  const float shade = state.pressed == target ? 0.8f : 1.0f;
  rgba(top, GREEN_TOP, alpha);
  rgba(bottom, GREEN_BOTTOM, alpha);
  for (int i = 0; i < 3; i++) {
    top[i] = std::min(1.0f, top[i] * shade + hover * 0.045f);
    bottom[i] *= shade;
  }
  const float outline[4] = {0.38f, 0.82f, 0.46f, (0.12f + 0.20f * hover) * alpha};
  round_box(r, layout.button_h * 0.32f, top, bottom, outline, 1.0f);
  const int font = BLF_default();
  const float size = label_size(layout);
  BLF_size(font, size);
  const char *label = target_label(target, state.subscribe);
  const float width = BLF_width(font, label, strlen(label));
  const float center = BLI_rctf_cent_x(&r);
  const float cy = BLI_rctf_cent_y(&r);
  const float ink[4] = {0.94f, 0.98f, 0.94f, alpha};
  const float icon_size = size * 1.4f;
  const float gap = size * 0.35f;
  text_centered(font, label, center + (icon_size + gap) * 0.5f, cy, ink);
  draw_icon(target == TARGET_UPGRADE ? ICON_CREDITS_UPGRADE : ICON_CREDITS_REFER,
            center - (width + gap) * 0.5f, cy, icon_size, alpha);
}

static void draw_slider(const State &state, const Layout &layout, const float alpha,
                        const double now)
{
  const rctf &r = layout.targets[TARGET_CREATOR];
  const float hover = state.hover_mix[TARGET_CREATOR];
  const float top[4] = {0.055f, 0.055f, 0.055f, alpha};
  const float bottom[4] = {0.028f, 0.028f, 0.028f, alpha};
  const float rim[4] = {0.23f, 0.38f, 0.27f, (0.18f + 0.25f * hover) * alpha};
  round_box(r, layout.button_h * 0.4f, top, bottom, rim, 1.0f);
  const rctf thumb = slider_thumb(layout, state.slide);
  const rctf start = slider_thumb(layout, 0.0f);
  const float text_x = (start.xmax + r.xmax) * 0.5f;
  const float cy = BLI_rctf_cent_y(&r);
  const int font = BLF_default();
  BLF_size(font, label_size(layout) * 0.94f);
  const char *hint = creator_hint(state);
  const float available = r.xmax - start.xmax - layout.button_h * 0.1f;
  const bool resting = strcmp(hint, "Creator Program") == 0;
  const float icon_size = label_size(layout) * 1.2f;
  const float icon_space = resting ? icon_size + label_size(layout) * 0.25f : 0.0f;
  float width = BLF_width(font, hint, strlen(hint));
  if (width + icon_space > available) {
    BLF_size(font, label_size(layout) * 0.94f * (available - icon_space) / width);
    width = BLF_width(font, hint, strlen(hint));
  }
  // Hint fades in on hover; a restrained shimmer teaches the slide direction.
  const float pulse = mixar_motion_reduced() ? 1.0f :
                          0.82f + 0.18f * std::sin(float(now) * 3.5f);
  const float ink[4] = {0.78f, 0.80f, 0.78f,
                        alpha * (0.65f + hover * 0.35f) * pulse * (1.0f - state.slide)};
  text_centered(font, hint, text_x + icon_space * 0.5f, cy, ink);
  if (resting) {
    draw_icon(ICON_CREDITS_CREATOR, text_x - (width + icon_space - icon_size) * 0.5f,
              cy, icon_size, alpha * (1.0f - state.slide));
  }
  float knob_top[4], knob_bottom[4];
  rgba(knob_top, GREEN_TOP, alpha);
  rgba(knob_bottom, GREEN_BOTTOM, alpha);
  round_box(thumb, layout.button_h * 0.42f, knob_top, knob_bottom);
  const float nudge = mixar_motion_reduced() || state.dragging ? 0.0f :
                          hover * layout.button_h * 0.035f * std::sin(float(now) * 4.0f);
  draw_icon(ICON_CREDITS_SLIDE, BLI_rctf_cent_x(&thumb) + nudge, cy,
            layout.button_h * 0.48f, alpha);
  if (state.focus == TARGET_CREATOR || state.slide > 0.01f) {
    BLF_size(font, label_size(layout));
    const float caption[4] = {0.72f, 0.76f, 0.72f, alpha};
    text_centered(font, hint, BLI_rctf_cent_x(&r), r.ymax + layout.button_h * 0.4f, caption);
  }
}

static void draw_close(const State &state, const Layout &layout, const float appear)
{
  const rctf &r = layout.targets[TARGET_CLOSE];
  const float hover = state.hover_mix[TARGET_CLOSE];
  const float size = BLI_rctf_size_x(&r);
  const float bg[4] = {0.08f, 0.08f, 0.08f, (0.75f + 0.25f * hover) * appear};
  const float rim[4] = {1.0f, 1.0f, 1.0f, (0.14f + 0.30f * hover) * appear};
  round_box(r, size * 0.24f, bg, bg, rim, 0.5f);
  const int font = BLF_default();
  BLF_size(font, size * 0.42f);
  const float ink[4] = {1.0f, 1.0f, 1.0f, (0.72f + 0.28f * hover) * appear};
  text_centered(font, "\xE2\x9C\x95" /* ✕ */, BLI_rctf_cent_x(&r), BLI_rctf_cent_y(&r), ink);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Window draw callback
 * \{ */

void draw(const wmWindow *win, void *customdata)
{
  State *state = static_cast<State *>(customdata);
  if (!state || state->win != win) {
    return;
  }
  const double now = BLI_time_now_seconds();
  const float motion = appear_factor(*state, now);
  const float appear = std::min(motion, 1.0f);    /* opacity */
  texture_ensure(*state);
  const Layout layout = layout_compute(*state, motion);
  const float winx = float(WM_window_native_pixel_x(win));
  const float winy = float(WM_window_native_pixel_y(win));
  const float card_w = BLI_rctf_size_x(&layout.card);

  const GPUBlend prev_blend = GPU_blend_get();
  GPU_blend(GPU_BLEND_ALPHA);

  /* Dim the whole app. */
  {
    rctf full;
    BLI_rctf_init(&full, 0.0f, winx, 0.0f, winy);
    const float scrim[4] = {0.008f, 0.016f, 0.012f, 0.76f * appear};
    round_box(full, 0.0f, scrim, scrim);
  }

  const float card_h = BLI_rctf_size_y(&layout.card);
  const float bg[4] = {0.006f, 0.006f, 0.006f, 0.98f * appear};
  const float rim[4] = {0.18f, 0.18f, 0.18f, 0.7f * appear};
  round_box(layout.card, layout.radius, bg, bg, rim, 1.0f);
  // The soft neutral wash keeps the cat legible without a luminous green frame.
  const float wash[3] = {0.14f, 0.14f, 0.14f};
  rctf halo = layout.art;
  BLI_rctf_pad(&halo, -card_w * 0.04f, -card_h * 0.06f);
  glow(halo, card_w * 0.20f, wash, 0.08f * appear, card_w * 0.12f, 16);
  if (state->texture) {
    rctf art = layout.art;
    const float aspect = float(state->image_w) / float(std::max(state->image_h, 1));
    const float height = std::min(BLI_rctf_size_y(&art), BLI_rctf_size_x(&art) / aspect);
    const float width = height * aspect;
    art.ymax = art.ymin + height;
    const float center = BLI_rctf_cent_x(&art);
    art.xmin = center - width * 0.5f;
    art.xmax = center + width * 0.5f;
    draw_texture(state->texture, art, appear);
  }
  const int font = BLF_default();
  BLF_size(font, card_w * 0.052f);
  BLF_character_weight(font, 700);
  const float ink[4] = {0.95f, 0.95f, 0.95f, appear};
  text_centered(font,
                state->subscribe ? "Subscribe to continue" : "You're all out of credits!",
                BLI_rctf_cent_x(&layout.card),
                layout.card.ymax - card_h * 0.145f, ink);
  BLF_character_weight(font, 400);
  BLF_size(font, card_w * 0.024f);
  const float muted[4] = {0.50f, 0.50f, 0.50f, appear};
  text_centered(font,
                state->subscribe ? "This feature uses credits. Subscribe or Earn Credits?" :
                                   "Upgrade Plan or Earn Credits?",
                BLI_rctf_cent_x(&layout.card),
                layout.card.ymax - card_h * 0.215f, muted);
  draw_button(*state, layout, TARGET_UPGRADE, appear);
  draw_button(*state, layout, TARGET_REFER, appear);
  draw_slider(*state, layout, appear, now - state->opened_at);
  draw_close(*state, layout, appear);

  GPU_blend(prev_blend);
}

/** \} */

}  // namespace blender::ui::credits_banner
