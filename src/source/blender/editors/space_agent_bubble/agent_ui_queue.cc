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

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"

#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "WM_types.hh"

#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_queue.hh"
#include "agent_ui_queue_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* -------------------------------------------------------------------- */
/** \name Row metrics — all in island units, scaled by `u` at use.
 * \{ */

/* The queue reads at its OWN scale, not the kit's.
 *
 * Every other pane is chips and a prompt — a handful of short labels with air
 * around them. The queue is a dense two-line list, and at the kit's 18/15 it
 * was the one pane you had to lean in to read. The row grows with the type so
 * the two lines keep their breathing room (they are placed as fractions of
 * QROW_H); the cost is roughly one fewer visible row, which is
 * the right trade for a list whose whole job is to be glanceable. */
#define QROW_H 76.0f            /* Row backplate height. */
#define QROW_GAP 10.0f          /* Vertical gap between rows. */
#define QROW_PAD_X 18.0f        /* Row inner horizontal padding. */
#define QROW_DOT_R 6.0f         /* Status dot radius — scaled with the type. */
#define QROW_FONT 23.0f         /* Title size. */
#define QROW_FONT_SUB 19.0f     /* Status / metadata size. */
#define QROW_CANCEL_W 40.0f     /* Cancel cross hit width at the row's right edge. */
#define QPANEL_PAD PANE_INSET_X /* Panel inset — the kit strip inset. */
#define QHEADER_H 54.0f         /* "N jobs" + Clear finished strip above the rows. */

/** \} */

}  // namespace

void agent_ui_queue_draw(const bContext *C, ARegion *region, const rctf &panel, const float u)
{
  wmWindowManager *wm = CTX_wm_manager(C);

  using namespace agent_queue;
  QueueRow rows[QUEUE_MAX_ROWS];
  int mirror_index[QUEUE_MAX_ROWS];
  int active_index = -1;
  const int row_count = gather_rows(wm, rows, mirror_index, active_index);

  const float pad = QPANEL_PAD * u;
  const float row_h = QROW_H * u;
  const float row_gap = QROW_GAP * u;
  const float font = QROW_FONT * u;
  const float font_sub = QROW_FONT_SUB * u;

  const float list_left = panel.xmin + pad;
  const float list_right = panel.xmax - pad;
  const float header_h = QHEADER_H * u;
  float y_top = panel.ymax - pad;

  const auto &palette = ui::mixar_tokens::zen;
  const float *col_text = palette.text;
  const float *col_dim = palette.secondary;
  const float *col_accent = palette.focus;
  const float *col_done = palette.focus;
  const float *col_pending = palette.warning;
  const float *col_failed = palette.danger;

  GPU_blend(GPU_BLEND_ALPHA);

  /* Shared panel wash (pane kit) — the queue backdrops like every pane. */
  pane_wash_paint(panel, u);

  if (row_count == 0) {
    pane_label_centre("No jobs in the queue",
                      (panel.xmin + panel.xmax) * 0.5f,
                      (panel.ymin + panel.ymax) * 0.5f,
                      font,
                      col_dim);
    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  /* Count and actions share the header strip. */
  bool any_terminal = false;
  int active_count = 0;
  for (int i = 0; i < row_count; i++) {
    any_terminal |= (rows[i].is_done || rows[i].is_failed);
    active_count += int(rows[i].is_running || rows[i].is_pending);
  }
  {
    char counts[64];
    if (active_count > 0) {
      SNPRINTF(
          counts, "%d job%s · %d active", row_count, (row_count == 1) ? "" : "s", active_count);
    }
    else {
      SNPRINTF(counts, "%d job%s", row_count, (row_count == 1) ? "" : "s");
    }
    const float cy = y_top - header_h * 0.5f;
    pane_label_left(counts, list_left, cy, font_sub, col_dim);
  }
  y_top -= header_h;

  /* Rows, newest first, as many as fit. */
  const int fit = std::max(0, int((y_top - panel.ymin - pad) / (row_h + row_gap)));
  const int shown = std::min(row_count, fit);

  /* Native rectangles own drawing, events and QA. Content is painted afterward.
   */
  rctf row_rects[QUEUE_MAX_ROWS];
  ui::Block *block = ui::block_begin(
      C, region, "agent_island_queue", blender::ui::EmbossType::None);

  /* Clear finished. */
  if (any_terminal) {
    const float cy = panel.ymax - pad - header_h * 0.5f;
    const float w = pane_action_chip_w("Clear finished", false, u);
    ui::Button *clear = uiDefButO(block,
                                  ui::ButtonType::But,
                                  "mixie.queue_clear_all_completed",
                                  blender::wm::OpCallContext::InvokeDefault,
                                  "Clear finished",
                                  int(list_right - w),
                                  int(cy - ui::mixar_tokens::control_height * u * 0.5f),
                                  short(w),
                                  short(ui::mixar_tokens::control_height * u),
                                  "Remove all finished jobs from the queue");
    ui::mixar_style_button(clear, ui::MixarComponent::Action, ui::MixarVariant::Secondary, u);
  }

  for (int i = 0; i < shown; i++) {
    const QueueRow &row = rows[i];
    const float row_top = panel.ymax - pad - header_h - float(i) * (row_h + row_gap);
    const float row_bottom = row_top - row_h;
    const bool cancellable = row.is_running || row.is_pending;
    const float cancel_w = cancellable ? QROW_CANCEL_W * u : 0.0f;
    row_rects[i] = {list_left, list_right - cancel_w, row_bottom, row_top};

    if (row.is_running || row.is_pending) {
      ui::Button *but = uiDefButO(block,
                                  ui::ButtonType::But,
                                  "mixie.queue_cancel_job",
                                  blender::wm::OpCallContext::InvokeDefault,
                                  "×",
                                  int(list_right - cancel_w),
                                  int(row_bottom),
                                  short(cancel_w),
                                  short(row_h),
                                  "Cancel this job");
      ui::mixar_style_button(but, ui::MixarComponent::Action, ui::MixarVariant::Ghost, u);
      if (but) {
        PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
        RNA_string_set(op_ptr, "feature_key", row.feature_key);
        RNA_string_set(op_ptr, "job_id", row.job_id);
      }
    }

    /* Row select — drives the mirror's active_index, whose update callback is
     * the queue-selection hook (frames the imported result, etc.). The rect
     * stops short of the cancel zone so the two never overlap. */
    ui::Button *sel = uiDefButO(block,
                                ui::ButtonType::But,
                                "wm.context_set_int",
                                blender::wm::OpCallContext::InvokeDefault,
                                row.title.c_str(),
                                int(list_left),
                                int(row_bottom),
                                short(list_right - cancel_w - list_left),
                                short(row_h),
                                "Select this job");
    ui::mixar_style_button(sel, ui::MixarComponent::Surface, ui::MixarVariant::Secondary, u);
    ui::mixar_button_lit_set(sel, mirror_index[i] == active_index);
    ui::mixar_button_tooltip_owned(sel, row.title.c_str());
    if (sel) {
      PointerRNA *op_ptr = ui::button_operator_ptr_ensure(sel);
      RNA_string_set(op_ptr, "data_path", "window_manager.mixie_queue.active_index");
      RNA_int_set(op_ptr, "value", mirror_index[i]);
    }
  }

  ui::block_end(C, block);
  ui::block_draw(C, block);
  GPU_blend(GPU_BLEND_ALPHA);

  for (int i = 0; i < shown; i++) {
    const QueueRow &row = rows[i];
    const rctf &rect = row_rects[i];
    const bool selected = mirror_index[i] == active_index;
    const float *row_dim = selected ? palette.text : palette.secondary;

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
    pane_fill_round(&dot, dot_r, dot_col);

    /* Two-line row, matching the moodboard queue's information:
     *   line 1: dot + title ................ elapsed clock [cancel]
     *   line 2:       type - model ......... status word */
    const float cy1 = rect.ymax - row_h * 0.30f;
    const float cy2 = rect.ymin + row_h * 0.26f;
    const float right_edge = rect.xmax - QROW_PAD_X * u;

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
      pane_label_right(clock, right_edge, cy1, font_sub, row_dim);
    }

    /* Title between dot and clock. */
    const float title_x = dot_cx + dot_r + 12.0f * u;
    const float title_max_w = right_edge - pane_text_width(clock, font_sub) - 16.0f * u - title_x;
    const std::string title = ui::mixar_fit_text(row.title.c_str(), title_max_w, font);
    ui::mixar_label_left(title.c_str(), title_x, cy1, font, col_text);

    /* Metadata line: generation type - model, dim; status word right. */
    char status[64];
    BLI_strncpy(status, row.status, sizeof(status));
    const float status_max_w = (rect.xmax - rect.xmin) * 0.35f;
    pane_fit_text(status, status_max_w, font_sub);
    pane_label_right(
        status, right_edge, cy2, font_sub, row.is_failed && !selected ? col_failed : row_dim);

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
      const float meta_max_w = right_edge - pane_text_width(status, font_sub) - 16.0f * u -
                               title_x;
      pane_fit_text(meta, meta_max_w, font_sub);
      pane_label_left(meta, title_x, cy2, font_sub, row_dim);
    }
  }

  if (shown < row_count) {
    char more[32];
    SNPRINTF(more, "+%d more", row_count - shown);
    const float more_y = y_top - float(shown) * (row_h + row_gap) - row_gap;
    pane_label_centre(more, (list_left + list_right) * 0.5f, more_y, font_sub, col_dim);
  }

  GPU_blend(GPU_BLEND_NONE);
}

}  // namespace blender
