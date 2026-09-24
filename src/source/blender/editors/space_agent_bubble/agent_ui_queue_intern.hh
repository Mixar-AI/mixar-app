/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "BLI_rect.h"
#include "BLI_vector.hh"
#include "UI_mixar_layout.hh"
#include <string>

struct wmWindowManager;

namespace blender::agent_queue {

enum Navigation { STEP, PAGE, FIRST, LAST };

struct QueueLayout {
  rctf rows, footer;
  float row_height, row_gap;
  int capacity;
};
QueueLayout layout(const rctf &panel, float unit, int total);
struct QueueData;
QueueData gather_rows(wmWindowManager *wm, int capacity);
int total_rows(wmWindowManager *wm);
float offset_get(wmWindowManager *wm);

struct QueueRow {
  int mirror_index;
  char job_id[64];
  char feature_key[64];
  std::string title;
  char status[64];
  /* Metadata line — catalog labels + clock base, all stamped by the Python
   * mirror sync (queue_properties.py), never derived here. */
  char type_label[64];
  char model_label[64];
  double created_epoch; /* unix seconds; 0 when unknown */
  float elapsed_done;   /* frozen duration for terminal rows; 0 otherwise */
  /* Lifecycle buckets, mirroring the UIList's state groups. */
  bool is_running;
  bool is_pending;
  bool is_done;
  bool is_failed; /* FAILED or CANCELLED. */
};

struct QueueData {
  Vector<QueueRow> rows;
  ui::MixarVisibleRange visible;
  int total = 0, active = 0, active_index = -1;
  bool any_terminal = false;
};
void format_elapsed(double seconds, char r_out[32]);

}  // namespace blender::agent_queue
