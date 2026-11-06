/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup wm
 *
 * Mixar: a blurred, dimmed window behind a modal pop-up (the Export sheet,
 * `WindowManager.mixar_invoke_modal_dialog(blur=True)`).
 *
 * A pop-up holds the blur for its window, keyed by its own data like the
 * floating-dock holds (`wm_mixar_modal_dialog.cc`): every close path frees
 * that data, and a release only undoes a hold that exists.
 *
 * On the first frame with a hold, the window's areas draw into an offscreen
 * of the window's size instead of the window (the stereo side-by-side path
 * draws a whole window into an offscreen the same way), so nothing is read
 * back from the window's own framebuffer. That capture is blurred once with
 * the liquid-glass kit (downsampled to at most 1024 px, so cheap) and kept;
 * every later frame skips the areas entirely and lays the kept blur and a
 * dark scrim under the pop-up. Only a window resize re-captures. The blur
 * therefore costs one capture per opening and makes every hover redraw of
 * the pop-up cheaper than a normal frame, at the price of a backdrop frozen
 * at the moment the pop-up opened — which is what a modal backdrop is.
 */

#include <map>
#include <optional>

#include "BKE_global.hh"
#include "BKE_main.hh"
#include "BKE_screen.hh"

#include "BLI_listbase_iterator.hh"
#include "BLI_map.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_mixar_glass.hh"

#include "GPU_context.hh"
#include "GPU_framebuffer.hh"
#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"

#include "WM_api.hh"
#include "WM_mixar.hh"
#include "WM_stall_monitor.hh"

#include "wm_draw_mixar_backdrop.hh"

namespace blender {

namespace {

/** Backdrop blur in px (the glass kit's scale: the island's host frost uses 16). */
constexpr float BLUR_RADIUS = 28.0f;
/** Black scrim over the blur, so the pop-up's card reads as the one surface. */
constexpr float SCRIM_ALPHA = 0.38f;

struct Hold {
  const wmWindow *win = nullptr;
  int winid = 0;
};

Map<const void *, Hold> &holds()
{
  static Map<const void *, Hold> map;
  return map;
}

struct Kept {
  gpu::Texture *blurred = nullptr;
  int2 size = {0, 0};
};

/* Textures cross contexts; key by the window's context, which survives a file
 * load replacing its wmWindow (as the host frost does). */
std::map<GPUContext *, Kept> &kept_blurs()
{
  static std::map<GPUContext *, Kept> map;
  return map;
}

/* Alive between a Capture `begin` and its `end` within one window draw. */
GPUOffScreen *g_capture = nullptr;

GPUContext *window_context(const wmWindow *win)
{
  return win != nullptr ? static_cast<GPUContext *>(win->runtime->gpuctx) : nullptr;
}

bool held(const wmWindow *win)
{
  for (const Hold &hold : holds().values()) {
    if (hold.win == win && hold.winid == win->winid) {
      return true;
    }
  }
  return false;
}

void release_kept(const wmWindow *win)
{
  auto found = kept_blurs().find(window_context(win));
  if (found == kept_blurs().end()) {
    return;
  }
  if (found->second.blurred != nullptr) {
    GPU_texture_free(found->second.blurred);
  }
  kept_blurs().erase(found);
}

/** A full-window quad in window px; `texture` null draws `color`. */
void draw_window_quad(const int2 size, gpu::Texture *texture, const float color[4])
{
  GPU_matrix_push();
  GPU_matrix_push_projection();
  GPU_matrix_identity_set();
  GPU_matrix_ortho_set(0.0f, float(size.x), 0.0f, float(size.y), -1.0f, 1.0f);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  if (texture != nullptr) {
    const uint uv = GPU_vertformat_attr_add(format, "texCoord", gpu::VertAttrType::SFLOAT_32_32);
    GPUSamplerState sampler = GPUSamplerState::default_sampler();
    sampler.filtering = GPU_SAMPLER_FILTERING_LINEAR;
    immBindBuiltinProgram(GPU_SHADER_3D_IMAGE);
    immBindTextureSampler("image", texture, sampler);
    immBegin(GPU_PRIM_TRI_FAN, 4);
    immAttr2f(uv, 0.0f, 0.0f);
    immVertex2f(pos, 0.0f, 0.0f);
    immAttr2f(uv, 1.0f, 0.0f);
    immVertex2f(pos, float(size.x), 0.0f);
    immAttr2f(uv, 1.0f, 1.0f);
    immVertex2f(pos, float(size.x), float(size.y));
    immAttr2f(uv, 0.0f, 1.0f);
    immVertex2f(pos, 0.0f, float(size.y));
    immEnd();
    immUnbindProgram();
    GPU_texture_unbind(texture);
  }
  else {
    immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
    immUniformColor4fv(color);
    immRectf(pos, 0.0f, 0.0f, float(size.x), float(size.y));
    immUnbindProgram();
  }
  GPU_matrix_pop_projection();
  GPU_matrix_pop();
}

/** Blur the capture into a texture this window keeps; null on failure. */
gpu::Texture *blur_capture(GPUOffScreen *capture, const int2 size)
{
  /* The kit's chain is shared scratch. Rebuild it in this window's context
   * (a second main window must not reuse another context's framebuffers) and
   * drop it afterwards: nothing else needs it while the pop-up is up. */
  ui::mixar_glass_free();
  ui::MixarGlassSource source;
  source.texture = GPU_offscreen_color_texture(capture);
  source.width = size.x;
  source.height = size.y;
  source.rect = {0, size.x, 0, size.y};
  const ui::MixarGlassBackdrop blurred = ui::mixar_glass_backdrop_prepare(source, BLUR_RADIUS);
  gpu::Texture *kept = nullptr;
  if (blurred.valid()) {
    kept = GPU_texture_create_2d("Mixar pop-up backdrop",
                                 GPU_texture_width(blurred.texture),
                                 GPU_texture_height(blurred.texture),
                                 1,
                                 gpu::TextureFormat::UNORM_8_8_8_8,
                                 GPU_TEXTURE_USAGE_GENERAL,
                                 nullptr);
    if (kept != nullptr) {
      /* The kit's texture is scratch space; retain our own copy. */
      GPU_texture_copy(kept, blurred.texture);
    }
  }
  ui::mixar_glass_free();
  return kept;
}

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Holds (WM_mixar.hh)
 * \{ */

void Mixar_backdrop_blur_hold(wmWindow *win, const void *owner)
{
  if (win == nullptr || owner == nullptr) {
    return;
  }
  holds().add_overwrite(owner, Hold{win, win->winid});
  if (bScreen *screen = WM_window_get_active_screen(win)) {
    screen->do_draw = true;
  }
}

void Mixar_backdrop_blur_release(const void *owner)
{
  const std::optional<Hold> hold = holds().pop_try(owner);
  if (!hold || G_MAIN == nullptr) {
    return;
  }
  /* The window may have gone with the pop-up (a file load): only touch it
   * while it is still one of the manager's windows. */
  wmWindowManager *wm = static_cast<wmWindowManager *>(G_MAIN->wm.first);
  if (wm == nullptr) {
    return;
  }
  for (wmWindow &win : wm->windows) {
    if (&win == hold->win && win.winid == hold->winid) {
      if (bScreen *screen = WM_window_get_active_screen(&win)) {
        screen->do_draw = true;
      }
    }
  }
}

bool Mixar_backdrop_blur_held(const wmWindow *win)
{
  return win != nullptr && held(win);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Window draw
 * \{ */

MixarBackdropPass wm_draw_mixar_backdrop_begin(wmWindow *win, const int view)
{
  if (!held(win)) {
    /* Released (or never held): give the window's memory back. */
    release_kept(win);
    return MixarBackdropPass::None;
  }
  if (view != -1) {
    return MixarBackdropPass::None;
  }
  const int2 size = WM_window_native_pixel_size(win);
  if (size.x <= 0 || size.y <= 0) {
    return MixarBackdropPass::None;
  }
  auto found = kept_blurs().find(window_context(win));
  if (found != kept_blurs().end() && found->second.blurred != nullptr &&
      found->second.size == size)
  {
    return MixarBackdropPass::Cached;
  }
  /* A resize (or a first frame): capture again. */
  release_kept(win);
  BLI_assert(g_capture == nullptr);
  g_capture = GPU_offscreen_create(size.x,
                                   size.y,
                                   false,
                                   gpu::TextureFormat::UNORM_8_8_8_8,
                                   GPU_TEXTURE_USAGE_SHADER_READ,
                                   false,
                                   nullptr);
  if (g_capture == nullptr) {
    return MixarBackdropPass::None;
  }
  GPU_offscreen_bind(g_capture, true);
  wmWindowViewport(win);
  GPU_clear_color(0.0f, 0.0f, 0.0f, 1.0f);
  return MixarBackdropPass::Capture;
}

void wm_draw_mixar_backdrop_end(wmWindow *win, const MixarBackdropPass pass)
{
  if (pass == MixarBackdropPass::None) {
    return;
  }
  Mixar_StallScope stall_scope("draw", "mixar_popup_backdrop");
  const int2 size = WM_window_native_pixel_size(win);
  const GPUBlend blend = GPU_blend_get();
  const GPUDepthTest depth = GPU_depth_test_get();
  GPU_depth_test(GPU_DEPTH_NONE);

  gpu::Texture *backdrop = nullptr;
  if (pass == MixarBackdropPass::Capture) {
    GPU_offscreen_unbind(g_capture, true);
    wmWindowViewport(win);
    gpu::Texture *blurred = blur_capture(g_capture, size);
    if (blurred != nullptr) {
      kept_blurs()[window_context(win)] = Kept{blurred, size};
      backdrop = blurred;
    }
    else {
      /* No blur: still put the areas on screen, unblurred under the scrim. */
      backdrop = GPU_offscreen_color_texture(g_capture);
    }
  }
  else {
    backdrop = kept_blurs()[window_context(win)].blurred;
  }

  wmWindowViewport(win);
  if (backdrop != nullptr) {
    GPU_blend(GPU_BLEND_NONE);
    draw_window_quad(size, backdrop, nullptr);
  }
  const float scrim[4] = {0.0f, 0.0f, 0.0f, SCRIM_ALPHA};
  GPU_blend(GPU_BLEND_ALPHA);
  draw_window_quad(size, nullptr, scrim);

  if (g_capture != nullptr) {
    GPU_offscreen_free(g_capture);
    g_capture = nullptr;
  }
  GPU_blend(blend);
  GPU_depth_test(depth);
  wmWindowViewport(win);
}

void wm_draw_mixar_backdrop_free(wmWindow *win)
{
  release_kept(win);
}

/** \} */

}  // namespace blender
