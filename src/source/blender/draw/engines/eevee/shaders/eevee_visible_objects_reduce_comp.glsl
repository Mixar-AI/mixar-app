/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */
#include "infos/eevee_visible_objects_infos.hh"
COMPUTE_SHADER_CREATE_INFO(eevee_visible_objects_reduce)

void main()
{
  int2 pixel = int2(gl_GlobalInvocationID.xy);
  if (any(greaterThanEqual(pixel, extent))) {
    return;
  }
  /* The otherwise-unused raw Cryptomatte alpha stores an exact draw resource integer.
   * Zero means background/holdout. No name hashes or retained-layer limits are involved. */
  uint object_index = uint(texelFetch(object_sample_tx, pixel + int2(padding), 0).w);
  if (object_index > 0u && object_index < uint(resource_count)) {
    atomicOr(object_hits[object_index], 1u);
  }
}
