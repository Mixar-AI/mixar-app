/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup wm
 *
 * Main-thread stall monitor. `WM_main` times each of its four phases per
 * iteration; an iteration longer than the threshold is written as one JSON
 * line to `<user config>/mixar/stalls.jsonl` with the phase split and the
 * longest breadcrumbs that ran inside it. Breadcrumbs are RAII scopes that
 * known heavy entry points (operators, Python timers and handlers, region
 * draws, job callbacks, autosave, depsgraph) open around their work, so a
 * record names the operator or Python function that held the loop instead of
 * only the phase.
 *
 * Environment:
 * - `MIXAR_STALL_THRESHOLD_MS` (default 100): iterations at or above are logged.
 * - `MIXAR_STALL_LOG`: log path override, `off` disables the file.
 * - `MIXAR_STALL_PRINT=1` (or `--debug-wm`): also print each record to stdout.
 * - `MIXAR_STALL_STACK_MS` (default 500): the Python watchdog's stack-capture threshold.
 *
 * Every entry point is main-thread only; scopes opened from other threads
 * (render-thread `bpy.app.handlers`) are ignored.
 */

#pragma once

#include <cstdint>

namespace blender {

struct bContext;

enum Mixar_StallPhase {
  MIXAR_STALL_PHASE_EVENTS = 0,
  MIXAR_STALL_PHASE_HANDLERS = 1,
  MIXAR_STALL_PHASE_NOTIFIERS = 2,
  MIXAR_STALL_PHASE_DRAW = 3,
  MIXAR_STALL_PHASE_NUM = 4,
};

/** Called by `WM_main` at the top of every iteration. */
void Mixar_stall_iteration_begin();
/** Called by `WM_main` after each phase; `phase` is the phase that just ended. */
void Mixar_stall_phase_end(Mixar_StallPhase phase);
/** Called by `WM_main` after the draw phase; writes the record when the iteration stalled. */
void Mixar_stall_iteration_end(const bContext *C);

/**
 * Open a breadcrumb. `kind` must be a string literal (stored by pointer),
 * `name` is copied (truncated to the record width). Returns the scope index
 * to pass to #Mixar_stall_scope_pop, or -1 when nothing was recorded.
 */
int Mixar_stall_scope_push(const char *kind, const char *name);
void Mixar_stall_scope_pop(int index);

/** Number of iterations recorded as stalls since startup (tests and QA probes). */
int Mixar_stall_record_count();

/**
 * Main-loop iterations since startup, incremented at the top of every iteration. Safe to
 * read from any thread without the GIL or Blender data: the Python stall watchdog polls it
 * as the main thread's heartbeat (`aud._mixar_main_loop_iteration`).
 */
uint64_t Mixar_stall_iteration_count();

/** RAII breadcrumb. */
struct Mixar_StallScope {
  int index;
  Mixar_StallScope(const char *kind, const char *name) : index(Mixar_stall_scope_push(kind, name))
  {
  }
  ~Mixar_StallScope()
  {
    if (index >= 0) {
      Mixar_stall_scope_pop(index);
    }
  }
  Mixar_StallScope(const Mixar_StallScope &) = delete;
  Mixar_StallScope &operator=(const Mixar_StallScope &) = delete;
};

}  // namespace blender
