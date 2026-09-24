/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include "BLI_assert.h"
#include "GPU_state.hh"

namespace blender {

/** Order glass reads, writes and teardown across native window command streams.
 * Each operation consumes the previous signal and publishes its own. A single
 * chain also carries a host's writes to BOTH consumers on single-use backends.
 * Explicitly drain it before the last host context is discarded, never from a
 * static destructor after GPU shutdown. */
class MixarGlassSync {
 private:
  GPUFence *pending_ = nullptr;

 public:
  MixarGlassSync() = default;
  MixarGlassSync(const MixarGlassSync &) = delete;
  MixarGlassSync &operator=(const MixarGlassSync &) = delete;

  void wait()
  {
    if (pending_ != nullptr) {
      GPU_fence_wait(pending_);
      GPU_fence_free(pending_);
      pending_ = nullptr;
    }
  }

  void signal()
  {
    BLI_assert(pending_ == nullptr);
    pending_ = GPU_fence_create();
    GPU_fence_signal(pending_);
    GPU_flush();
  }
};

}  // namespace blender
