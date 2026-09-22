/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/* Model four independent GPU command streams and single-use fence semantics.
 * Waiting transfers only the signalling stream's dependencies, not a global
 * CPU completion: skipping a second consumer's wait must fail this test. */
#include <algorithm>
#include <cassert>

#include "wm_draw_mixar_glass_sync.hh"

namespace blender {
struct GPUFence {
  int sequence = 0;
  bool pending = false;
  bool flushed = false;
};

static int context, sequence, streams[4], live, created, waited, freed;
static GPUFence *unflushed;

GPUFence *GPU_fence_create()
{
  assert(++live == 1); /* Storage stays bounded while the host is idle. */
  ++created;
  return new GPUFence;
}
void GPU_fence_signal(GPUFence *fence)
{
  assert(!fence->pending && unflushed == nullptr);
  fence->sequence = streams[context];
  fence->pending = true;
  unflushed = fence;
}
void GPU_flush()
{
  assert(unflushed != nullptr);
  unflushed->flushed = true;
  unflushed = nullptr;
}
void GPU_fence_wait(GPUFence *fence)
{
  assert(fence->pending && fence->flushed);
  streams[context] = std::max(streams[context], fence->sequence);
  fence->pending = false;
  ++waited;
}
void GPU_fence_free(GPUFence *fence)
{
  assert(!fence->pending);
  --live;
  ++freed;
  delete fence;
}

/* Every access must follow all previous shared reads/writes, even after a
 * host switch, failed capture, or deletion of a different native window. */
static void access()
{
  assert(streams[context] == sequence);
  streams[context] = ++sequence;
}
}  // namespace blender

int main()
{
  using namespace blender;
  MixarGlassSync sync;
  auto operation = [&](int window) {
    context = window;
    sync.wait();
    access();
    sync.signal();
  };
  sync.wait(); /* Empty initial state and repeated empty drains are safe. */
  sync.wait();
  operation(0); /* Host capture. */
  for (int i = 0; i < 100; ++i) {
    operation(1); /* Island animation while the host remains idle. */
  }
  operation(2); /* Pill must inherit the host write through the island. */
  for (int i = 0; i < 100; ++i) {
    operation(2);
  }
  operation(0); /* Host write follows every recent consumer read. */
  for (int i = 0; i < 100; ++i) {
    operation(0); /* Repeated captures with no consumer redraw. */
  }
  for (int i = 0; i < 100; ++i) {
    operation(3); /* Another host reuses the shared blur scratch. */
    operation(1); /* Island reparented to that host. */
    operation(2); /* Alternate consumers in independent contexts. */
    operation(0); /* Original host resizes or capture allocation fails. */
  }
  operation(3); /* Teardown of one host forwards dependencies to survivors. */
  operation(2); /* Consumer teardown. */
  operation(0);
  context = 0;
  sync.wait(); /* Last host drains before GPU shutdown. */
  access();
  sync.wait();
  assert(live == 0 && created == waited && waited == freed);
  operation(0); /* Recreated context starts a fresh chain. */
  operation(1);
  sync.wait();
  assert(live == 0 && created == waited && waited == freed);
}
