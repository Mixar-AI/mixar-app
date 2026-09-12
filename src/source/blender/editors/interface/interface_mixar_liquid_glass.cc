/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar liquid glass: the blur and the window request behind
 * `ED_mixar_glass.hh`. Read that header first — it states what a pane is made
 * of and why the backdrop is a caller-supplied texture. The material table is
 * `interface_mixar_liquid_glass_tokens.cc`; the painter is
 * `interface_mixar_liquid_glass_draw.cc`.
 *
 * A bounded bilinear down/up cascade reuses offscreens between redraws.
 * Preserve framebuffer state even when allocation fails: creating an offscreen
 * binds and clears a framebuffer too. Each pass owns one balanced push/pop.
 */

#include <algorithm>
#include <cmath>

#include "BLI_math_base.h"
#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "GPU_framebuffer.hh"
#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_shader.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"
#include "GPU_viewport.hh"

#include "ED_mixar_glass.hh"

#if defined(__APPLE__) || defined(_WIN32)
/** Defined per platform in `intern/ghost` (Cocoa and Win32). Declared here
 * because this unit must not depend on a bubble header, and with C linkage to
 * match every other declaration of it in the tree. */
extern "C" bool Mixar_WindowSetBlurBehind(void *window_handle, bool enable);
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
/** Ceiling on both first-level dimensions. Levels 1..n are cheap (each is a
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
                                             /*with_depth_buffer*/ false,
                                             gpu::TextureFormat::UNORM_8_8_8_8,
                                             GPU_TEXTURE_USAGE_SHADER_READ,
                                             /*clear*/ true,
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

  GPU_offscreen_bind(dst, /*save*/ true);
  GPU_viewport(0, 0, w, h);
  GPU_scissor(0, 0, w, h);
  GPU_matrix_push_projection();
  GPU_matrix_push();
  GPU_matrix_ortho_set(0.0f, float(w), 0.0f, float(h), -1.0f, 1.0f);
  GPU_matrix_identity_set();
  GPU_blend(blend);
  GPUSamplerState sampler = GPUSamplerState::default_sampler();
  sampler.filtering = GPU_SAMPLER_FILTERING_LINEAR;
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint texcoord = GPU_vertformat_attr_add(
      format, "texCoord", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_IMAGE);
  immBindTextureSampler("image", tex, sampler);
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
  GPU_offscreen_unbind(dst, /*restore*/ true);
}

/** \} */

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Public API
 * \{ */

MixarGlassBackdrop mixar_glass_backdrop_prepare(const MixarGlassSource &source,
                                                const float blur_radius)
{
  const MixarGlassBackdrop empty = {};
  if (!source.valid()) {
    return empty;
  }
  const int rect_w = BLI_rcti_size_x(&source.rect);
  const int rect_h = BLI_rcti_size_y(&source.rect);
  if (!std::isfinite(blur_radius) || blur_radius <= 0.0f || rect_w < GLASS_BLUR_MIN_PX || rect_h < GLASS_BLUR_MIN_PX) {
    return empty;
  }

  /* Each halving doubles the effective kernel, so the level count follows the
   * radius; two levels is the floor, because one halving and a straight return
   * is a 2x2 box and nothing like a blur. */
  const int levels = std::clamp(1 + int(std::log2(std::max(blur_radius, 1.0f))),
                                2,
                                GLASS_BLUR_LEVELS);
  const float scale = std::min(1.0f, float(GLASS_BLUR_MAX_BASE) /
                                       float(std::max(rect_w, rect_h)));
  const int base_w = std::max(1, int(rect_w * scale));
  const int base_h = std::max(1, int(rect_h * scale));

  gpu::FrameBuffer *fb_prev = GPU_framebuffer_active_get();
  int viewport_prev[4], scissor_prev[4];
  GPU_viewport_size_get_i(viewport_prev);
  GPU_scissor_get(scissor_prev);
  const GPUBlend blend_prev = GPU_blend_get();
  const GPUDepthTest depth_prev = GPU_depth_test_get();
  const bool depth_mask_prev = GPU_depth_mask_get();
  const auto restore = [&]() {
    if (fb_prev != nullptr) {
      GPU_framebuffer_bind(fb_prev);
    }
    else {
      GPU_framebuffer_restore();
    }
    GPU_viewport(viewport_prev[0], viewport_prev[1], viewport_prev[2], viewport_prev[3]);
    GPU_scissor(scissor_prev[0], scissor_prev[1], scissor_prev[2], scissor_prev[3]);
    GPU_blend(blend_prev);
    GPU_depth_test(depth_prev);
    GPU_depth_mask(depth_mask_prev);
  };
  if (!glass_chain_ensure(base_w, base_h, levels)) {
    restore();
    return empty;
  }
  GPU_depth_test(GPU_DEPTH_NONE);
  GPU_depth_mask(false);

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

  restore();

  return {GPU_offscreen_color_texture(g_chain.levels[0]), source.rect};
}

bool mixar_glass_window_apply_translucency(void *ghostwin, const bool enable)
{
#if defined(__APPLE__) || defined(_WIN32)
  if (ghostwin == nullptr) {
    return false;
  }
  return Mixar_WindowSetBlurBehind(ghostwin, enable);
#else
  /* No definition of the underlying call exists on this platform, so calling
   * it would be an undefined reference at link time. A window that cannot be
   * made translucent simply keeps drawing its own tint. */
  (void)ghostwin;
  (void)enable;
  return false;
#endif
}

void mixar_glass_shader_free();

void mixar_glass_free()
{
  glass_chain_release();
  mixar_glass_shader_free();
}

/** \} */

}  // namespace ui
}  // namespace blender
