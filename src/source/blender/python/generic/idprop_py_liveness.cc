/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup pygen
 *
 * Mixar: see `idprop_py_liveness.hh` (mixar-backend#2031).
 *
 * The release hook runs for every IDProperty struct Blender frees, on any thread (evaluated
 * copies are freed by depsgraph workers). It returns after one atomic load while no wrapper is
 * tracked. Otherwise a mutex guards the map; wrappers are tracked and untracked with the GIL
 * held, and a slot is only ever cleared, never dereferenced, by the hook.
 */

#include <atomic>
#include <mutex>
#include <unordered_map>

#include "BKE_idprop_mixar.hh"

#include "idprop_py_liveness.hh"

namespace blender {

namespace {

struct Registry {
  std::mutex mutex;
  /** Property address -> wrapper fields currently holding it. */
  std::unordered_multimap<const IDProperty *, IDProperty **> slots;
};

std::atomic<size_t> tracked_num{0};

Registry &registry()
{
  /* Never destroyed: the hook may still run while the process exits. */
  static Registry *instance = new Registry();
  return *instance;
}

void release_listener(const IDProperty *prop)
{
  if (tracked_num.load(std::memory_order_acquire) == 0) {
    return;
  }
  Registry &reg = registry();
  std::scoped_lock lock(reg.mutex);
  auto [first, last] = reg.slots.equal_range(prop);
  if (first == last) {
    return;
  }
  size_t cleared = 0;
  for (auto it = first; it != last; ++it) {
    *it->second = nullptr;
    cleared++;
  }
  reg.slots.erase(first, last);
  tracked_num.fetch_sub(cleared, std::memory_order_release);
}

}  // namespace

void BPy_IDProperty_liveness_init()
{
  BKE_idprop_mixar_release_listener_set(release_listener);
}

void BPy_IDProperty_liveness_track(IDProperty **slot)
{
  Registry &reg = registry();
  std::scoped_lock lock(reg.mutex);
  if (*slot == nullptr) {
    return;
  }
  reg.slots.emplace(*slot, slot);
  tracked_num.fetch_add(1, std::memory_order_release);
}

void BPy_IDProperty_liveness_untrack(IDProperty **slot)
{
  Registry &reg = registry();
  std::scoped_lock lock(reg.mutex);
  if (*slot == nullptr) {
    /* Already cleared (and erased) by the release hook. */
    return;
  }
  auto [first, last] = reg.slots.equal_range(*slot);
  for (auto it = first; it != last; ++it) {
    if (it->second == slot) {
      reg.slots.erase(it);
      tracked_num.fetch_sub(1, std::memory_order_release);
      return;
    }
  }
}

PyObject *BPy_IDProperty_raise_removed()
{
  PyErr_SetString(PyExc_ReferenceError,
                  "IDProperty has been removed (its group was deleted, replaced, popped or "
                  "cleared); look it up again from its owner");
  return nullptr;
}

}  // namespace blender
