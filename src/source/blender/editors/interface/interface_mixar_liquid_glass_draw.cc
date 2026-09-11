/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar liquid glass: the painter behind `mixar_glass_draw`. Read
 * `ED_mixar_glass.hh` for what a pane is made of and why; the material table
 * is in `interface_mixar_liquid_glass_tokens.cc` and the blur is in
 * `interface_mixar_liquid_glass.cc`.
 *
 * A TEXTURE CANNOT FILL A ROUNDED SHAPE
 * `ui::draw_roundbox_4fv_ex` takes colours, not a texture, so a pane cannot be
 * one call. It is instead a rounded SILHOUETTE that is only ever drawn with
 * rounded primitives, with the rectangular blurred bed laid inside it. The bed
 * is inset by `min(radius * 0.5, min(w, h) * 0.25)`: a rounded corner departs
 * from its corner square by at most `radius * (1 - cos 45°) ≈ 0.293 * radius`,
 * so half a radius of inset keeps every square corner of the bed strictly
 * inside the silhouette. The band that leaves is not a defect — it is where
 * the rim and the refraction wash live.
 *
 * THE LAYER ORDER IS THE MATERIAL, bottom to top: shadow, tinted silhouette,
 * blurred bed + glaze, top gloss, refraction wash, specular streak, rim. Each
 * layer reads its own tokens, so a role can switch a layer off by zeroing an
 * alpha (`CHIP` carries no shadow and no specular) without special cases here.
 *
 * Refraction and the travelling streak are lighting: they only read as glass
 * when there is a frosted bed to catch them. No caller in this overlay can
 * capture a backdrop today, so those two layers stay off unless one is handed
 * in — otherwise they dirtied every tinted pane (a diagonal wash and a
 * sweeping bar on painted colour, which is what read as "the glass is weird").
 *
 * The blend mode and the matrix are saved and restored around the whole
 * painter, so a caller may draw a pane mid-pass, and the blend mode alone
 * around the blur's inner passes is handled in the chain.
 */

#include <algorithm>
#include <cmath>

#include "BLI_rect.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "DNA_userdef_types.h"

#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_shader.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"

#include "ED_mixar_glass.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {
namespace ui {

namespace {

/** Lean of the travelling specular streak, in DEGREES: `GPU_matrix_rotate_2d`
 * takes degrees, as its call sites show (`wm_operators.cc` wraps its own
 * radians in `RAD2DEGF` before calling it). 22° reads as light raking across
 * the pane rather than a symmetric band. */
constexpr float GLASS_SPECULAR_TILT_DEG = 22.0f;

/**
 * Draw the window of \a tex covering \a src at \a dst, in the caller's space.
 *
 * \a src is in the caller's pixels and need not contain \a dst: the texture
 * coordinates are clamped, so a pane hanging off the edge of its backdrop
 * smears that edge rather than wrapping or sampling outside. This is the one
 * place a pane is allowed to be larger than its backdrop — a card straddling
 * the viewport's border.
 *
 * The colour variant of the shader, not the plain one, because it carries a
 * uniform colour that multiplies the sample (`wm_operators.cc` binds it the
 * same way for its image draw): with white it changes nothing at full alpha,
 * and with a fading pane it lets the blurred backdrop fade with the tint
 * instead of popping in. `GPU_SHADER_3D_IMAGE` has no such uniform, so a pane
 * drawn with it could only ever appear at full strength.
 */
void glass_draw_texture_window(gpu::Texture *tex,
                               const rctf *dst,
                               const rcti *src,
                               const float alpha)
{
  if (tex == nullptr || src == nullptr || alpha <= 0.0f) {
    return;
  }
  const float sx = std::max(BLI_rcti_size_x(src), 1);
  const float sy = std::max(BLI_rcti_size_y(src), 1);
  const float x0 = float(src->xmin);
  const float y0 = float(src->ymin);
  const auto u_of = [x0, sx](const float x) { return std::clamp((x - x0) / sx, 0.0f, 1.0f); };
  const auto v_of = [y0, sy](const float y) { return std::clamp((y - y0) / sy, 0.0f, 1.0f); };
  const float white[3] = {1.0f, 1.0f, 1.0f};

  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint texcoord = GPU_vertformat_attr_add(
      format, "texCoord", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_IMAGE_COLOR);
  immUniformColor3fvAlpha(white, alpha);
  immBindTexture("image", tex);
  immBegin(GPU_PRIM_TRI_FAN, 4);
  immAttr2f(texcoord, u_of(dst->xmin), v_of(dst->ymin));
  immVertex2f(pos, dst->xmin, dst->ymin);
  immAttr2f(texcoord, u_of(dst->xmax), v_of(dst->ymin));
  immVertex2f(pos, dst->xmax, dst->ymin);
  immAttr2f(texcoord, u_of(dst->xmax), v_of(dst->ymax));
  immVertex2f(pos, dst->xmax, dst->ymax);
  immAttr2f(texcoord, u_of(dst->xmin), v_of(dst->ymax));
  immVertex2f(pos, dst->xmin, dst->ymax);
  immEnd();
  immUnbindProgram();
}

/**
 * The diagonal wash that reads as a thick edge refracting the pane's own
 * light: brightest at the top-left, dissolving through the middle, darkest at
 * the bottom-right. One smooth-shaded quad, because `draw_roundbox_4fv_ex` can
 * only ramp vertically.
 *
 * This is the fake that stands in for per-pixel refraction. Without a fragment
 * shader the kit cannot sample an offset copy of the backdrop, so the "bent"
 * light is painted rather than sampled; the two clear corners are what keep it
 * from reading as a plain two-stop gradient.
 */
void glass_draw_refraction(const rctf *rect, const float col[4], const float alpha)
{
  const float lit[4] = {col[0], col[1], col[2], col[3] * alpha};
  const float clear[4] = {col[0], col[1], col[2], 0.0f};
  const float dark[4] = {col[0] * 0.30f, col[1] * 0.30f, col[2] * 0.30f, col[3] * alpha};

  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint color = GPU_vertformat_attr_add(
      format, "color", gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);
  immBegin(GPU_PRIM_TRI_FAN, 4);
  immAttr4fv(color, lit);
  immVertex2f(pos, rect->xmin, rect->ymax);
  immAttr4fv(color, clear);
  immVertex2f(pos, rect->xmax, rect->ymax);
  immAttr4fv(color, dark);
  immVertex2f(pos, rect->xmax, rect->ymin);
  immAttr4fv(color, clear);
  immVertex2f(pos, rect->xmin, rect->ymin);
  immEnd();
  immUnbindProgram();
}

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Painter
 * \{ */

void mixar_glass_draw(const rcti &rect,
                      const MixarGlassStyle &style,
                      const MixarGlassBackdrop &backdrop)
{
  const int width = BLI_rcti_size_x(&rect);
  const int height = BLI_rcti_size_y(&rect);
  if (width <= 0 || height <= 0 || style.alpha <= 0.0f) {
    return;
  }

  const MixarGlassTokens t = mixar_glass_tokens(style.role);
  const float alpha = style.alpha;
  const float radius = std::clamp(style.radius >= 0.0f ? style.radius : t.radius,
                                 0.0f,
                                 std::min(width, height) * 0.5f);

  rctf box;
  BLI_rctf_rcti_copy(&box, &rect);

  const GPUBlend blend_prev = GPU_blend_get();
  GPU_blend(GPU_BLEND_ALPHA);
  GPU_matrix_push_projection();
  GPU_matrix_push();

  /* Layer 1 — the drop shadow, under everything. Grown outward by one pixel so
   * the pane's own silhouette does not eat the top of its own shadow. */
  if (style.draw_shadow && t.shadow[3] > 0.0f) {
    rctf shadow = box;
    BLI_rctf_pad(&shadow, -U.pixelsize, -U.pixelsize);
    draw_roundbox_corner_set(CNR_ALL);
    draw_dropshadow(&shadow, radius, t.shadow_width, 1.0f, t.shadow[3] * alpha);
  }

  const float tint_top[4] = {t.tint_top[0], t.tint_top[1], t.tint_top[2], t.tint_top[3] * alpha};
  const float tint_bottom[4] = {
      t.tint_bottom[0], t.tint_bottom[1], t.tint_bottom[2], t.tint_bottom[3] * alpha};

  /* Layer 2 — the tinted silhouette. Every pane in the family is lit from
   * above, so the ramp is vertical; `nullptr` inners means "no outline", which
   * layer 7 draws instead. */
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv_ex(&box, tint_top, tint_bottom, 1.0f, nullptr, 0.0f, radius);

  const float inset = std::min(radius * 0.5f, std::min(float(width), float(height)) * 0.25f);

  /* Layer 3 — the blurred backdrop and the glaze that unifies it with the
   * tint. Drawn at the pane's own alpha, so a reveal animation fades the
   * backdrop in step with the tint rather than popping it in at the end. */
  if (backdrop.valid()) {
    rctf bed = box;
    bed.xmin += inset;
    bed.ymin += inset;
    bed.xmax -= inset;
    bed.ymax -= inset;
    glass_draw_texture_window(backdrop.texture, &bed, &backdrop.rect, alpha);
    if (t.glaze[3] > 0.0f) {
      const float glaze[4] = {t.glaze[0], t.glaze[1], t.glaze[2], t.glaze[3] * alpha};
      draw_roundbox_corner_set(CNR_ALL);
      draw_roundbox_4fv(&bed, true, std::max(radius - inset, 0.0f), glaze);
    }
  }

  /* Layer 4 — the top gloss. Two bands: a wide catch-light and a narrower,
   * brighter one inside it, which is what makes the light read as catching a
   * curved surface rather than a flat gradient.
   *
   * The band is the token height, capped to a fraction of the pane — never
   * the corner radius. A capsule's radius is half its short side, so using
   * that as a floor flooded the top half of every pill and turned the island
   * card's sheen into a coloured header bar. */
  if (t.sheen[3] > 0.0f) {
    const float band = std::min(t.sheen_height, float(height) * 0.28f);
    rctf gloss = box;
    gloss.ymin = std::max(box.ymin, box.ymax - band);
    const float sheen_lit[4] = {t.sheen[0], t.sheen[1], t.sheen[2], t.sheen[3] * alpha};
    const float sheen_clear[4] = {t.sheen[0], t.sheen[1], t.sheen[2], 0.0f};
    draw_roundbox_corner_set(CNR_TOP_LEFT | CNR_TOP_RIGHT);
    draw_roundbox_4fv_ex(&gloss, sheen_lit, sheen_clear, 1.0f, nullptr, 0.0f, radius);

    rctf inner = gloss;
    const float pad = std::max(band * 0.25f, 1.0f);
    inner.xmin += pad;
    inner.xmax -= pad;
    inner.ymin = std::max(inner.ymin, inner.ymax - band * 0.5f);
    const float inner_lit[4] = {sheen_lit[0], sheen_lit[1], sheen_lit[2], sheen_lit[3] * 0.6f};
    draw_roundbox_corner_set(CNR_TOP_LEFT | CNR_TOP_RIGHT);
    draw_roundbox_4fv_ex(
        &inner, inner_lit, sheen_clear, 1.0f, nullptr, 0.0f, std::max(radius - pad, 0.0f));
  }

  /* Layer 5 — the refraction wash, only over a frosted bed. On a tinted
   * silhouette with nothing behind it this is just a diagonal gradient, and
   * that is the cheap bevel the panes were reading as. */
  if (backdrop.valid() && t.refract[3] > 0.0f) {
    rctf inside = box;
    inside.xmin += inset;
    inside.ymin += inset;
    inside.xmax -= inset;
    inside.ymax -= inset;
    glass_draw_refraction(&inside, t.refract, alpha);
  }

  /* Layer 6 — the travelling specular streak. Time-driven, not random, so a
   * still frame is reproducible and two panes side by side sweep together.
   * Clipped to the pane's inner band, because the streak is a bar and the pane
   * is not a rectangle. */
  const float inner_w = float(width) - inset * 2.0f;
  const float inner_h = float(height) - inset * 2.0f;
  if (backdrop.valid() && style.draw_specular && t.specular_alpha > 0.0f &&
      t.specular_width > 0.0f && t.specular_period > 0.0f && inner_w > 0.0f &&
      inner_h > 0.0f)
  {
    const float travel = inner_w + t.specular_width;
    const float phase = float(
        std::fmod(BLI_time_now_seconds() / double(t.specular_period), 1.0));
    const float sweep = -t.specular_width + phase * travel;
    rctf bar = box;
    bar.xmin = box.xmin + inset + sweep;
    bar.xmax = bar.xmin + t.specular_width;
    bar.ymin = box.ymin + inset;
    bar.ymax = box.ymax - inset;

    /* A pane may hang off the region (a card straddling the viewport's edge),
     * and a negative scissor origin is not valid, so the clip is pinned to the
     * window's origin and the region clips whatever is left. */
    const int clip_x = std::max(rect.xmin + int(inset), 0);
    const int clip_y = std::max(rect.ymin + int(inset), 0);
    int scissor_prev[4];
    GPU_scissor_get(scissor_prev);
    GPU_scissor(clip_x, clip_y, std::max(int(inner_w), 1), std::max(int(inner_h), 1));
    /* Rotate about the bar's own centre, so the lean does not walk the streak
     * off the pane at the ends of its travel. */
    const float cx = BLI_rctf_cent_x(&bar);
    const float cy = BLI_rctf_cent_y(&bar);
    GPU_matrix_push();
    GPU_matrix_translate_2f(cx, cy);
    GPU_matrix_rotate_2d(GLASS_SPECULAR_TILT_DEG);
    GPU_matrix_translate_2f(-cx, -cy);
    const float streak[4] = {t.sheen[0], t.sheen[1], t.sheen[2], t.specular_alpha * alpha};
    draw_roundbox_corner_set(CNR_ALL);
    draw_roundbox_4fv(&bar, true, t.specular_width * 0.5f, streak);
    GPU_matrix_pop();
    GPU_scissor(scissor_prev[0], scissor_prev[1], scissor_prev[2], scissor_prev[3]);
  }

  /* Layer 7 — the rim, last, so it sits on top of everything it contains. */
  if (t.rim_width > 0.0f && t.rim[3] > 0.0f) {
    const float rim[4] = {t.rim[0], t.rim[1], t.rim[2], t.rim[3] * alpha};
    draw_roundbox_corner_set(CNR_ALL);
    draw_roundbox_4fv_ex(&box, nullptr, nullptr, 1.0f, rim, t.rim_width, radius);
  }

  GPU_matrix_pop();
  GPU_matrix_pop_projection();
  GPU_blend(blend_prev);
}

/** \} */

}  // namespace ui
}  // namespace blender
