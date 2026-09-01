/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Queue tab for the Agent island.
 *
 * Renders the unified job queue — the `wm.mixie_queue` WindowManager mirror
 * that the moodboard N-panel's Queue tab lists through a UIList — as island
 * rows: a rounded backplate per job, status dot + title on the left, status
 * word on the right, a cancel cross on active rows. Data is read-only via
 * RNA; every action goes through the queue's EXISTING operators
 * (`mixie.queue_cancel_job`, `mixie.queue_clear_all_completed`) or the stock
 * `wm.context_set_int` on `mixie_queue.active_index`, whose update callback
 * is the queue-selection hook the N-panel list already uses. No timers here:
 * the queue's own blink timer pumps redraws while anything is active, and
 * AGENT_BUBBLE is in QUEUE_SURFACE_AREA_TYPES.
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <ctime>

#include "MEM_guardedalloc.h"

#include "BLF_api.hh"

#include "BLI_rect.h"
#include "BLI_utildefines.h"
#include "BLI_string.h"
#include "BLI_time.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_ui_queue.hh"
#include "agent_ui_theme.hh"

namespace {

/* -------------------------------------------------------------------- */
/** \name Row model
 * \{ */

constexpr int QUEUE_MAX_ROWS = 64;

struct QueueRow {
  char job_id[64];
  char feature_key[64];
  char title[96];
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

bool state_is(const char *state, const char *name)
{
  return STREQ(state, name);
}

/** C++ mirror of the UIList's `_status_word` — one vocabulary, two surfaces. */
void status_word(const char *state, const char *substate, char r_out[64])
{
  const char *word = "";
  if (state_is(state, "SUCCESS")) {
    word = "Done";
  }
  else if (state_is(state, "FAILED")) {
    word = "Failed";
  }
  else if (state_is(state, "CANCELLED")) {
    word = "Cancelled";
  }
  else if (state_is(state, "PAUSED_AUTH")) {
    word = "Waiting for sign-in";
  }
  else if (state_is(state, "RUNNING_SUBMIT") || state_is(state, "RUNNING_POLL") ||
           state_is(state, "RUNNING_DOWNLOAD"))
  {
    word = (substate && substate[0]) ? substate : "Processing";
  }
  else if (state_is(state, "PENDING")) {
    word = (substate && substate[0]) ? substate : "Queued";
  }
  else {
    word = (substate && substate[0]) ? substate : "";
  }
  BLI_strncpy(r_out, word, 64);
}

void read_item_string(PointerRNA *item, const char *name, char *r_buf, const int buf_len)
{
  r_buf[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(item, name);
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return;
  }
  /* Never the bare RNA_property_string_get — it is strcpy-shaped and a value
   * longer than the buffer overflows it. The alloc form clamps to the fixed
   * buffer and only heap-allocates past it. */
  int len = 0;
  char *value = RNA_property_string_get_alloc(item, prop, r_buf, buf_len, &len);
  if (value != r_buf) {
    BLI_strncpy(r_buf, value, size_t(buf_len));
    MEM_freeN(value);
  }
  r_buf[buf_len - 1] = '\0';
}

float read_item_float(PointerRNA *item, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(item, name);
  if (!prop || RNA_property_type(prop) != PROP_FLOAT) {
    return 0.0f;
  }
  return RNA_property_float_get(item, prop);
}

/** m:ss, or h:mm:ss past the hour — mirrors labels.py format_elapsed. */
void format_elapsed(double seconds, char r_out[32])
{
  if (seconds < 0.0) {
    seconds = 0.0;
  }
  const int total = int(seconds);
  const int m = total / 60;
  const int sec = total % 60;
  /* Parameter arrays decay to pointers, so SNPRINTF's ARRAY_SIZE can't see
   * the bound — pass it explicitly. */
  if (m >= 60) {
    BLI_snprintf(r_out, 32, "%d:%02d:%02d", m / 60, m % 60, sec);
  }
  else {
    BLI_snprintf(r_out, 32, "%d:%02d", m, sec);
  }
}

/** Fill \a rows from wm.mixie_queue.items (already newest-first). */
int gather_rows(wmWindowManager *wm, QueueRow *rows, int *r_index_of_row)
{
  if (!wm) {
    return 0;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *queue_prop = RNA_struct_find_property(&wm_ptr, "mixie_queue");
  if (!queue_prop || RNA_property_type(queue_prop) != PROP_POINTER) {
    return 0;
  }
  PointerRNA queue = RNA_property_pointer_get(&wm_ptr, queue_prop);
  PropertyRNA *items = RNA_struct_find_property(&queue, "items");
  if (!items || RNA_property_type(items) != PROP_COLLECTION) {
    return 0;
  }

  int count = 0;
  int index = 0;
  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&queue, items, &iter);
  for (; iter.valid && count < QUEUE_MAX_ROWS; RNA_property_collection_next(&iter), index++) {
    PointerRNA item = iter.ptr;
    QueueRow &row = rows[count];

    read_item_string(&item, "job_id", row.job_id, sizeof(row.job_id));
    read_item_string(&item, "feature_key", row.feature_key, sizeof(row.feature_key));

    char display_label[96] = "";
    char label[96] = "";
    read_item_string(&item, "display_label", display_label, sizeof(display_label));
    read_item_string(&item, "label", label, sizeof(label));
    const char *title = display_label[0] ? display_label : (label[0] ? label : "(unnamed)");
    BLI_strncpy(row.title, title, sizeof(row.title));
    /* Match the UIList's capitalized first letter. ASCII-only on purpose —
     * a multi-byte first char is left alone. */
    if (row.title[0] >= 'a' && row.title[0] <= 'z') {
      row.title[0] = char(row.title[0] - 'a' + 'A');
    }

    char state[32] = "";
    char substate[64] = "";
    read_item_string(&item, "state", state, sizeof(state));
    read_item_string(&item, "substate_text", substate, sizeof(substate));
    status_word(state, substate, row.status);
    read_item_string(&item, "type_label", row.type_label, sizeof(row.type_label));
    read_item_string(&item, "model_label", row.model_label, sizeof(row.model_label));
    row.created_epoch = double(read_item_float(&item, "created_epoch"));
    row.elapsed_done = read_item_float(&item, "elapsed_done");

    row.is_running = state_is(state, "RUNNING_SUBMIT") || state_is(state, "RUNNING_POLL") ||
                     state_is(state, "RUNNING_DOWNLOAD");
    row.is_pending = state_is(state, "PENDING") || state_is(state, "PAUSED_AUTH");
    row.is_done = state_is(state, "SUCCESS");
    row.is_failed = state_is(state, "FAILED") || state_is(state, "CANCELLED");

    r_index_of_row[count] = index;
    count++;
  }
  RNA_property_collection_end(&iter);
  return count;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Paint helpers (duplicated from agent_ui_draw.cc's statics —
 * deliberately local; that file's helpers are private to its own pass).
 * \{ */

void q_fill_round(const rctf *rect, const float radius, const float col[4])
{
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(rect, true, radius, col);
}

int q_font()
{
  return BLF_default();
}

float q_text_width(const char *text, const float size)
{
  const int font = q_font();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}

void q_label_left(
    const char *text, const float x, const float cy, const float size, const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  const int font = q_font();
  BLF_size(font, size);
  BLF_disable(font, BLF_CLIPPING);

  rcti box;
  BLF_boundbox(font, text, strlen(text), &box);
  const float baseline = cy - float(box.ymin + box.ymax) * 0.5f;

  BLF_color4fv(font, col);
  BLF_position(font, x, baseline, 0.0f);
  BLF_draw(font, text, strlen(text));
}

void q_label_centre(
    const char *text, const float cx, const float cy, const float size, const float col[4])
{
  q_label_left(text, cx - q_text_width(text, size) * 0.5f, cy, size, col);
}

void q_label_right(
    const char *text, const float x, const float cy, const float size, const float col[4])
{
  q_label_left(text, x - q_text_width(text, size), cy, size, col);
}

/** Truncate \a text (in place) so it fits \a max_w at \a size, byte-safe. */
void q_fit_text(char *text, const float max_w, const float size)
{
  if (q_text_width(text, size) <= max_w) {
    return;
  }
  size_t len = strlen(text);
  while (len > 1) {
    len--;
    /* Never split a UTF-8 sequence: back up over continuation bytes. */
    while (len > 1 && ((unsigned char)(text[len]) & 0xC0) == 0x80) {
      len--;
    }
    text[len] = '\0';
    if (q_text_width(text, size) <= max_w) {
      break;
    }
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Row metrics — all in island units, scaled by `u` at use.
 * \{ */

#define QROW_H 64.0f       /* Row backplate height. */
#define QROW_GAP 10.0f     /* Vertical gap between rows. */
#define QROW_PAD_X 18.0f   /* Row inner horizontal padding. */
#define QROW_RADIUS 14.0f  /* Row corner radius — matches the chips. */
#define QROW_DOT_R 5.0f    /* Status dot radius — matches the pill's dot. */
#define QROW_FONT 18.0f    /* Title size — matches the chip labels. */
#define QROW_FONT_SUB 15.0f/* Status size — matches the pill label. */
#define QROW_CANCEL_W 40.0f/* Cancel cross hit width at the row's right edge. */
#define QPANEL_PAD 16.0f   /* Panel inset around the whole list. */
#define QHEADER_H 46.0f    /* "N jobs" + Clear finished strip above the rows. */

/** \} */

}  // namespace

void agent_ui_queue_draw(const bContext *C, ARegion *region, const rctf &panel, const float u)
{
  wmWindowManager *wm = CTX_wm_manager(C);

  QueueRow rows[QUEUE_MAX_ROWS];
  int mirror_index[QUEUE_MAX_ROWS];
  const int row_count = gather_rows(wm, rows, mirror_index);

  const float pad = QPANEL_PAD * u;
  const float row_h = QROW_H * u;
  const float row_gap = QROW_GAP * u;
  const float font = QROW_FONT * u;
  const float font_sub = QROW_FONT_SUB * u;

  const float list_left = panel.xmin + pad;
  const float list_right = panel.xmax - pad;
  const float header_h = QHEADER_H * u;
  float y_top = panel.ymax - pad;

  const float col_text[4] = AGENT_COL_TEXT;
  const float col_dim[4] = AGENT_COL_TEXT_DIM;
  const float col_row[4] = AGENT_COL_CHIP;
  const float col_accent[4] = AGENT_COL_BORDER;   /* Running dot: the island green. */
  const float col_done[4] = AGENT_COL_ACCENT;     /* Done dot: calmer green. */
  const float col_pending[4] = AGENT_COL_QUEUE_COUNT;
  const float col_failed[4] = {0.804f, 0.361f, 0.361f, 1.0f}; /* Muted red. */

  GPU_blend(GPU_BLEND_ALPHA);

  if (row_count == 0) {
    q_label_centre("No jobs in the queue",
                   (panel.xmin + panel.xmax) * 0.5f,
                   (panel.ymin + panel.ymax) * 0.5f,
                   font,
                   col_dim);
    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  /* Header strip: count on the left, Clear finished on the right (painted
   * here; its invisible button is laid below with the rest). */
  bool any_terminal = false;
  int active_count = 0;
  for (int i = 0; i < row_count; i++) {
    any_terminal |= (rows[i].is_done || rows[i].is_failed);
    active_count += int(rows[i].is_running || rows[i].is_pending);
  }
  {
    char counts[64];
    if (active_count > 0) {
      SNPRINTF(counts, "%d job%s · %d active", row_count, (row_count == 1) ? "" : "s",
               active_count);
    }
    else {
      SNPRINTF(counts, "%d job%s", row_count, (row_count == 1) ? "" : "s");
    }
    const float cy = y_top - header_h * 0.5f;
    q_label_left(counts, list_left, cy, font_sub, col_dim);
    if (any_terminal) {
      q_label_right("Clear finished", list_right, cy, font_sub, col_dim);
    }
  }
  y_top -= header_h;

  /* Rows, newest first, as many as fit. */
  const int fit = std::max(0, int((y_top - panel.ymin - pad) / (row_h + row_gap)));
  const int shown = std::min(row_count, fit);

  for (int i = 0; i < shown; i++) {
    const QueueRow &row = rows[i];
    rctf rect;
    rect.xmin = list_left;
    rect.xmax = list_right;
    rect.ymax = y_top - float(i) * (row_h + row_gap);
    rect.ymin = rect.ymax - row_h;

    q_fill_round(&rect, QROW_RADIUS * u, col_row);

    const float cy = (rect.ymin + rect.ymax) * 0.5f;
    const float dot_r = QROW_DOT_R * u;
    const float dot_cx = rect.xmin + QROW_PAD_X * u + dot_r;

    /* Status dot; running rows breathe with the queue blink timer's pump. */
    float dot_col[4];
    if (row.is_running) {
      memcpy(dot_col, col_accent, sizeof(dot_col));
      const float phase = float(BLI_time_now_seconds() * 2.0);
      dot_col[3] = 0.55f + 0.45f * fabsf(sinf(phase));
    }
    else if (row.is_done) {
      memcpy(dot_col, col_done, sizeof(dot_col));
    }
    else if (row.is_failed) {
      memcpy(dot_col, col_failed, sizeof(dot_col));
    }
    else {
      memcpy(dot_col, col_pending, sizeof(dot_col));
    }
    rctf dot;
    dot.xmin = dot_cx - dot_r;
    dot.xmax = dot_cx + dot_r;
    dot.ymin = cy - dot_r;
    dot.ymax = cy + dot_r;
    q_fill_round(&dot, dot_r, dot_col);

    /* Two-line row, matching the moodboard queue's information:
     *   line 1: dot + title ................ elapsed clock [cancel]
     *   line 2:       type - model ......... status word */
    const float cy1 = rect.ymax - row_h * 0.30f;
    const float cy2 = rect.ymin + row_h * 0.26f;
    const float right_edge = rect.xmax - QROW_PAD_X * u -
                             ((row.is_running || row.is_pending) ? QROW_CANCEL_W * u : 0.0f);

    /* Elapsed clock: ticking for live rows (the queue blink timer pumps the
     * redraws), frozen at the completion duration for terminal rows. */
    char clock[32] = "";
    if (row.is_running || row.is_pending) {
      if (row.created_epoch > 0.0) {
        format_elapsed(double(time(nullptr)) - row.created_epoch, clock);
      }
    }
    else if (row.elapsed_done > 0.0f) {
      format_elapsed(double(row.elapsed_done), clock);
    }
    if (clock[0]) {
      q_label_right(clock, right_edge, cy1, font_sub, col_dim);
    }

    /* Title between dot and clock. */
    char title[96];
    BLI_strncpy(title, row.title, sizeof(title));
    const float title_x = dot_cx + dot_r + 12.0f * u;
    const float title_max_w = right_edge - q_text_width(clock, font_sub) - 16.0f * u - title_x;
    q_fit_text(title, title_max_w, font);
    q_label_left(title, title_x, cy1, font, col_text);

    /* Metadata line: generation type - model, dim; status word right. */
    char status[64];
    BLI_strncpy(status, row.status, sizeof(status));
    const float status_max_w = (rect.xmax - rect.xmin) * 0.35f;
    q_fit_text(status, status_max_w, font_sub);
    q_label_right(status, right_edge, cy2, font_sub, row.is_failed ? col_failed : col_dim);

    char meta[160] = "";
    if (row.type_label[0] && row.model_label[0]) {
      SNPRINTF(meta, "%s \xC2\xB7 %s", row.type_label, row.model_label);
    }
    else if (row.type_label[0]) {
      BLI_strncpy(meta, row.type_label, sizeof(meta));
    }
    else if (row.model_label[0]) {
      BLI_strncpy(meta, row.model_label, sizeof(meta));
    }
    if (meta[0]) {
      const float meta_max_w = right_edge - q_text_width(status, font_sub) - 16.0f * u - title_x;
      q_fit_text(meta, meta_max_w, font_sub);
      q_label_left(meta, title_x, cy2, font_sub, col_dim);
    }

    /* Cancel cross for rows that can still be cancelled. */
    if (row.is_running || row.is_pending) {
      q_label_centre("\xC3\x97", /* U+00D7 multiplication sign. */
                     rect.xmax - (QROW_CANCEL_W * 0.5f) * u,
                     cy,
                     font,
                     col_dim);
    }
  }

  if (shown < row_count) {
    char more[32];
    SNPRINTF(more, "+%d more", row_count - shown);
    const float more_y = y_top - float(shown) * (row_h + row_gap) - row_gap;
    q_label_centre(more, (list_left + list_right) * 0.5f, more_y, font_sub, col_dim);
  }

  GPU_blend(GPU_BLEND_NONE);

  /* ---- Controls: one unembossed block over the painted rows. ---- */
  uiBlock *block = UI_block_begin(C, region, "agent_island_queue", blender::ui::EmbossType::None);

  /* Clear finished. */
  if (any_terminal) {
    const float cy = panel.ymax - pad - header_h * 0.5f;
    const float w = q_text_width("Clear finished", font_sub) + 16.0f * u;
    uiDefButO(block, ButType::But, "mixie.queue_clear_all_completed",
              blender::wm::OpCallContext::InvokeDefault, "",
              int(list_right - w), int(cy - header_h * 0.5f), short(w), short(header_h),
              "Remove all finished jobs from the queue");
  }

  for (int i = 0; i < shown; i++) {
    const QueueRow &row = rows[i];
    const float row_top = panel.ymax - pad - header_h - float(i) * (row_h + row_gap);
    const float row_bottom = row_top - row_h;
    const float cancel_w = QROW_CANCEL_W * u;

    if (row.is_running || row.is_pending) {
      uiBut *but = uiDefButO(block, ButType::But, "mixie.queue_cancel_job",
                             blender::wm::OpCallContext::InvokeDefault, "",
                             int(list_right - cancel_w), int(row_bottom),
                             short(cancel_w), short(row_h), "Cancel this job");
      if (but) {
        PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
        RNA_string_set(op_ptr, "feature_key", row.feature_key);
        RNA_string_set(op_ptr, "job_id", row.job_id);
      }
    }

    /* Row select — drives the mirror's active_index, whose update callback is
     * the queue-selection hook (frames the imported result, etc.). The rect
     * stops short of the cancel zone so the two never overlap. */
    uiBut *sel = uiDefButO(block, ButType::But, "wm.context_set_int",
                           blender::wm::OpCallContext::InvokeDefault, "",
                           int(list_left), int(row_bottom),
                           short(list_right - cancel_w - list_left), short(row_h),
                           "Select this job");
    if (sel) {
      PointerRNA *op_ptr = UI_but_operator_ptr_ensure(sel);
      RNA_string_set(op_ptr, "data_path", "window_manager.mixie_queue.active_index");
      RNA_int_set(op_ptr, "value", mirror_index[i]);
    }
  }

  UI_block_end(C, block);
  UI_block_draw(C, block);
}
