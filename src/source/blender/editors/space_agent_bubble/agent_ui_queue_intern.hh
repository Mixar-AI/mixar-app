/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include <string>

struct wmWindowManager;

namespace blender::agent_queue {

constexpr int QUEUE_MAX_ROWS = 64;

struct QueueRow {
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

int gather_rows(wmWindowManager *wm, QueueRow *rows, int *r_index_of_row, int &r_active_index);
void format_elapsed(double seconds, char r_out[32]);

}  // namespace blender::agent_queue
