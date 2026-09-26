/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Scene-card thumbnails for the Scenes drawer: each tab's scene rendered
 * natively into a small offscreen, the same flow the workspace viewer uses
 * (`view3d_workspace_viewer_render.cc`): fit the evaluated geometry from a
 * fixed three-quarter view, solid or material shading after the host view,
 * helper lights/cameras/empties hidden. Rendering an off-window scene here is
 * immune to the pin races a screenshot would have: the scene is passed in.
 *
 * Renders are throttled per card and skipped while the depsgraph has not
 * changed, so an idle drawer costs one textured quad per card per redraw and
 * nothing else.
 *
 * The render runs from a timer-driven operator, outside any window frame, and
 * the card draws in a later frame. Blitting the render's GPU texture across
 * that gap came up black on Metal from the second render of a card on (the
 * first was fine, `--debug` hid it, and no amount of `GPU_finish` helped), so
 * the render is read back to memory right after it finishes and the draw pass
 * uploads it into a texture of its own — Blender's own out-of-frame renders
 * (`ED_view3d_draw_offscreen_imbuf`) read back the same way.
 */

#include <algorithm>
#include <cmath>

#include "BLI_bounds.hh"
#include "BLI_math_geom.h"
#include "BLI_math_matrix.h"
#include "BLI_math_matrix.hh"
#include "BLI_listbase_iterator.hh"
#include "BLI_math_rotation.h"
#include "BLI_rect.h"
#include "BLI_time.h"

#include "BKE_context.hh"
#include "BKE_main.hh"
#include "BKE_object.hh"
#include "BKE_scene.hh"
#include "BKE_screen.hh"

#include "DEG_depsgraph.hh"
#include "DEG_depsgraph_query.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_view3d_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"
#include "ED_view3d_offscreen.hh"

#include "GPU_framebuffer.hh"
#include "GPU_immediate.hh"
#include "GPU_shader_builtin.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"

#include "WM_api.hh"
#include "WM_mixar.hh"

#include "view3d_director_minimap.hh"
#include "view3d_scenes_drawer.hh"

namespace blender {

static WorldExtents thumb_extents(Depsgraph *depsgraph)
{
  std::optional<Bounds<float3>> world;
  DEGObjectIterSettings settings{};
  settings.depsgraph = depsgraph;
  settings.flags = DEG_OBJECT_ITER_FOR_RENDER_ENGINE_FLAGS;
  DEG_OBJECT_ITER_BEGIN (&settings, object) {
    if (MINIMAP_HIDDEN_TYPES & (1 << object->type)) {
      continue;
    }
    if (const auto local = BKE_object_boundbox_get(object)) {
      const auto transformed = bounds::transform_bounds(object->object_to_world(), *local);
      if (world) {
        world->min = math::min(world->min, transformed.min);
        world->max = math::max(world->max, transformed.max);
      }
      else {
        world = transformed;
      }
    }
  }
  DEG_OBJECT_ITER_END;
  WorldExtents result;
  if (world) {
    result.any = true;
    BLI_rctf_init(&result.xy, world->min.x, world->max.x, world->min.y, world->max.y);
    result.zmin = world->min.z;
    result.zmax = world->max.z;
  }
  return result;
}

void view3d_scenes_drawer_thumb_free(ScenesDrawerThumb &t)
{
  if (t.offscreen) {
    GPU_offscreen_free(t.offscreen);
  }
  if (t.texture) {
    GPU_texture_free(t.texture);
  }
  t.offscreen = nullptr;
  t.texture = nullptr;
  t.pixels.clear();
  t.pixels_w = t.pixels_h = 0;
  t.pixels_dirty = false;
  t.has_render = false;
}

void view3d_scenes_drawer_thumb_render(ScenesDrawerThumb &t,
                                       Main *bmain,
                                       const wmWindowManager *wm,
                                       Scene *scene,
                                       const View3D *host,
                                       const int w,
                                       const int h,
                                       const double min_interval)
{
  if (!scene || !bmain || w < 8 || h < 8 || ED_view3d_draw_offscreen_check_nested()) {
    return;
  }
  /* Called from a timer-driven operator, which on macOS and Windows can run
   * inside the OS resize callback; a viewport render there is the crash
   * CLAUDE.md's resize rule describes. Keep the previous thumbnail. */
  if (Mixar_window_resize_dispatch_active()) {
    return;
  }
  ViewLayer *layer = static_cast<ViewLayer *>(scene->view_layers.first);
  Depsgraph *deps = layer ? BKE_scene_ensure_depsgraph(bmain, scene, layer) : nullptr;
  if (!deps) {
    return;
  }
  /* A tab that is not on screen is evaluated by nobody: a workspace rebuild
   * (Zen <-> Engine mode) or a routed script leaves its depsgraph tagged and
   * its card would stay blank. Evaluate it here — operator context, never the
   * draw callback (the same rule the workspace viewer follows) — unless a
   * window shows it, in which case the event loop already does. */
  bool visible_elsewhere = false;
  if (wm) {
    for (const wmWindow &window : wm->windows) {
      visible_elsewhere |= WM_window_get_active_scene(&window) == scene;
    }
  }
  if (!visible_elsewhere && (DEG_id_type_any_updated(deps) || DEG_get_update_count(deps) == 0)) {
    BKE_scene_graph_update_tagged(deps, bmain);
  }
  if (DEG_get_update_count(deps) == 0 || !DEG_is_fully_evaluated(deps)) {
    /* Still not drawable (workbench's SceneState::init dereferences a
     * half-evaluated graph): the card keeps its last thumbnail. */
    return;
  }
  const eDrawType type = (host && host->shading.type >= OB_MATERIAL) ? OB_MATERIAL : OB_SOLID;
  if (t.offscreen && (GPU_offscreen_width(t.offscreen) != w || GPU_offscreen_height(t.offscreen) != h)) {
    view3d_scenes_drawer_thumb_free(t);
  }
  if (t.has_render && t.update_count == DEG_get_update_count(deps) && t.draw_type == type) {
    return;
  }
  const double now = BLI_time_now_seconds();
  if (t.has_render && now - t.last_render_time < min_interval) {
    return;
  }
  if (!t.offscreen) {
    char error[256] = {};
    t.offscreen = GPU_offscreen_create(w, h, true, gpu::TextureFormat::UNORM_8_8_8_8,
                                       GPU_TEXTURE_USAGE_SHADER_READ, false, error);
    if (!t.offscreen) {
      t.render_failed = true;
      return;
    }
  }
  const WorldExtents bounds = thumb_extents(deps);
  const float cx = bounds.any ? BLI_rctf_cent_x(&bounds.xy) : 0;
  const float cy = bounds.any ? BLI_rctf_cent_y(&bounds.xy) : 0;
  const float cz = bounds.any ? (bounds.zmin + bounds.zmax) * 0.5f : 0;
  const float sx = bounds.any ? BLI_rctf_size_x(&bounds.xy) : 6;
  const float sy = bounds.any ? BLI_rctf_size_y(&bounds.xy) : 6;
  const float sz = bounds.any ? bounds.zmax - bounds.zmin : 6;
  const float radius = std::max(1.0f, std::sqrt(sx * sx + sy * sy + sz * sz) * 0.5f);
  const float half_h = radius * 1.12f * std::max(1.0f, float(h) / w);
  const float half_w = half_h * float(w) / h;
  const float distance = radius * 4 + 10;
  float qx[4], qz[4], q[4], view[4][4], projection[4][4];
  axis_angle_to_quat_single(qx, 'X', DEG2RADF(-65.0f));
  axis_angle_to_quat_single(qz, 'Z', DEG2RADF(30.0f));
  mul_qt_qtqt(q, qx, qz);
  quat_to_mat4(view, q);
  view[3][2] -= distance;
  translate_m4(view, -cx, -cy, -cz);
  const float clip_end = distance + radius * 4 + 10;
  orthographic_m4(projection, -half_w, half_w, -half_h, half_h, 0.01f, clip_end);
  View3DShading shading;
  BKE_screen_view3d_shading_init(&shading);
  shading.type = type;
  shading.light = V3D_LIGHTING_STUDIO;
  shading.color_type = V3D_SHADING_MATERIAL_COLOR;
  gpu::FrameBuffer *framebuffer = GPU_framebuffer_active_get();
  int viewport[4], scissor[4];
  GPU_viewport_size_get_i(viewport);
  GPU_scissor_get(scissor);
  /* The offscreen scene draw leaves depth testing, depth writes and face
   * culling as the engines set them; the card's pill, name and glyphs drawn
   * after it in the same frame are flat 2D and were dropped by the depth
   * test on the frames a thumbnail rendered. Restore the region's state. */
  const GPUDepthTest depth_test = GPU_depth_test_get();
  const bool depth_mask = GPU_depth_mask_get();
  const GPUFaceCullTest face_cull = GPU_face_culling_get();
  GPU_offscreen_bind(t.offscreen, true);
  /* A temporary GPUViewport per render (DRW makes and frees it), display
   * colour space and overlays merged, so the offscreen holds the finished
   * picture and nothing survives between renders but the offscreen itself. */
  ED_view3d_draw_offscreen_simple(deps, scene, &shading, nullptr, type, MINIMAP_HIDDEN_TYPES, 0, w, h,
                                  V3D_OFSDRAW_SHOW_GRIDFLOOR, view, projection, 0.01f, clip_end, 0,
                                  false, true, true, nullptr, true, nullptr, t.offscreen, nullptr);
  /* Read the picture back while the offscreen is still bound (the read waits
   * for the render): a few thousand pixels, throttled by `min_interval`. */
  t.pixels.resize(size_t(w) * size_t(h) * 4);
  GPU_offscreen_read_color(t.offscreen, GPU_DATA_UBYTE, t.pixels.data());
  t.pixels_w = w;
  t.pixels_h = h;
  t.pixels_dirty = true;
  GPU_offscreen_unbind(t.offscreen, true);
  if (framebuffer) {
    GPU_framebuffer_bind(framebuffer);
  }
  GPU_viewport(viewport[0], viewport[1], viewport[2], viewport[3]);
  GPU_scissor(scissor[0], scissor[1], scissor[2], scissor[3]);
  GPU_depth_test(depth_test);
  GPU_depth_mask(depth_mask);
  GPU_face_culling(face_cull);
  GPU_blend(GPU_BLEND_ALPHA);
  t.has_render = true;
  t.render_failed = false;
  t.update_count = DEG_get_update_count(deps);
  t.draw_type = type;
  t.last_render_time = now;
}

void view3d_scenes_drawer_thumb_draw(ScenesDrawerThumb &t, const rcti &rect)
{
  if (!t.has_render || t.pixels.empty()) {
    return;
  }
  if (t.texture && (GPU_texture_width(t.texture) != t.pixels_w ||
                    GPU_texture_height(t.texture) != t.pixels_h))
  {
    GPU_texture_free(t.texture);
    t.texture = nullptr;
  }
  if (!t.texture) {
    t.texture = GPU_texture_create_2d("scenes_drawer_thumb", t.pixels_w, t.pixels_h, 1,
                                      gpu::TextureFormat::UNORM_8_8_8_8,
                                      GPU_TEXTURE_USAGE_SHADER_READ, nullptr);
    if (!t.texture) {
      return;
    }
    t.pixels_dirty = true;
  }
  if (t.pixels_dirty) {
    GPU_texture_update(t.texture, GPU_DATA_UBYTE, t.pixels.data());
    t.pixels_dirty = false;
  }
  /* The render is already in display space and opaque (background drawn). */
  GPU_blend(GPU_BLEND_NONE);
  GPUSamplerState sampler = GPUSamplerState::default_sampler();
  sampler.filtering = GPU_SAMPLER_FILTERING_LINEAR;
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint texco = GPU_vertformat_attr_add(format, "texCoord", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_IMAGE);
  immBindTextureSampler("image", t.texture, sampler);
  immBegin(GPU_PRIM_TRI_FAN, 4);
  immAttr2f(texco, 0.0f, 0.0f);
  immVertex2f(pos, float(rect.xmin), float(rect.ymin));
  immAttr2f(texco, 1.0f, 0.0f);
  immVertex2f(pos, float(rect.xmax + 1), float(rect.ymin));
  immAttr2f(texco, 1.0f, 1.0f);
  immVertex2f(pos, float(rect.xmax + 1), float(rect.ymax + 1));
  immAttr2f(texco, 0.0f, 1.0f);
  immVertex2f(pos, float(rect.xmin), float(rect.ymax + 1));
  immEnd();
  immUnbindProgram();
  GPU_texture_unbind(t.texture);
  GPU_blend(GPU_BLEND_ALPHA);
}

}  // namespace blender
