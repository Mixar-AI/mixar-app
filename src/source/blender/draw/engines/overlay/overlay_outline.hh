/* SPDX-FileCopyrightText: 2024 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup overlay
 */

#pragma once

#include "overlay_base.hh"
#include "overlay_grease_pencil.hh"

#include "draw_common.hh"

#include "DNA_userdef_types.h"

namespace blender::draw::overlay {

/**
 * Display selected object outline.
 * The option can be found under (Viewport Overlays > Objects > Outline Selected).
 */
class Outline : Overlay {
 private:
  /* Simple render pass that renders an object ID pass. */
  PassMain outline_prepass_ps_ = {"Prepass"};
  PassMain::Sub *prepass_curves_ps_ = nullptr;
  PassMain::Sub *prepass_pointcloud_ps_ = nullptr;
  PassMain::Sub *prepass_gpencil_ps_ = nullptr;
  PassMain::Sub *prepass_mesh_ps_ = nullptr;
  PassMain::Sub *prepass_volume_ps_ = nullptr;
  PassMain::Sub *prepass_wire_ps_ = nullptr;
  /* MIXAR: parallel sub-passes for selection-suggestion ghost outlines —
   * identical shaders with is_suggested=true, which emits outline category
   * 2u (unused upstream) so the resolve shader colors them differently. */
  PassMain::Sub *prepass_curves_suggested_ps_ = nullptr;
  PassMain::Sub *prepass_pointcloud_suggested_ps_ = nullptr;
  PassMain::Sub *prepass_gpencil_suggested_ps_ = nullptr;
  PassMain::Sub *prepass_mesh_suggested_ps_ = nullptr;
  PassMain::Sub *prepass_volume_suggested_ps_ = nullptr;
  PassMain::Sub *prepass_wire_suggested_ps_ = nullptr;
  /* Detect edges inside the ID pass and output color for each of them. */
  PassSimple outline_resolve_ps_ = {"Resolve"};

  TextureFromPool object_id_tx_ = {"outline_ob_id_tx"};
  TextureFromPool tmp_depth_tx_ = {"outline_depth_tx"};

  Framebuffer prepass_fb_ = {"outline.prepass_fb"};

  Vector<FlatObjectRef> flat_objects_;

  PassMain outline_prepass_flat_ps_ = {"PrepassFlat"};

 public:
  void begin_sync(Resources &res, const State &state) final
  {
    enabled_ = !res.is_selection();
    enabled_ &= state.v3d && (state.v3d_flag & V3D_SELECT_OUTLINE);

    flat_objects_.clear();

    if (!enabled_) {
      return;
    }

    const float outline_width = UI_GetThemeValuef(TH_OUTLINE_WIDTH);
    const bool do_smooth_lines = (U.gpu_flag & USER_GPU_FLAG_OVERLAY_SMOOTH_WIRE) != 0;
    const bool do_expand = (U.pixelsize > 1.0) || (outline_width > 2.0f);
    const bool is_transform = (G.moving & G_TRANSFORM_OBJ) != 0;

    {
      auto &pass = outline_prepass_ps_;
      pass.init();
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
      pass.framebuffer_set(&prepass_fb_);
      pass.clear_color_depth_stencil(float4(0.0f), 1.0f, 0x0);
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_WRITE_DEPTH | DRW_STATE_DEPTH_LESS_EQUAL,
                     state.clipping_plane_count);
      /* MIXAR: each geometry type gets a base sub-pass and a "suggested"
       * twin (is_suggested=true -> ghost outline category). */
      auto make_sub = [&](const char *name, auto *shader, bool suggested) {
        auto &sub = pass.sub(name);
        sub.shader_set(shader);
        sub.push_constant("is_transform", is_transform);
        sub.push_constant("is_suggested", suggested);
        return &sub;
      };
      prepass_curves_ps_ = make_sub("Curves", res.shaders->outline_prepass_curves.get(), false);
      prepass_curves_suggested_ps_ = make_sub(
          "CurvesSuggested", res.shaders->outline_prepass_curves.get(), true);
      prepass_pointcloud_ps_ = make_sub(
          "PointCloud", res.shaders->outline_prepass_pointcloud.get(), false);
      prepass_pointcloud_suggested_ps_ = make_sub(
          "PointCloudSuggested", res.shaders->outline_prepass_pointcloud.get(), true);
      prepass_gpencil_ps_ = make_sub(
          "GreasePencil", res.shaders->outline_prepass_gpencil.get(), false);
      prepass_gpencil_suggested_ps_ = make_sub(
          "GreasePencilSuggested", res.shaders->outline_prepass_gpencil.get(), true);
      prepass_mesh_ps_ = make_sub("Mesh", res.shaders->outline_prepass_mesh.get(), false);
      prepass_mesh_suggested_ps_ = make_sub(
          "MeshSuggested", res.shaders->outline_prepass_mesh.get(), true);
      prepass_volume_ps_ = make_sub("Volume", res.shaders->outline_prepass_mesh.get(), false);
      prepass_volume_suggested_ps_ = make_sub(
          "VolumeSuggested", res.shaders->outline_prepass_mesh.get(), true);
      prepass_wire_ps_ = make_sub("Wire", res.shaders->outline_prepass_wire.get(), false);
      prepass_wire_suggested_ps_ = make_sub(
          "WireSuggested", res.shaders->outline_prepass_wire.get(), true);
    }
    {
      auto &pass = outline_resolve_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_BLEND_ALPHA_PREMUL);
      pass.shader_set(res.shaders->outline_detect.get());
      /* Don't occlude the outline if in xray mode as it causes too much flickering. */
      pass.push_constant("alpha_occlu", state.xray_enabled ? 1.0f : 0.35f);
      pass.push_constant("do_thick_outlines", do_expand);
      pass.push_constant("do_anti_aliasing", do_smooth_lines);
      pass.push_constant("is_xray_wires", state.xray_enabled_and_not_wire);
      /* MIXAR: ghost color for suggested-selection outlines (category 2u).
       * Matches the agent halo green (agent_viewport_lock/constants.py). */
      pass.push_constant("suggested_color", float4(0.290f, 0.870f, 0.502f, 1.0f));
      pass.bind_texture("outline_id_tx", &object_id_tx_);
      pass.bind_texture("scene_depth_tx", &res.depth_tx);
      pass.bind_texture("outline_depth_tx", &tmp_depth_tx_);
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
      pass.draw_procedural(GPU_PRIM_TRIS, 1, 3);
    }
  }

  void object_sync(Manager &manager,
                   const ObjectRef &ob_ref,
                   Resources &res,
                   const State &state) final
  {
    object_sync_ex(manager, ob_ref, res, state, false);
  }

  /* MIXAR: *is_suggested* routes the object into the ghost-outline twin
   * sub-passes (selection-suggestion preview) instead of the regular
   * selected-outline ones. */
  void object_sync_ex(Manager &manager,
                      const ObjectRef &ob_ref,
                      Resources &res,
                      const State &state,
                      const bool is_suggested)
  {
    if (!enabled_) {
      return;
    }

    /* Outlines of bounding boxes are not drawn. */
    if (ob_ref.object->dt == OB_BOUNDBOX) {
      return;
    }

    PassMain::Sub *curves_ps = is_suggested ? prepass_curves_suggested_ps_ : prepass_curves_ps_;
    PassMain::Sub *pointcloud_ps = is_suggested ? prepass_pointcloud_suggested_ps_ :
                                                  prepass_pointcloud_ps_;
    PassMain::Sub *gpencil_ps = is_suggested ? prepass_gpencil_suggested_ps_ :
                                               prepass_gpencil_ps_;
    PassMain::Sub *mesh_ps = is_suggested ? prepass_mesh_suggested_ps_ : prepass_mesh_ps_;
    PassMain::Sub *volume_ps = is_suggested ? prepass_volume_suggested_ps_ : prepass_volume_ps_;
    PassMain::Sub *wire_ps = is_suggested ? prepass_wire_suggested_ps_ : prepass_wire_ps_;

    gpu::Batch *geom;
    switch (ob_ref.object->type) {
      case OB_CURVES: {
        const char *error = nullptr;
        /* The error string will always have been printed by the engine already.
         * No need to display it twice. */
        geom = curves_sub_pass_setup(*curves_ps, state.scene, ob_ref.object, error);
        curves_ps->draw(geom, manager.unique_handle(ob_ref));
        break;
      }
      case OB_GREASE_PENCIL:
        GreasePencil::draw_grease_pencil(
            res, *gpencil_ps, state.scene, ob_ref.object, manager.unique_handle(ob_ref));
        break;
      case OB_MESH:
        if (state.xray_enabled_and_not_wire) {
          geom = DRW_cache_mesh_edge_detection_get(ob_ref.object, nullptr);
          wire_ps->draw_expand(geom, GPU_PRIM_LINES, 1, 1, manager.unique_handle(ob_ref));
        }
        else {
          geom = DRW_cache_mesh_surface_get(ob_ref.object);
          mesh_ps->draw(geom, manager.unique_handle(ob_ref));

          /* Display flat object as a line when view is orthogonal to them.
           * This fixes only the biggest case which is a plane in ortho view.
           * MIXAR: skipped for suggested objects — the flat pass has a single
           * category push constant and the edge case is cosmetic. */
          if (!is_suggested) {
            int flat_axis = FlatObjectRef::flat_axis_index_get(ob_ref.object);
            if (flat_axis != -1) {
              geom = DRW_cache_mesh_edge_detection_get(ob_ref.object, nullptr);
              flat_objects_.append({geom, manager.unique_handle(ob_ref), flat_axis});
            }
          }
        }
        break;
      case OB_POINTCLOUD:
        /* Looks bad in wireframe mode. Could be relaxed if we draw a wireframe of some sort in
         * the future. */
        if (!state.is_wireframe_mode) {
          geom = pointcloud_sub_pass_setup(*pointcloud_ps, ob_ref.object);
          pointcloud_ps->draw(geom, manager.unique_handle(ob_ref));
        }
        break;
      case OB_VOLUME:
        geom = DRW_cache_volume_selection_surface_get(ob_ref.object);
        /* TODO(fclem): Get rid of these check and enforce correct API on the batch cache. */
        if (geom) {
          volume_ps->draw(geom, manager.unique_handle(ob_ref));
        }
        break;
      default:
        break;
    }
  }

  /* Flat objects outline workaround need to generate passes for each redraw. */
  void flat_objects_pass_sync(Manager &manager, View &view, Resources &res, const State &state)
  {
    outline_prepass_flat_ps_.init();

    if (!enabled_) {
      return;
    }

    if (!view.is_persp()) {
      const bool is_transform = (G.moving & G_TRANSFORM_OBJ) != 0;
      /* Note: We need a dedicated pass since we have to populated it for each redraw. */
      auto &pass = outline_prepass_flat_ps_;
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
      pass.framebuffer_set(&prepass_fb_);
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_WRITE_DEPTH | DRW_STATE_DEPTH_LESS_EQUAL,
                     state.clipping_plane_count);
      pass.shader_set(res.shaders->outline_prepass_wire.get());
      pass.push_constant("is_transform", is_transform);
      /* MIXAR: flat workaround only carries non-suggested objects. */
      pass.push_constant("is_suggested", false);

      for (FlatObjectRef flag_ob_ref : flat_objects_) {
        flag_ob_ref.if_flat_axis_orthogonal_to_view(
            manager, view, [&](gpu::Batch *geom, ResourceIndex resource_index) {
              pass.draw_expand(geom, GPU_PRIM_LINES, 1, 1, resource_index);
            });
      }
    }
  }

  void pre_draw(Manager &manager, View &view) final
  {
    if (!enabled_) {
      return;
    }

    manager.generate_commands(outline_prepass_ps_, view);
    manager.generate_commands(outline_prepass_flat_ps_, view);
  }

  /* TODO(fclem): Remove dependency on Resources. */
  void draw_line_only_ex(Framebuffer &framebuffer, Resources &res, Manager &manager, View &view)
  {
    if (!enabled_) {
      return;
    }

    GPU_debug_group_begin("Outline");

    int2 render_size = int2(res.depth_tx.size());

    eGPUTextureUsage usage = GPU_TEXTURE_USAGE_SHADER_READ | GPU_TEXTURE_USAGE_ATTACHMENT;
    tmp_depth_tx_.acquire(render_size, gpu::TextureFormat::SFLOAT_32_DEPTH_UINT_8, usage);
    object_id_tx_.acquire(render_size, gpu::TextureFormat::UINT_16, usage);

    prepass_fb_.ensure(GPU_ATTACHMENT_TEXTURE(tmp_depth_tx_),
                       GPU_ATTACHMENT_TEXTURE(object_id_tx_));

    manager.submit_only(outline_prepass_ps_, view);
    manager.submit_only(outline_prepass_flat_ps_, view);

    GPU_framebuffer_bind(framebuffer);
    manager.submit(outline_resolve_ps_, view);

    tmp_depth_tx_.release();
    object_id_tx_.release();

    GPU_debug_group_end();
  }
};

}  // namespace blender::draw::overlay
