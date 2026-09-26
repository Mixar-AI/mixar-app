/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Out-of-credits banner painter: a dimmed window, a soft green bloom behind
 * the banner art, the art itself, and three call-to-action buttons seated in
 * the art's bottom band (under its "down" chevron). Everything is drawn in
 * window pixels by a WM draw callback, so it sits above every editor.
 *
 * Geometry lives in `layout_compute`, shared with the click handler and the
 * QA targets; this file only paints.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_math_base.h"
#include "BLI_math_vector.h"
#include "BLI_rect.h"
#include "BLI_time.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"

#include "IMB_imbuf.hh"
#include "IMB_imbuf_types.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "WM_api.hh"

#include "credits_banner.hh"

namespace blender::ui::credits_banner {

/* Palette sampled from the banner art: the headline greens and the coins. */
static const float GREEN_TOP[3] = {0.62f, 0.97f, 0.64f};
static const float GREEN_BOTTOM[3] = {0.25f, 0.80f, 0.40f};
static const float GREEN_GLOW[3] = {0.36f, 0.95f, 0.50f};
static const float GOLD_TOP[3] = {1.00f, 0.86f, 0.42f};
static const float GOLD_BOTTOM[3] = {0.91f, 0.64f, 0.14f};
static const float GLASS_TOP[3] = {0.075f, 0.140f, 0.095f};
static const float GLASS_BOTTOM[3] = {0.035f, 0.070f, 0.048f};
static const float INK_DARK[3] = {0.02f, 0.08f, 0.04f};
static const float INK_LIGHT[3] = {0.95f, 0.97f, 0.95f};

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

static void mix_rgb(float out[3], const float a[3], const float b[3], const float t)
{
  for (int i = 0; i < 3; i++) {
    out[i] = a[i] + (b[i] - a[i]) * t;
  }
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

/* Leading glyph per button; all three live in the bundled Noto symbol fonts. */
static const char *target_glyph(const Target target)
{
  switch (target) {
    case TARGET_UPGRADE:
      return "\xE2\x9C\xA6"; /* ✦ */
    case TARGET_REFER:
      return "\xE2\x99\xA5"; /* ♥ */
    case TARGET_CREATOR:
      return "\xE2\x98\x85"; /* ★ */
    default:
      return "";
  }
}

/** One font size for all three labels: the largest that fits every button. */
static float label_size(const int font, const Layout &layout)
{
  const float bh = layout.button_h;
  float size = bh * 0.33f;
  const float avail = BLI_rctf_size_x(&layout.targets[TARGET_UPGRADE]) - bh * 0.9f;
  BLF_size(font, size);
  BLF_character_weight(font, 700);
  float widest = 0.0f;
  for (int t = TARGET_UPGRADE; t <= TARGET_CREATOR; t++) {
    const char *label = target_label(Target(t));
    widest = std::max(widest, BLF_width(font, label, strlen(label)));
  }
  BLF_character_weight(font, 400);
  if (widest > avail && widest > 0.0f) {
    size *= avail / widest;
  }
  return std::max(size, bh * 0.2f);
}

static void draw_button(const State &state,
                        const Layout &layout,
                        const Target target,
                        const float appear,
                        const float now_s,
                        const float font_size)
{
  const float hover = state.hover_mix[target];
  const bool pressed = state.pressed == target;
  const float bh = layout.button_h;
  rctf r = layout.targets[target];

  /* Staggered rise-in after the card lands, then a small lift on hover. */
  const float stagger = std::clamp(appear * 1.35f - 0.12f * float(target), 0.0f, 1.0f);
  const float rise = (1.0f - stagger) * bh * 0.35f - hover * bh * 0.05f;
  BLI_rctf_translate(&r, 0.0f, -rise);
  if (pressed) {
    BLI_rctf_scale(&r, 0.97f);
  }
  const float a = stagger;
  if (a <= 0.001f) {
    return;
  }
  const float radius = bh * 0.5f;

  float top[4], bottom[4], outline[4], ink[4];
  if (target == TARGET_UPGRADE) {
    /* Primary: solid green pill with a breathing halo. */
    const float pulse = 0.5f + 0.5f * std::sin(now_s * float(M_PI) * 2.0f / 2.4f);
    glow(r, radius, GREEN_GLOW, (0.16f + 0.08f * pulse + 0.14f * hover) * a, bh * 0.55f, 8);
    const float lift[3] = {0.80f, 1.0f, 0.82f};
    float t3[3], b3[3];
    mix_rgb(t3, GREEN_TOP, lift, 0.35f * hover);
    mix_rgb(b3, GREEN_BOTTOM, GREEN_TOP, 0.25f * hover);
    rgba(top, t3, a);
    rgba(bottom, b3, a);
    const float rim[3] = {0.85f, 1.0f, 0.86f};
    rgba(outline, rim, 0.55f * a);
    rgba(ink, INK_DARK, a);
  }
  else {
    /* Secondary: dark glass with a lit rim — green for referral, coin gold
     * for the Creator Program so it reads as its own, special track. */
    const float *accent = target == TARGET_CREATOR ? GOLD_TOP : GREEN_TOP;
    glow(r, radius, accent, (0.05f + 0.13f * hover) * a, bh * 0.45f, 6);
    float t3[3], b3[3];
    mix_rgb(t3, GLASS_TOP, accent, 0.10f + 0.10f * hover);
    mix_rgb(b3, GLASS_BOTTOM, accent, 0.03f + 0.06f * hover);
    rgba(top, t3, 0.94f * a);
    rgba(bottom, b3, 0.94f * a);
    rgba(outline, accent, (0.55f + 0.45f * hover) * a);
    rgba(ink, INK_LIGHT, a);
  }
  round_box(r, radius, top, bottom, outline, std::max(1.0f, bh * 0.028f));

  /* Glass sheen on the upper half. */
  {
    rctf sheen = r;
    BLI_rctf_pad(&sheen, -bh * 0.06f, -bh * 0.06f);
    sheen.ymin = BLI_rctf_cent_y(&r);
    const float s_top[4] = {1.0f, 1.0f, 1.0f, (target == TARGET_UPGRADE ? 0.16f : 0.05f) * a};
    const float s_bot[4] = {1.0f, 1.0f, 1.0f, 0.0f};
    round_box(sheen, radius * 0.9f, s_top, s_bot);
  }

  /* Glyph + label, centred together. */
  const int font = BLF_default();
  const char *label = target_label(target);
  const char *glyph = target_glyph(target);
  BLF_size(font, font_size);
  BLF_character_weight(font, 700);
  const float label_w = BLF_width(font, label, strlen(label));
  BLF_character_weight(font, 400);
  const float glyph_size = font_size * 1.05f;
  BLF_size(font, glyph_size);
  const float glyph_w = BLF_width(font, glyph, strlen(glyph));
  const float gap = font_size * 0.5f;
  const float total = glyph_w + gap + label_w;
  const float x0 = BLI_rctf_cent_x(&r) - total * 0.5f;
  const float cy = BLI_rctf_cent_y(&r);

  float glyph_col[4];
  if (target == TARGET_CREATOR) {
    rgba(glyph_col, GOLD_TOP, a);
  }
  else if (target == TARGET_REFER) {
    rgba(glyph_col, GREEN_TOP, a);
  }
  else {
    copy_v4_v4(glyph_col, ink);
  }
  text_centered(font, glyph, x0 + glyph_w * 0.5f, cy, glyph_col);
  BLF_size(font, font_size);
  BLF_character_weight(font, 700);
  text_centered(font, label, x0 + glyph_w + gap + label_w * 0.5f, cy, ink);
  BLF_character_weight(font, 400);

  /* "10K+ followers" chip hanging on the Creator button's top edge. */
  if (target == TARGET_CREATOR) {
    rctf badge = layout.badge;
    BLI_rctf_translate(&badge, 0.0f, -rise);
    float b_top[4], b_bot[4];
    rgba(b_top, GOLD_TOP, a);
    rgba(b_bot, GOLD_BOTTOM, a);
    const float shadow[4] = {0.0f, 0.0f, 0.0f, 0.35f * a};
    rctf drop = badge;
    BLI_rctf_translate(&drop, 0.0f, -bh * 0.03f);
    round_box(expanded(drop, bh * 0.02f), BLI_rctf_size_y(&badge), shadow, shadow);
    round_box(badge, BLI_rctf_size_y(&badge) * 0.5f, b_top, b_bot);
    const float badge_ink[4] = {0.18f, 0.10f, 0.0f, a};
    BLF_size(font, BLI_rctf_size_y(&badge) * 0.56f);
    BLF_character_weight(font, 800);
    text_centered(font, "10K+ FOLLOWERS", BLI_rctf_cent_x(&badge), BLI_rctf_cent_y(&badge), badge_ink);
    BLF_character_weight(font, 400);
  }
}

static void draw_close(const State &state, const Layout &layout, const float appear)
{
  const rctf &r = layout.targets[TARGET_CLOSE];
  const float hover = state.hover_mix[TARGET_CLOSE];
  const float size = BLI_rctf_size_x(&r);
  const float bg[4] = {0.0f, 0.0f, 0.0f, (0.42f + 0.25f * hover) * appear};
  const float rim[4] = {1.0f, 1.0f, 1.0f, (0.14f + 0.30f * hover) * appear};
  round_box(r, size * 0.5f, bg, bg, rim, std::max(1.0f, size * 0.03f));
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
  const float motion = appear_factor(*state, now); /* may overshoot 1 */
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

  /* Drop shadow, then a green bloom so the card glows off the dark. */
  {
    rctf shadow = layout.card;
    BLI_rctf_translate(&shadow, 0.0f, -card_w * 0.012f);
    const float black[3] = {0.0f, 0.0f, 0.0f};
    glow(shadow, layout.radius, black, 0.55f * appear, card_w * 0.035f, 8);
    glow(layout.card, layout.radius, GREEN_GLOW, 0.075f * appear, card_w * 0.07f, 10);
  }

  if (state->texture) {
    GPU_blend(GPU_BLEND_ALPHA);
    draw_texture(state->texture, layout.card, appear);
  }
  else {
    /* The art is missing from the install: keep the CTA usable on a plain card. */
    float top[4], bottom[4], outline[4];
    rgba(top, GLASS_TOP, appear);
    rgba(bottom, GLASS_BOTTOM, appear);
    rgba(outline, GREEN_TOP, 0.6f * appear);
    round_box(layout.card, layout.radius, top, bottom, outline, 2.0f);
    const int font = BLF_default();
    BLF_size(font, card_w * 0.04f);
    BLF_character_weight(font, 800);
    const float ink[4] = {INK_LIGHT[0], INK_LIGHT[1], INK_LIGHT[2], appear};
    text_centered(font,
                  "You're out of credits",
                  BLI_rctf_cent_x(&layout.card),
                  layout.card.ymin + BLI_rctf_size_y(&layout.card) * 0.6f,
                  ink);
    BLF_character_weight(font, 400);
  }

  /* Hairline rim so the rounded card edge stays crisp on the scrim. */
  {
    const float clear[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    const float rim[4] = {0.55f, 1.0f, 0.62f, 0.10f * appear};
    round_box(layout.card, layout.radius, clear, clear, rim, std::max(1.0f, card_w * 0.0008f));
  }

  const int font = BLF_default();
  const float font_size = label_size(font, layout);
  for (int t = TARGET_UPGRADE; t <= TARGET_CREATOR; t++) {
    draw_button(*state, layout, Target(t), appear, float(now - state->opened_at), font_size);
  }
  draw_close(*state, layout, appear);

  GPU_blend(prev_blend);
}

/** \} */

}  // namespace blender::ui::credits_banner
