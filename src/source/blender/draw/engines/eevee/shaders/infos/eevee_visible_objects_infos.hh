/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */
#include "gpu_shader_create_info.hh"

GPU_SHADER_CREATE_INFO(eevee_visible_objects_reduce)
LOCAL_GROUP_SIZE(16, 16)
PUSH_CONSTANT(int, padding)
PUSH_CONSTANT(int2, extent)
PUSH_CONSTANT(int, resource_count)
SAMPLER(0, sampler2D, object_sample_tx)
STORAGE_BUF(0, read_write, uint, object_hits[])
COMPUTE_SOURCE("eevee_visible_objects_reduce_comp.glsl")
DO_STATIC_COMPILATION()
GPU_SHADER_CREATE_END()
