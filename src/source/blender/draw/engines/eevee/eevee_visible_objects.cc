/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "eevee_visible_objects.hh"
#include "eevee_instance.hh"
#include "RE_engine.h"
#include "DEG_depsgraph_query.hh"
#include "DNA_material_types.h"
#include "GPU_compute.hh"
#include "GPU_shader.hh"

namespace blender::eevee {
VisibleObjects::~VisibleObjects()
{
  if (shader_) {
    GPU_shader_free(shader_);
  }
}

void VisibleObjects::begin_sync()
{
  /* Resource indices can change on a motion-blur re-sync. Resolve before replacing the map. */
  read_result();
  enabled_ = inst_.render && RE_mixar_visibility_enabled(inst_.render->re);
  sampled_ = false;
  objects_.clear();
}

void VisibleObjects::sync_object(Object *object, draw::ResourceHandleRange handle)
{
  if (!enabled_ || object->type != OB_MESH) {
    return;
  }
  Object *original = reinterpret_cast<Object *>(DEG_get_original_id(&object->id));
  const draw::ResourceIndexRange range = handle;
  const uint32_t first = range.first.resource_index();
  if (first + range.count > (1u << 24)) {
    RE_mixar_visibility_fail(inst_.render->re, "Too many draw resources for visibility capture");
    enabled_ = false;
    return;
  }
  for (uint32_t i = 0; i < range.count; i++) {
    objects_.insert_or_assign(first + i,
                              MixarVisibleObject{original->id.session_uid, original->id.name + 2});
  }
}

void VisibleObjects::sync_material(const ::Material *material)
{
  if (enabled_ && material && material->surface_render_method == MA_SURFACE_METHOD_FORWARD) {
    RE_mixar_visibility_fail(inst_.render->re,
                             "Visibility capture requires Dithered surface rendering; "
                             "Blended materials are not supported yet");
    enabled_ = false;
  }
}

void VisibleObjects::end_sync()
{
  if (!enabled_) {
    return;
  }
  if (!hits_) {
    hits_ = std::make_unique<draw::StorageArrayBuffer<uint32_t, 16>>("VisibleObjects");
  }
  const uint32_t count = objects_.empty() ? 1 : objects_.rbegin()->first + 1;
  hits_->resize(count);
  hits_->clear_to_zero();
}

void VisibleObjects::accumulate()
{
  if (!enabled_) {
    return;
  }
  if (!shader_) {
    shader_ = GPU_shader_create_from_info_name("eevee_visible_objects_reduce");
  }
  if (!shader_) {
    RE_mixar_visibility_fail(inst_.render->re, "Could not compile visibility capture shader");
    enabled_ = false;
    return;
  }
  const int padding = inst_.film.render_overscan_get();
  const int2 extent = inst_.film.render_extent_get() - int2(2 * padding);
  GPU_memory_barrier(GPU_BARRIER_TEXTURE_FETCH | GPU_BARRIER_SHADER_IMAGE_ACCESS);
  GPU_shader_bind(shader_);
  GPU_shader_uniform_1i(shader_, "padding", padding);
  GPU_shader_uniform_2iv(shader_, "extent", &extent.x);
  GPU_shader_uniform_1i(shader_, "resource_count", int(hits_->size()));
  GPU_texture_bind(inst_.render_buffers.cryptomatte_tx, 0);
  GPU_storagebuf_bind(*hits_, 0);
  GPU_compute_dispatch(shader_, (extent.x + 15) / 16, (extent.y + 15) / 16, 1);
  GPU_memory_barrier(GPU_BARRIER_SHADER_STORAGE | GPU_BARRIER_BUFFER_UPDATE);
  sampled_ = true;
  RE_mixar_visibility_sample(inst_.render->re);
}

void VisibleObjects::read_result()
{
  if (!enabled_ || !sampled_ || !hits_) {
    return;
  }
  hits_->read();
  for (const auto &[resource, object] : objects_) {
    if ((*hits_)[resource]) {
      RE_mixar_visibility_add(inst_.render->re, object);
    }
  }
  sampled_ = false;
}
}  // namespace blender::eevee
