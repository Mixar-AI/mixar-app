/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Table segment rendering for chat messages.
 * Tables are stored as tab-delimited text (first line = header, rest = rows).
 * Calculates column widths from content, clips text to cell bounds.
 */

#include <cmath>
#include <cstring>

#include "BLF_api.hh"

#include "mixie_chat_intern.hh"
#include "mixie_chat_markdown_intern.hh"
#include "mixie_chat_ui_types.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Table Parsing Helpers
 * \{ */

static int count_columns(const char *line, const char *line_end)
{
  int count = 1;
  for (const char *p = line; p < line_end; p++) {
    if (*p == '\t') {
      count++;
    }
  }
  return (count > MARKDOWN_TABLE_MAX_COLS) ? MARKDOWN_TABLE_MAX_COLS : count;
}

/**
 * Count non-empty newline-separated rows in text.
 * Skips trailing newlines and blank lines.
 */
static int count_rows(const char *text)
{
  int count = 0;
  const char *p = text;
  while (*p) {
    /* Find end of this line */
    const char *line_end = p;
    while (*line_end && *line_end != '\n') {
      line_end++;
    }
    /* Count only non-empty lines */
    if (line_end > p) {
      count++;
    }
    p = (*line_end) ? line_end + 1 : line_end;
  }
  return count;
}

static void extract_cell(const char *line,
                          const char *line_end,
                          int col_idx,
                          char *out,
                          int max_len)
{
  out[0] = '\0';
  const char *cell_start = line;
  int col = 0;

  while (cell_start < line_end && col < col_idx) {
    while (cell_start < line_end && *cell_start != '\t') {
      cell_start++;
    }
    if (cell_start < line_end) {
      cell_start++;
    }
    col++;
  }

  if (col != col_idx) {
    return;
  }

  const char *cell_end = cell_start;
  while (cell_end < line_end && *cell_end != '\t') {
    cell_end++;
  }

  int len = int(cell_end - cell_start);
  if (len > max_len - 1) {
    len = max_len - 1;
  }
  memcpy(out, cell_start, len);
  out[len] = '\0';
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Column Layout
 * \{ */

/**
 * Measure natural column widths from content.
 * Returns total measured width.
 */
static float measure_column_widths(const char *text,
                                    int col_count,
                                    int font_size,
                                    float cell_h_pad,
                                    float *col_widths)
{
  for (int c = 0; c < col_count; c++) {
    col_widths[c] = 0;
  }

  const char *line = text;
  int row = 0;

  while (*line && row < MARKDOWN_TABLE_MAX_ROWS + 1) {
    const char *line_end = line;
    while (*line_end && *line_end != '\n') {
      line_end++;
    }

    for (int c = 0; c < col_count; c++) {
      char cell[256];
      extract_cell(line, line_end, c, cell, sizeof(cell));

      if (cell[0]) {
        float w, h;
        int flags = (row == 0) ? BLF_BOLD : 0;
        chat_ui_calc_text_bounds(cell, 10000.0f, font_size, flags, &w, &h);
        float cw = w + cell_h_pad * 2;
        if (cw > col_widths[c]) {
          col_widths[c] = cw;
        }
      }
    }

    row++;
    line = (*line_end) ? line_end + 1 : line_end;
  }

  float total_width = 0;
  for (int c = 0; c < col_count; c++) {
    if (col_widths[c] < 40.0f) {
      col_widths[c] = 40.0f;
    }
    total_width += col_widths[c];
  }

  return total_width;
}

/**
 * Determine how many columns fit in the available width.
 * Each column needs at least min_col_w pixels to be readable.
 */
static int calc_visible_columns(int col_count, float content_width, float min_col_w)
{
  int max_cols = int(content_width / min_col_w);
  if (max_cols < 1) {
    max_cols = 1;
  }
  return (col_count < max_cols) ? col_count : max_cols;
}

/**
 * Distribute content_width across visible columns proportionally,
 * enforcing a minimum column width.
 */
static void distribute_column_widths(float *col_widths,
                                      int vis_cols,
                                      float content_width,
                                      float min_col_w)
{
  float total = 0;
  for (int c = 0; c < vis_cols; c++) {
    total += col_widths[c];
  }

  if (total <= content_width && total > 0) {
    /* Columns fit — expand proportionally to fill width */
    float scale = content_width / total;
    for (int c = 0; c < vis_cols; c++) {
      col_widths[c] *= scale;
    }
    return;
  }

  if (total <= 0) {
    /* Equal distribution fallback */
    float w = content_width / float(vis_cols);
    for (int c = 0; c < vis_cols; c++) {
      col_widths[c] = w;
    }
    return;
  }

  /* Columns too wide — scale down proportionally */
  float scale = content_width / total;
  for (int c = 0; c < vis_cols; c++) {
    col_widths[c] *= scale;
    if (col_widths[c] < min_col_w) {
      col_widths[c] = min_col_w;
    }
  }
}

/**
 * Draw a single-line text string clipped to a rectangular region.
 * Uses BLF_CLIPPING so text beyond the cell boundary is invisible.
 */
static void draw_cell_text(const char *text,
                            float cell_xmin,
                            float cell_xmax,
                            float baseline_y,
                            int font_size,
                            int flags,
                            const float color[4])
{
  if (!text || !text[0]) {
    return;
  }

  const int font_id = BLF_default();
  BLF_size(font_id, font_size);

  if (flags) {
    BLF_enable(font_id, FontFlags(flags));
  }

  /* Enable clipping to cell boundaries */
  BLF_enable(font_id, BLF_CLIPPING);
  BLF_clipping(font_id, cell_xmin, -10000.0f, cell_xmax, 10000.0f);

  BLF_color4fv(font_id, color);
  BLF_position(font_id, cell_xmin, baseline_y, 0.0f);
  BLF_draw(font_id, text, strlen(text));

  BLF_disable(font_id, BLF_CLIPPING);

  if (flags) {
    BLF_disable(font_id, FontFlags(flags));
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Public Table API
 * \{ */

float chat_ui_calc_table_height(const MarkdownSegment *seg,
                                 const ChatBubbleStyle *style,
                                 float content_width,
                                 float scale_factor)
{
  if (!seg->text[0]) {
    return 0;
  }

  int total_rows = count_rows(seg->text);
  if (total_rows <= 0) {
    return 0;
  }

  float row_h = float(style->font_size) * 1.6f;
  float padding = 8.0f * scale_factor;
  float sep_h = 1.0f * scale_factor;

  return padding + row_h + sep_h + float(total_rows - 1) * row_h + padding;
}

float chat_ui_draw_table(const MarkdownSegment *seg,
                          float x,
                          float y,
                          float content_width,
                          const ChatBubbleStyle *style,
                          float scale_factor)
{
  if (!seg->text[0] || content_width < 40.0f) {
    return 0;
  }

  /* Parse dimensions */
  const char *first_line_end = seg->text;
  while (*first_line_end && *first_line_end != '\n') {
    first_line_end++;
  }
  int col_count = count_columns(seg->text, first_line_end);
  int total_rows = count_rows(seg->text);
  if (col_count <= 0 || total_rows <= 0) {
    return 0;
  }

  /* Layout constants */
  float cell_h_pad = 6.0f * scale_factor;
  float row_h = float(style->font_size) * 1.6f;
  float padding = 8.0f * scale_factor;
  float sep_h = 1.0f * scale_factor;
  float corner = 4.0f * scale_factor;
  float min_col_w = 60.0f * scale_factor;

  /* Limit visible columns to what fits */
  int vis_cols = calc_visible_columns(col_count, content_width, min_col_w);

  /* Measure and distribute column widths */
  float col_widths[MARKDOWN_TABLE_MAX_COLS];
  measure_column_widths(seg->text, vis_cols, style->font_size, cell_h_pad, col_widths);
  distribute_column_widths(col_widths, vis_cols, content_width, min_col_w);

  float total_height = padding + row_h + sep_h + float(total_rows - 1) * row_h + padding;

  /* Draw table background */
  float bg_color[4];
  chat_ui_get_button_bg_color(bg_color);
  bg_color[3] = 0.4f;
  rctf bg_rect;
  bg_rect.xmin = x;
  bg_rect.xmax = x + content_width;
  bg_rect.ymin = y - total_height;
  bg_rect.ymax = y;
  chat_ui_draw_rounded_rect(&bg_rect, corner, bg_color);

  /* Iterate rows, skipping empty lines */
  float cur_y = y - padding;
  const char *line = seg->text;
  int row_idx = 0;

  while (*line) {
    const char *line_end = line;
    while (*line_end && *line_end != '\n') {
      line_end++;
    }

    /* Skip empty lines */
    if (line_end == line) {
      line = (*line_end) ? line_end + 1 : line_end;
      continue;
    }

    bool is_header = (row_idx == 0);

    /* Header accent background */
    if (is_header) {
      float header_bg[4];
      chat_ui_get_button_bg_color(header_bg);
      header_bg[3] = 0.7f;
      rctf hdr_rect;
      hdr_rect.xmin = x;
      hdr_rect.xmax = x + content_width;
      hdr_rect.ymin = cur_y - row_h;
      hdr_rect.ymax = cur_y;
      chat_ui_draw_rounded_rect(&hdr_rect, corner, header_bg);
    }

    /* Draw cells */
    float cell_x = x;
    float baseline_y = cur_y - row_h * 0.65f;

    for (int c = 0; c < vis_cols; c++) {
      char cell[256];
      extract_cell(line, line_end, c, cell, sizeof(cell));

      if (cell[0]) {
        int flags = is_header ? BLF_BOLD : 0;
        float text_color[4];
        memcpy(text_color, style->text_color, sizeof(float) * 4);
        if (is_header) {
          text_color[0] = fminf(text_color[0] * 1.15f, 1.0f);
          text_color[1] = fminf(text_color[1] * 1.15f, 1.0f);
          text_color[2] = fminf(text_color[2] * 1.15f, 1.0f);
        }

        draw_cell_text(cell,
                       cell_x + cell_h_pad,
                       cell_x + col_widths[c] - cell_h_pad,
                       baseline_y,
                       style->font_size,
                       flags,
                       text_color);
      }

      /* Column separator */
      if (c < vis_cols - 1) {
        float sep_color[4] = {0.5f, 0.5f, 0.5f, 0.15f};
        rctf sep_rect;
        sep_rect.xmin = cell_x + col_widths[c] - 0.5f * scale_factor;
        sep_rect.xmax = cell_x + col_widths[c] + 0.5f * scale_factor;
        sep_rect.ymin = cur_y - row_h;
        sep_rect.ymax = cur_y;
        chat_ui_draw_rounded_rect(&sep_rect, 0, sep_color);
      }

      cell_x += col_widths[c];
    }

    /* Thin separator line after header, subtle line after data rows */
    if (is_header) {
      cur_y -= row_h;
      float sep_color[4] = {0.5f, 0.5f, 0.5f, 0.4f};
      rctf sep_rect;
      sep_rect.xmin = x;
      sep_rect.xmax = x + content_width;
      sep_rect.ymin = cur_y - sep_h;
      sep_rect.ymax = cur_y;
      chat_ui_draw_rounded_rect(&sep_rect, 0, sep_color);
      cur_y -= sep_h;
    }
    else {
      cur_y -= row_h;
      /* Subtle row divider */
      float div_color[4] = {0.5f, 0.5f, 0.5f, 0.1f};
      rctf div_rect;
      div_rect.xmin = x;
      div_rect.xmax = x + content_width;
      div_rect.ymin = cur_y;
      div_rect.ymax = cur_y + 1.0f * scale_factor;
      chat_ui_draw_rounded_rect(&div_rect, 0, div_color);
    }

    row_idx++;
    line = (*line_end) ? line_end + 1 : line_end;
  }

  return total_height;
}

/** \} */
}  // namespace blender
