/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "GHOST_Types.hh"
#include <cassert>
int main() {
  static_assert((GHOST_gpuTransparent & GHOST_gpuNoHWRaytracing) == 0);
  GHOST_GPUSettings settings{};
  settings.flags = GHOST_gpuTransparent | GHOST_gpuNoHWRaytracing | GHOST_gpuVSyncIsOverridden;
  settings.vsync = GHOST_kVSyncModeOn;
  GHOST_ContextParams params = GHOST_CONTEXT_PARAMS_FROM_GPU_SETTINGS(settings);
  assert(params.use_alpha && params.no_hw_rt && params.vsync == GHOST_kVSyncModeOn);
  GHOST_ContextParams offscreen = GHOST_CONTEXT_PARAMS_FROM_GPU_SETTINGS_OFFSCREEN(settings);
  assert(!offscreen.use_alpha && offscreen.no_hw_rt);
  GHOST_ContextParams defaults = GHOST_CONTEXT_PARAMS_NONE;
  assert(!defaults.use_alpha && !defaults.no_hw_rt && defaults.vsync == GHOST_kVSyncModeUnset);
}
