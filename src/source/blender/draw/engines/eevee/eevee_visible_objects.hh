/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

#include <map>
#include <memory>
#include "DRW_gpu_wrapper.hh"
#include "RE_mixar_visibility.hh"
#include "draw_handle.hh"

struct Material;

namespace blender::eevee {
class Instance;

/** Reduce camera sample IDs before Cryptomatte's finite per-pixel accumulation. */
class VisibleObjects {
  Instance &inst_;
  bool enabled_ = false;
  bool sampled_ = false;
  std::map<uint32_t, MixarVisibleObject> objects_;
  std::unique_ptr<draw::StorageArrayBuffer<uint32_t, 16>> hits_;
  gpu::Shader *shader_ = nullptr;

 public:
  explicit VisibleObjects(Instance &inst) : inst_(inst) {}
  ~VisibleObjects();
  bool enabled() const { return enabled_; }
  void begin_sync();
  void sync_object(Object *object, draw::ResourceHandleRange handle);
  void sync_material(const ::Material *material);
  void end_sync();
  void accumulate();
  void read_result();
};
}  // namespace blender::eevee
