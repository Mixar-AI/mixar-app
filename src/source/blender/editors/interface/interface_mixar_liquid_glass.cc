/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar liquid glass: the palette, the blur and the window request behind
 * `ED_mixar_glass.hh`. Read that header first — it states what a pane is made
 * of, why the backdrop is a caller-supplied texture, and why the surfaces are
 * a table. The painter is `interface_mixar_liquid_glass_draw.cc`.
 *
 * Two implementation decisions worth knowing before reading the code:
 *
 * THE BLUR IS A DOWNSAMPLE, NOT A KERNEL
 * There is no way to author a fragment shader in this overlay (the whole `gpu`
 * module is upstream and absent here), so a real separable Gaussian is out of
 * reach. What IS reachable is bilinear resampling and an offscreen, and a
 * bilinear *downsample* is already a box average: sampling a texture at half
 * resolution is exactly a 2x2 box filter. So the chain resamples the source
 * into `levels[0]`, halves down to `levels[n]`, and then walks back up so the
 * result is smooth rather than a grid of 2x2 blocks. Each halving doubles the
 * effective kernel, which is why the level count follows the requested radius
 * rather than being fixed.
 *
 * EVERY PASS REPLACES, NOTHING BLENDS
 * `GPU_SHADER_3D_IMAGE` exposes no colour uniform (see `draw_gpu_texture_quad`
 * in `space_mixie/mixie_draw_moodboard_images.cc`, which binds a texture and
 * sets only `pos`/`texCoord`), so a blurred level cannot be weighted as it is
 * written. Additive or per-level alpha compositing during the cascade is
 * therefore impossible: a level drawn with `GPU_BLEND_ALPHA` over an
 * opaque-alpha destination can only lower the destination's alpha, which is
 * the opposite of what a blur wants. Every pass is `GPU_BLEND_NONE` and
 * overwrites its target wholesale, which is exactly what a blur is — each
 * level is a complete replacement for the one above it. (The painter does use
 * the colour-carrying variant `GPU_SHADER_3D_IMAGE_COLOR` where a textured
 * quad needs weighting; the cascade deliberately does not, because a cascade
 * stage that faded toward its input would be a blend, not a blur.) Blending is
 * used only for painted layers, which are `draw_roundbox_*` primitives with
 * real per-vertex colour.
 */

#include <algorithm>
#include <cmath>

#include "BLI_math_base.h"
#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "DNA_theme_types.h"
#include "DNA_userdef_types.h"

#include "GPU_framebuffer.hh"
#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_offscreen.hh"
#include "GPU_shader.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"
#include "GPU_viewport.hh"

#include "ED_mixar_glass.hh"

#if defined(__APPLE__) || defined(_WIN32)
/** Defined per platform in `intern/ghost` (Cocoa and Win32). Declared here
 * because this unit must not depend on a bubble header, and with C linkage to
 * match every other declaration of it in the tree. */
extern "C" void Mixar_WindowSetBlurBehind(void *window_handle, bool enable);
#endif

/* Mixar 5.2 port: namespace wrap. */
namespace blender {
namespace ui {

namespace {

/* -------------------------------------------------------------------- */
/** \name Blur chain
 * \{ */

/** Halvings available. 4 levels reach a ~16x kernel, past which a pane-sized
 * backdrop has nothing left to average. */
constexpr int GLASS_BLUR_LEVELS = 4;
/** Below this the pane is smaller than the kernel; the tint alone is clearer. */
constexpr int GLASS_BLUR_MIN_PX = 4;
/** Ceiling on the first level's width. Levels 1..n are cheap (each is a
 * quarter of the one above), but level 0 is a straight copy at source
 * resolution, so it is capped to keep that copy bounded. */
constexpr int GLASS_BLUR_MAX_BASE = 1024;

/** The shared cascade. One surface blurs at a time, so one chain is enough. */
struct GlassBlurChain {
  GPUOffScreen *levels[GLASS_BLUR_LEVELS] = {};
  int level_count = 0;
  int base_w = 0;
  int base_h = 0;
};

GlassBlurChain g_chain;

void glass_chain_release()
{
  for (int i = 0; i < GLASS_BLUR_LEVELS; i++) {
    if (g_chain.levels[i] != nullptr) {
      GPU_offscreen_free(g_chain.levels[i]);
      g_chain.levels[i] = nullptr;
    }
  }
  g_chain.level_count = 0;
  g_chain.base_w = 0;
  g_chain.base_h = 0;
}

/**
 * Allocate (or reuse) a cascade of \a levels halvings from a \a w x \a h base.
 *
 * Reuse is the whole point: these surfaces redraw every frame, and
 * reallocating four framebuffers per redraw is exactly the churn the
 * moodboard texture cache was written to avoid. Sizes and depth are compared,
 * so a caller that resizes gets a fresh chain and one that does not keeps its
 * textures.
 */
bool glass_chain_ensure(const int w, const int h, const int levels)
{
  if (g_chain.level_count == levels && g_chain.base_w == w && g_chain.base_h == h) {
    return true;
  }
  glass_chain_release();

  for (int i = 0; i < levels; i++) {
    char err_out[256] = "unknown";
    g_chain.levels[i] = GPU_offscreen_create(std::max(1, w >> i),
                                             std::max(1, h >> i),
                                             /*allow_hdr*/ true,
                                             gpu::TextureFormat::UNORM_8_8_8_8,
                                             GPU_TEXTURE_USAGE_SHADER_READ,
                                             /*with_depth_buffer*/ false,
                                             err_out);
    if (g_chain.levels[i] == nullptr) {
      glass_chain_release();
      return false;
    }
  }

  g_chain.level_count = levels;
  g_chain.base_w = w;
  g_chain.base_h = h;
  return true;
}

/**
 * Draw \a tex over the whole of \a dst, replacing everything under it. The
 * projection is grown to the destination's own pixel size, so the caller's
 * matrix (the region's pixelspace, ortho'd to the region) does not scale or
 * clip the quad.
 */
void glass_blit_full(GPUOffScreen *dst, gpu::Texture *tex, const GPUBlend blend)
{
  if (dst == nullptr || tex == nullptr) {
    return;
  }
  const int w = GPU_offscreen_width(dst);
  const int h = GPU_offscreen_height(dst);
  if (w <= 0 || h <= 0) {
    return;
  }

  GPU_offscreen_bind(dst, /*read_buffer*/ true);
  GPU_matrix_push_projection();
  GPU_matrix_push();
  GPU_matrix_ortho_set(0.0f, float(w), 0.0f, float(h), -1.0f, 1.0f);
  GPU_matrix_identity_set();
  GPU_blend(blend);
  GPU_texture_filter_mode(tex, true);

  GPU_texture_bind(tex, 0);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint texcoord = GPU_vertformat_attr_add(
      format, "texCoord", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_IMAGE);
  immBegin(GPU_PRIM_TRI_FAN, 4);
  immAttr2f(texcoord, 0.0f, 0.0f);
  immVertex2f(pos, 0.0f, 0.0f);
  immAttr2f(texcoord, 1.0f, 0.0f);
  immVertex2f(pos, float(w), 0.0f);
  immAttr2f(texcoord, 1.0f, 1.0f);
  immVertex2f(pos, float(w), float(h));
  immAttr2f(texcoord, 0.0f, 1.0f);
  immVertex2f(pos, 0.0f, float(h));
  immEnd();
  immUnbindProgram();
  GPU_texture_unbind(tex);

  GPU_matrix_pop();
  GPU_matrix_pop_projection();
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Tokens
 * \{ */

/**
 * Design px, alphas explicit on every colour.
 *
 * A three-value initialiser zero-fills the fourth and the shape draws
 * invisible — the failure reads as "the button is missing", not as a colour
 * bug — so every entry spells its alpha out even when it is 0.
 *
 * These are the TRANSLUCENT variants and the material metrics; neither the
 * opaque design-system palette (`interface_mixar_palette.hh`) nor the island's
 * pane vocabulary (`agent_ui_pane_kit.hh`) carries an alpha ramp, a rim, a
 * sheen, a specular or a shadow, and a material cannot be assembled out of
 * opaque chips. The RGBs are those tables' colours where a pane has an opaque
 * counterpart: CARD and ISLAND take the agent surface's green ramp, MENU,
 * PANEL and CHAT the neutral dark surfaces, PILL the brand green with the
 * brightest rim in the family (it is the smallest pane, so the rim is most of
 * what identifies it), CHIP tint only, no gloss and no specular, so it can sit
 * on a pane without doubling its material.
 *
 * `PILL.radius` is deliberately larger than any pill: the painter clamps a
 * radius to half the short side, which is exactly the capsule rule, so one
 * number covers every pill height (the same 999 as the palette's
 * `MX_R_PILL`).
 */
const MixarGlassTokens g_glass_tokens[] = {
    /* MIXAR_GLASS_CARD */
    {
        /* tint_top      */ {0.196f, 0.357f, 0.200f, 0.72f},
        /* tint_bottom   */ {0.000f, 0.137f, 0.090f, 0.88f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.30f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.10f},
        /* rim           */ {0.294f, 0.596f, 0.376f, 0.55f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.16f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.40f},
        /* radius        */ 12.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 18.0f,
        /* shadow_width  */ 8.0f,
        /* sheen_height  */ 20.0f,
        /* specular_width*/ 26.0f,
        /* specular_alpha*/ 0.10f,
        /* specular_period*/ 6.0f,
    },
    /* MIXAR_GLASS_MENU */
    {
        /* tint_top      */ {0.086f, 0.086f, 0.090f, 0.88f},
        /* tint_bottom   */ {0.047f, 0.047f, 0.051f, 0.94f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.22f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.07f},
        /* rim           */ {0.255f, 0.255f, 0.255f, 0.45f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.10f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.45f},
        /* radius        */ 8.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 14.0f,
        /* shadow_width  */ 7.0f,
        /* sheen_height  */ 14.0f,
        /* specular_width*/ 18.0f,
        /* specular_alpha*/ 0.06f,
        /* specular_period*/ 7.0f,
    },
    /* MIXAR_GLASS_PANEL */
    {
        /* tint_top      */ {0.110f, 0.110f, 0.114f, 0.55f},
        /* tint_bottom   */ {0.071f, 0.071f, 0.075f, 0.62f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.18f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.06f},
        /* rim           */ {0.294f, 0.294f, 0.294f, 0.40f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.09f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.30f},
        /* radius        */ 10.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 24.0f,
        /* shadow_width  */ 9.0f,
        /* sheen_height  */ 16.0f,
        /* specular_width*/ 22.0f,
        /* specular_alpha*/ 0.06f,
        /* specular_period*/ 8.0f,
    },
    /* MIXAR_GLASS_ISLAND */
    {
        /* tint_top      */ {0.196f, 0.357f, 0.200f, 0.78f},
        /* tint_bottom   */ {0.000f, 0.137f, 0.090f, 0.90f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.28f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.09f},
        /* rim           */ {0.294f, 0.596f, 0.376f, 0.50f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.14f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.42f},
        /* radius        */ 14.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 16.0f,
        /* shadow_width  */ 10.0f,
        /* sheen_height  */ 22.0f,
        /* specular_width*/ 28.0f,
        /* specular_alpha*/ 0.09f,
        /* specular_period*/ 6.0f,
    },
    /* MIXAR_GLASS_PILL — radius clamped to half the short side, i.e. a capsule. */
    {
        /* tint_top      */ {0.196f, 0.357f, 0.200f, 0.86f},
        /* tint_bottom   */ {0.000f, 0.137f, 0.090f, 0.92f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.24f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.14f},
        /* rim           */ {0.000f, 1.000f, 0.549f, 0.65f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.20f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.38f},
        /* radius        */ 999.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 12.0f,
        /* shadow_width  */ 5.0f,
        /* sheen_height  */ 12.0f,
        /* specular_width*/ 14.0f,
        /* specular_alpha*/ 0.12f,
        /* specular_period*/ 5.0f,
    },
    /* MIXAR_GLASS_CHAT */
    {
        /* tint_top      */ {0.114f, 0.114f, 0.118f, 0.80f},
        /* tint_bottom   */ {0.071f, 0.071f, 0.075f, 0.88f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.20f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.07f},
        /* rim           */ {0.255f, 0.255f, 0.255f, 0.35f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.10f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.32f},
        /* radius        */ 10.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 16.0f,
        /* shadow_width  */ 7.0f,
        /* sheen_height  */ 16.0f,
        /* specular_width*/ 20.0f,
        /* specular_alpha*/ 0.07f,
        /* specular_period*/ 7.0f,
    },
    /* MIXAR_GLASS_CHIP — tint, rim and a whisper of gloss; no shadow, no
     * specular, because a chip sits ON a pane and may not cast its own. */
    {
        /* tint_top      */ {0.114f, 0.114f, 0.114f, 0.90f},
        /* tint_bottom   */ {0.114f, 0.114f, 0.114f, 0.90f},
        /* glaze         */ {0.000f, 0.000f, 0.000f, 0.00f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.05f},
        /* rim           */ {0.255f, 0.255f, 0.255f, 0.30f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.06f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.00f},
        /* radius        */ 8.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 8.0f,
        /* shadow_width  */ 0.0f,
        /* sheen_height  */ 8.0f,
        /* specular_width*/ 0.0f,
        /* specular_alpha*/ 0.00f,
        /* specular_period*/ 0.0f,
    },
};

static_assert(BLI_ARRAY_SIZE(g_glass_tokens) == size_t(MIXAR_GLASS_CHIP) + 1u,
              "Every role needs a row: the enum and the table are read together.");

/** \} */

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Public API
 * \{ */

MixarGlassTokens mixar_glass_tokens(const eMixarGlassRole role)
{
  const int index = std::clamp(int(role), 0, int(MIXAR_GLASS_CHIP));
  MixarGlassTokens tokens = g_glass_tokens[index];
  const float scale = UI_SCALE_FAC;
  tokens.radius *= scale;
  tokens.rim_width *= scale;
  tokens.blur_radius *= scale;
  tokens.shadow_width *= scale;
  tokens.sheen_height *= scale;
  tokens.specular_width *= scale;
  /* `specular_alpha` and `specular_period` are not lengths — one is an alpha,
   * the other is seconds — so the UI scale must not touch them. */
  return tokens;
}

MixarGlassBackdrop mixar_glass_backdrop_prepare(const MixarGlassSource &source,
                                                const float blur_radius)
{
  const MixarGlassBackdrop empty = {};
  if (!source.valid()) {
    return empty;
  }
  const int rect_w = BLI_rcti_size_x(&source.rect);
  const int rect_h = BLI_rcti_size_y(&source.rect);
  if (blur_radius <= 0.0f || rect_w < GLASS_BLUR_MIN_PX || rect_h < GLASS_BLUR_MIN_PX) {
    return empty;
  }

  /* Each halving doubles the effective kernel, so the level count follows the
   * radius; two levels is the floor, because one halving and a straight return
   * is a 2x2 box and nothing like a blur. */
  const int levels = std::clamp(1 + int(std::log2(std::max(blur_radius, 1.0f))),
                                2,
                                GLASS_BLUR_LEVELS);
  const int base_w = std::min(rect_w, GLASS_BLUR_MAX_BASE);
  const int base_h = std::max(1, int(float(rect_h) * float(base_w) / float(rect_w)));

  if (!glass_chain_ensure(base_w, base_h, levels)) {
    return empty;
  }

  /* The cascade is a full GPU pass inside someone else's region draw, so every
   * piece of state the pass touches is saved and handed back. */
  gpu::FrameBuffer *fb_prev = GPU_framebuffer_active_get();
  int viewport_prev[4];
  GPU_viewport_size_get_i(viewport_prev);
  int scissor_prev[4];
  GPU_scissor_get(scissor_prev);
  const GPUBlend blend_prev = GPU_blend_get();

  glass_blit_full(g_chain.levels[0], source.texture, GPU_BLEND_NONE);
  for (int i = 1; i < g_chain.level_count; i++) {
    glass_blit_full(
        g_chain.levels[i], GPU_offscreen_color_texture(g_chain.levels[i - 1]), GPU_BLEND_NONE);
  }
  /* Back up the chain, or the result is a grid of 2x2 blocks. Each upsample is
   * a bilinear read of a halved image, which is a wider and softer
   * reconstruction than the downsample that produced it; the two rounds
   * together are the blur. */
  for (int i = g_chain.level_count - 1; i > 0; i--) {
    glass_blit_full(
        g_chain.levels[i - 1], GPU_offscreen_color_texture(g_chain.levels[i]), GPU_BLEND_NONE);
  }

  GPU_offscreen_unbind(g_chain.levels[0], /*read_buffer*/ true);
  if (fb_prev != nullptr) {
    GPU_framebuffer_bind(fb_prev);
  }
  GPU_viewport(viewport_prev[0], viewport_prev[1], viewport_prev[2], viewport_prev[3]);
  GPU_scissor(scissor_prev[0], scissor_prev[1], scissor_prev[2], scissor_prev[3]);
  GPU_blend(blend_prev);

  return {GPU_offscreen_color_texture(g_chain.levels[0]), source.rect};
}

bool mixar_glass_window_apply_translucency(void *ghostwin, const bool enable)
{
#if defined(__APPLE__) || defined(_WIN32)
  if (ghostwin == nullptr) {
    return false;
  }
  Mixar_WindowSetBlurBehind(ghostwin, enable);
  return true;
#else
  /* No definition of the underlying call exists on this platform, so calling
   * it would be an undefined reference at link time. A window that cannot be
   * made translucent simply keeps drawing its own tint. */
  (void)ghostwin;
  (void)enable;
  return false;
#endif
}

void mixar_glass_free()
{
  glass_chain_release();
}

/** \} */

}  // namespace ui
}  // namespace blender
