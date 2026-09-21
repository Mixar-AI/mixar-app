/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include <algorithm>
#include <cmath>
#include "BLI_bounds.hh"
#include "BLI_math_matrix.hh"
#include "BLI_math_geom.h"
#include "BLI_time.h"
#include "BLI_math_matrix.h"
#include "BLI_math_rotation.h"
#include "BKE_context.hh"
#include "BKE_object.hh"
#include "BKE_scene.hh"
#include "BKE_screen.hh"
#include "DEG_depsgraph.hh"
#include "DEG_depsgraph_query.hh"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_view3d_types.h"
#include "ED_screen.hh"
#include "ED_view3d_offscreen.hh"
#include "GPU_framebuffer.hh"
#include "GPU_state.hh"
#include "GPU_viewport.hh"
#include "view3d_director_minimap.hh"
#include "view3d_workspace_viewer.hh"

namespace blender {
static WorldExtents workspace_extents(Depsgraph *depsgraph)
{
  std::optional<Bounds<float3>> world;
  DEGObjectIterSettings settings{};
  settings.depsgraph = depsgraph;
  /* Collection and geometry-node instances have no mesh bounds on their
   * instancer. Measure the same evaluated instances that the renderer draws. */
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

void view3d_workspace_viewer_gpu_free(WorkspaceViewer &v)
{
  if (v.viewport) { GPU_viewport_free(v.viewport); }
  if (v.offscreen) { GPU_offscreen_free(v.offscreen); }
  v.viewport = nullptr;
  v.offscreen = nullptr;
  v.has_render = false;
}

void view3d_workspace_viewer_render(const bContext * /*C*/, WorkspaceViewer &v, Scene *scene)
{
  const int w = BLI_rcti_size_x(&v.image) + 1, h = BLI_rcti_size_y(&v.image) + 1;
  if (!scene || w < 8 || h < 8 || ED_view3d_draw_offscreen_check_nested()) { return; }
  ViewLayer *layer = static_cast<ViewLayer *>(scene->view_layers.first);
  Depsgraph *deps = layer ? BKE_scene_get_depsgraph(scene, layer) : nullptr;
  if (!deps || DEG_get_update_count(deps) == 0) { return; }
  const View3D *host = static_cast<View3D *>(v.area->spacedata.first);
  const eDrawType type = host->shading.type >= OB_MATERIAL ? OB_MATERIAL : OB_SOLID;
  if (v.offscreen && (GPU_offscreen_width(v.offscreen) != w || GPU_offscreen_height(v.offscreen) != h)) {
    view3d_workspace_viewer_gpu_free(v);
  }
  if (v.has_render && v.update_count == DEG_get_update_count(deps) && v.draw_type == type) { return; }
  const double now = BLI_time_now_seconds();
  if (v.has_render && now - v.last_render_time < 0.1) { return; }
  if (!v.offscreen) {
    char error[256] = {};
    v.offscreen = GPU_offscreen_create(w, h, true, gpu::TextureFormat::UNORM_8_8_8_8,
                                       GPU_TEXTURE_USAGE_SHADER_READ, false, error);
    if (!v.offscreen) { v.render_failed = true; return; }
    v.viewport = GPU_viewport_create();
    if (!v.viewport) { view3d_workspace_viewer_gpu_free(v); v.render_failed = true; return; }
  }
  // Same offscreen flow as develop's scene tiles. Fit the evaluated geometry,
  // excluding helper lights/cameras, so new objects stay visible as the agent builds.
  const WorldExtents bounds = workspace_extents(deps);
  const float cx = bounds.any ? BLI_rctf_cent_x(&bounds.xy) : 0;
  const float cy = bounds.any ? BLI_rctf_cent_y(&bounds.xy) : 0;
  const float cz = bounds.any ? (bounds.zmin + bounds.zmax) * 0.5f : 0;
  const float sx = bounds.any ? BLI_rctf_size_x(&bounds.xy) : 6;
  const float sy = bounds.any ? BLI_rctf_size_y(&bounds.xy) : 6;
  const float sz = bounds.any ? bounds.zmax - bounds.zmin : 6;
  const float radius = std::max(1.0f, std::sqrt(sx*sx + sy*sy + sz*sz) * 0.5f);
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
  GPU_offscreen_bind(v.offscreen, true);
  ED_view3d_draw_offscreen_simple(deps, scene, &shading, nullptr, type,
                                  MINIMAP_HIDDEN_TYPES, 0, w, h,
                                  V3D_OFSDRAW_SHOW_GRIDFLOOR, view, projection,
                                  0.01f, clip_end, 0, false, true, true, nullptr,
                                  false, nullptr, v.offscreen, v.viewport);
  GPU_offscreen_unbind(v.offscreen, true);
  if (framebuffer) { GPU_framebuffer_bind(framebuffer); }
  GPU_viewport(viewport[0], viewport[1], viewport[2], viewport[3]);
  GPU_scissor(scissor[0], scissor[1], scissor[2], scissor[3]);
  ED_region_pixelspace(v.region);
  GPU_blend(GPU_BLEND_ALPHA);
  v.has_render = true;
  v.render_failed = false;
  v.update_count = DEG_get_update_count(deps);
  v.draw_type = type;
  v.frame_count++;
  v.last_render_time = now;
}
}  // namespace blender
