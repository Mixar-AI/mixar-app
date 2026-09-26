/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "BLI_rect.h"
#include "BLI_vector.hh"
#include "UI_mixar.hh"
#include "UI_mixar_layout.hh"
#include <string>

struct wmWindowManager;

namespace blender::agent_queue {

enum Navigation { STEP, PAGE, FIRST, LAST };

struct QueueLayout {
  rctf rows, footer;
  /* "Why it failed" card under the rows; empty (xmin == xmax) when hidden. */
  rctf failure;
  float row_height, row_gap;
  int capacity;
};
/** \param failure_card: the selected job failed, so reserve its details card. */
QueueLayout layout(const rctf &panel, float unit, int total, bool failure_card);
struct QueueData;
QueueData gather_rows(wmWindowManager *wm, int capacity);
int total_rows(wmWindowManager *wm);
float offset_get(wmWindowManager *wm);
/** True when the selected (`active_index`) job is FAILED — the details card shows. */
bool active_failure_present(wmWindowManager *wm);

/** Failure explanation, stamped by the Python mirror (core/failure_info.py). */
struct QueueFailure {
  char job_id[64];
  char feature_key[64];
  char headline[64]; /* "Blocked by content policy" */
  std::string message; /* one readable sentence */
  std::string reason;  /* provider/backend's own words; empty if it repeats message */
  std::string hint;    /* what the user can do */
  std::string details; /* all of the above + support ids (tooltip, clipboard) */
};

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
  bool is_cancelled;
  /* FAILED rows only (see QueueFailure); empty otherwise. */
  QueueFailure failure;
};

struct QueueData {
  Vector<QueueRow> rows;
  ui::MixarVisibleRange visible;
  int total = 0, active = 0, active_index = -1;
  /* Header summary counts across ALL rows, not only the visible page. */
  int running = 0, pending = 0, done = 0, failed = 0;
  bool any_terminal = false;
  /* The selected job, when it FAILED (drives the details card). */
  bool has_selected_failure = false;
  QueueFailure selected_failure;
};
void format_elapsed(double seconds, char r_out[32]);

/** Paint + lay out the "Why it failed" card (agent_ui_queue_failure.cc). */
void failure_card_draw(ui::Block *block, const QueueFailure &failure, const rctf &card, float u);
/** Greedy word wrap into at most \a max_lines lines; the last is elided. */
Vector<std::string> wrap_text(const std::string &text, float max_width, float size, int max_lines);

}  // namespace blender::agent_queue
