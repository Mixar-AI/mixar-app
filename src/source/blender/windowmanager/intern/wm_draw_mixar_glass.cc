/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup wm
 *
 * Windows DWM cannot reliably frost the parent's OpenGL/Vulkan viewport. Keep
 * that completed host framebuffer on the GPU and composite its blurred pixels
 * under the island's premultiplied UI. The final window pixels are opaque, so
 * this works even when DWM accepts alpha setup but presents an opaque surface.
 */

#include "wm_draw_mixar_glass.hh"

#ifdef WIN32

#  include "wm_draw_mixar_glass_sync.hh"

#  include <map>

#  include "BKE_screen.hh"
#  include "BLI_listbase.h"
#  include "DNA_screen_types.h"
#  include "DNA_space_enums.h"
#  include "DNA_windowmanager_types.h"
#  include "ED_mixar_glass.hh"
#  include "ED_space_api.hh"
#  include "GHOST_IWindow.hh"
#  include "GHOST_Rect.hh"
#  include "GPU_context.hh"
#  include "GPU_framebuffer.hh"
#  include "GPU_immediate.hh"
#  include "GPU_matrix.hh"
#  include "GPU_state.hh"
#  include "GPU_texture.hh"
#  include "WM_api.hh"

extern "C" bool Mixar_WindowIsVisible(void *window_handle);

namespace blender {
namespace {

struct HostBackdrop {
  GPUOffScreen *capture = nullptr;
  gpu::Texture *blurred = nullptr;
};

/* FBOs remain in their host context. Only textures cross window contexts.
 * A file load can replace wmWindow while retaining its GPU context. Key these
 * resources by that stable identity so its eventual teardown releases them. */
std::map<GPUContext *, HostBackdrop> host_backdrops;
std::map<GPUContext *, GHOST_Rect> consumer_bounds;
MixarGlassSync glass_sync;

GPUContext *window_context(const wmWindow *win)
{
  return win != nullptr ? static_cast<GPUContext *>(win->runtime->gpuctx) : nullptr;
}

bool is_glass_window(const wmWindow *win)
{
  const bScreen *screen = WM_window_get_active_screen(win);
  if (screen == nullptr) {
    return false;
  }
  for (const ScrArea &area : screen->areabase) {
    if (area.spacetype == SPACE_AGENT_BUBBLE) {
      return true;
    }
  }
  return false;
}

bool is_visible(const wmWindow *win)
{
  const auto *ghost = static_cast<GHOST_IWindow *>(win->runtime->ghostwin);
  return ghost != nullptr && ghost->getState() != GHOST_kWindowStateMinimized &&
         Mixar_WindowIsVisible(win->runtime->ghostwin);
}

wmWindow *host_window(wmWindowManager *wm, wmWindow *win)
{
  if (is_glass_window(win)) {
    /* An existing island can be natively reparented to another main window
     * without changing Blender's original window hierarchy. */
    wmWindow *host = ED_agent_bubble_host_window_get(wm);
    if (host != nullptr && !is_glass_window(host)) {
      return host;
    }
  }
  /* The status pill can be a child of the island rather than the viewport. */
  while (win->parent != nullptr) {
    win = win->parent;
  }
  return is_glass_window(win) ? nullptr : win;
}

GHOST_Rect client_bounds(const wmWindow *win)
{
  GHOST_Rect bounds;
  static_cast<GHOST_IWindow *>(win->runtime->ghostwin)->getClientBounds(bounds);
  return bounds;
}

void release_backdrop(HostBackdrop &backdrop)
{
  if (backdrop.capture != nullptr) {
    GPU_offscreen_free(backdrop.capture);
  }
  if (backdrop.blurred != nullptr) {
    GPU_texture_free(backdrop.blurred);
  }
  backdrop = {};
}

bool has_consumers(wmWindowManager *wm, wmWindow *host, const bool tag_redraw)
{
  bool found = false;
  for (wmWindow &win : wm->windows) {
    if (&win != host && is_glass_window(&win) && is_visible(&win) &&
        host_window(wm, &win) == host)
    {
      found = true;
      if (tag_redraw) {
        WM_window_get_active_screen(&win)->do_draw = true;
      }
    }
  }
  return found;
}

void capture_host(wmWindowManager *wm, wmWindow *win)
{
  if (!has_consumers(wm, win, false)) {
    return;
  }
  const int2 size = WM_window_native_pixel_size(win);
  if (size.x <= 0 || size.y <= 0) {
    return;
  }
  /* Order shared blur scratch and every previous texture reader, including
   * consumers that have since switched hosts or become hidden. */
  glass_sync.wait();
  HostBackdrop &backdrop = host_backdrops[window_context(win)];
  gpu::FrameBuffer *window_fb = GPU_framebuffer_active_get();
  int viewport[4], scissor[4];
  GPU_viewport_size_get_i(viewport);
  GPU_scissor_get(scissor);

  if (backdrop.capture != nullptr &&
      (GPU_offscreen_width(backdrop.capture) != size.x ||
       GPU_offscreen_height(backdrop.capture) != size.y))
  {
    release_backdrop(backdrop);
  }
  if (backdrop.capture == nullptr) {
    backdrop.capture = GPU_offscreen_create(size.x,
                                            size.y,
                                            false,
                                            gpu::TextureFormat::UNORM_8_8_8_8,
                                            GPU_TEXTURE_USAGE_SHADER_READ,
                                            false,
                                            nullptr);
  }
  if (backdrop.capture != nullptr) {
    gpu::FrameBuffer *capture_fb;
    gpu::Texture *capture_texture, *depth_texture;
    GPU_offscreen_viewport_data_get(
        backdrop.capture, &capture_fb, &capture_texture, &depth_texture);
    GPU_scissor(0, 0, size.x, size.y);
    GPU_framebuffer_blit(window_fb, 0, capture_fb, 0, GPU_COLOR_BIT);
    GPU_framebuffer_bind(window_fb);

    ui::MixarGlassSource source;
    source.texture = capture_texture;
    source.width = size.x;
    source.height = size.y;
    source.rect = {0, size.x, 0, size.y};
    const ui::MixarGlassBackdrop blurred = ui::mixar_glass_backdrop_prepare(source, 16.0f);
    if (blurred.valid()) {
      const int width = GPU_texture_width(blurred.texture);
      const int height = GPU_texture_height(blurred.texture);
      if (backdrop.blurred != nullptr &&
          (GPU_texture_width(backdrop.blurred) != width ||
           GPU_texture_height(backdrop.blurred) != height))
      {
        GPU_texture_free(backdrop.blurred);
        backdrop.blurred = nullptr;
      }
      if (backdrop.blurred == nullptr) {
        backdrop.blurred = GPU_texture_create_2d("Mixar host frost",
                                                 width,
                                                 height,
                                                 1,
                                                 gpu::TextureFormat::UNORM_8_8_8_8,
                                                 GPU_TEXTURE_USAGE_GENERAL,
                                                 nullptr);
      }
      if (backdrop.blurred != nullptr) {
        /* The blur kit's texture is scratch space. Retain this host's result. */
        GPU_texture_copy(backdrop.blurred, blurred.texture);
        has_consumers(wm, win, true);
      }
    }
  }
  GPU_framebuffer_bind(window_fb);
  GPU_viewport(viewport[0], viewport[1], viewport[2], viewport[3]);
  GPU_scissor(scissor[0], scissor[1], scissor[2], scissor[3]);
  /* Publish even a failed capture: allocation/blur may have submitted work. */
  glass_sync.signal();
}

void draw_solid(const int2 size, const float value)
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4f(value, value, value, 1.0f);
  immRectf(pos, 0.0f, 0.0f, float(size.x), float(size.y));
  immUnbindProgram();
}

void composite_backdrop(wmWindowManager *wm, wmWindow *win)
{
  wmWindow *host = host_window(wm, win);
  const auto found = host_backdrops.find(window_context(host));
  gpu::Texture *texture = found == host_backdrops.end() ? nullptr : found->second.blurred;
  if (texture != nullptr) {
    glass_sync.wait();
  }
  const int2 size = WM_window_native_pixel_size(win);
  const GPUBlend blend = GPU_blend_get();
  const GPUDepthTest depth = GPU_depth_test_get();
  const GPUWriteMask write_mask = GPU_write_mask_get();
  int viewport[4], scissor[4];
  GPU_viewport_size_get_i(viewport);
  GPU_scissor_get(scissor);
  GPU_viewport(0, 0, size.x, size.y);
  GPU_scissor(0, 0, size.x, size.y);
  GPU_matrix_push();
  GPU_matrix_push_projection();
  GPU_matrix_identity_set();
  GPU_matrix_ortho_set(0.0f, float(size.x), 0.0f, float(size.y), -1.0f, 1.0f);
  GPU_depth_test(GPU_DEPTH_NONE);
  GPU_depth_mask(false);
  GPU_color_mask(true, true, true, true);
  GPU_blend(GPU_BLEND_ALPHA_UNDER_PREMUL);

  if (texture != nullptr && host != nullptr && host->runtime->ghostwin != nullptr) {
    const GHOST_Rect host_rect = client_bounds(host);
    const GHOST_Rect rect = client_bounds(win);
    const float host_width = float(host_rect.getWidth());
    const float host_height = float(host_rect.getHeight());
    if (host_width > 0.0f && host_height > 0.0f) {
      /* Native bounds are physical desktop pixels with a top-left origin.
       * UVs are bottom-left. Ratios also handle different monitor DPI scales. */
      const float u0 = float(rect.l_ - host_rect.l_) / host_width;
      const float u1 = float(rect.r_ - host_rect.l_) / host_width;
      const float v0 = float(host_rect.b_ - rect.b_) / host_height;
      const float v1 = float(host_rect.b_ - rect.t_) / host_height;
      GPUVertFormat *format = immVertexFormat();
      const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
      const uint uv = GPU_vertformat_attr_add(format, "texCoord", gpu::VertAttrType::SFLOAT_32_32);
      GPUSamplerState sampler = GPUSamplerState::default_sampler();
      sampler.filtering = GPU_SAMPLER_FILTERING_LINEAR;
      immBindBuiltinProgram(GPU_SHADER_3D_IMAGE);
      immBindTextureSampler("image", texture, sampler);
      immBegin(GPU_PRIM_TRI_FAN, 4);
      immAttr2f(uv, u0, v0);
      immVertex2f(pos, 0.0f, 0.0f);
      immAttr2f(uv, u1, v0);
      immVertex2f(pos, float(size.x), 0.0f);
      immAttr2f(uv, u1, v1);
      immVertex2f(pos, float(size.x), float(size.y));
      immAttr2f(uv, u0, v1);
      immVertex2f(pos, 0.0f, float(size.y));
      immEnd();
      immUnbindProgram();
      GPU_texture_unbind(texture);
    }
  }
  /* Fill any missing host/alpha with charcoal; preserve already drawn UI. */
  draw_solid(size, 0.07f);
  /* Native rounded HWND regions clip the exterior. Interior presents opaque
   * regardless of the parent framebuffer's alpha convention. */
  GPU_blend(GPU_BLEND_NONE);
  GPU_color_mask(false, false, false, true);
  draw_solid(size, 0.0f);
  if (texture != nullptr) {
    glass_sync.signal();
  }

  GPU_matrix_pop_projection();
  GPU_matrix_pop();
  GPU_write_mask(write_mask);
  GPU_depth_test(depth);
  GPU_blend(blend);
  GPU_viewport(viewport[0], viewport[1], viewport[2], viewport[3]);
  GPU_scissor(scissor[0], scissor[1], scissor[2], scissor[3]);
}

}  // namespace

void wm_draw_mixar_glass_update(wmWindowManager *wm)
{
  for (wmWindow &win : wm->windows) {
    if (!is_glass_window(&win) || !is_visible(&win)) {
      consumer_bounds.erase(window_context(&win));
      continue;
    }
    wmWindow *host = host_window(wm, &win);
    if (host == nullptr || !is_visible(host)) {
      continue;
    }
    const auto capture = host_backdrops.find(window_context(host));
    if (capture == host_backdrops.end() || capture->second.blurred == nullptr) {
      WM_window_get_active_screen(host)->do_draw = true;
    }
    const GHOST_Rect current = client_bounds(&win);
    const auto old = consumer_bounds.find(window_context(&win));
    if (old == consumer_bounds.end()) {
      /* The host may have changed while every glass window was hidden. */
      WM_window_get_active_screen(host)->do_draw = true;
    }
    if (old == consumer_bounds.end() || old->second.l_ != current.l_ ||
        old->second.t_ != current.t_ || old->second.r_ != current.r_ ||
        old->second.b_ != current.b_)
    {
      consumer_bounds[window_context(&win)] = current;
      WM_window_get_active_screen(&win)->do_draw = true;
    }
  }
}

void wm_draw_mixar_glass(wmWindowManager *wm, wmWindow *win)
{
  if (is_glass_window(win)) {
    composite_backdrop(wm, win);
  }
  else {
    capture_host(wm, win);
  }
}

void wm_draw_mixar_glass_free(wmWindow *win)
{
  /* Teardown participates in the same chain before freeing shared textures. */
  glass_sync.wait();
  consumer_bounds.erase(window_context(win));
  const auto found = host_backdrops.find(window_context(win));
  if (found != host_backdrops.end()) {
    release_backdrop(found->second);
    host_backdrops.erase(found);
    /* The shared blur scratch also owns FBOs in this context. Drop it before
     * that context dies; other live hosts retain their own blurred textures. */
    ui::mixar_glass_free();
  }
  if (!host_backdrops.empty()) {
    /* Carry the dependency to surviving contexts; the last host drains it. */
    glass_sync.signal();
  }
}

}  // namespace blender

#else

namespace blender {
void wm_draw_mixar_glass_update(wmWindowManager * /*wm*/) {}
void wm_draw_mixar_glass(wmWindowManager * /*wm*/, wmWindow * /*win*/) {}
void wm_draw_mixar_glass_free(wmWindow * /*win*/) {}
}  // namespace blender

#endif
