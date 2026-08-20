/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Thinking bubble rendering with FIFO line-limiting.
 * Displays only the last 4 visual lines of thinking text,
 * with older content scrolling off as new text arrives.
 */

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"

#include "BLF_api.hh"

#include "MEM_guardedalloc.h"

#include "UI_interface.hh"

#include "mixie_chat_intern.hh"
#include "mixie_chat_ui_types.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* Maximum visible lines in thinking bubble */
#define THINKING_BUBBLE_MAX_LINES 4

/* Gradient circle spinner characters */
static const char *g_thinking_spinners[] = {"◐", "◓", "◑", "◒"};
#define THINKING_SPINNER_COUNT 4

/* -------------------------------------------------------------------- */
/** \name Visual Line Counting
 * \{ */

/**
 * Get the number of visual lines text will occupy at a given wrap width.
 * Uses BLF word wrap and bounding box calculation.
 */
static int get_visual_line_count(const char *text, float wrap_width, int font_size)
{
  if (!text || text[0] == '\0') {
    return 0;
  }

  const int font_id = BLF_default();
  BLF_size(font_id, font_size);
  BLF_enable(font_id, BLF_WORD_WRAP);
  BLF_wordwrap(font_id, int(wrap_width));

  rcti bbox;
  BLF_boundbox(font_id, text, strlen(text), &bbox);
  int text_height = BLI_rcti_size_y(&bbox);
  int line_height = BLF_height_max(font_id);

  BLF_disable(font_id, BLF_WORD_WRAP);

  if (line_height <= 0) {
    return 1;
  }

  /* Ceiling division to count lines */
  return (text_height + line_height - 1) / line_height;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name FIFO Text Truncation
 * \{ */

/**
 * Find the character offset where the last N visual lines begin.
 * Uses binary search with BLF text measurement for efficiency.
 *
 * \param text: Full text to analyze
 * \param wrap_width: Width for word wrapping
 * \param font_size: Font size for text measurement
 * \param max_lines: Maximum number of lines to keep (default 4)
 * \return Character offset to start rendering from (0 = show all)
 */
static int find_visible_text_offset(const char *text,
                                    float wrap_width,
                                    int font_size,
                                    int max_lines)
{
  if (!text || text[0] == '\0') {
    return 0;
  }

  int total_lines = get_visual_line_count(text, wrap_width, font_size);
  if (total_lines <= max_lines) {
    return 0; /* All text fits, no truncation needed */
  }

  int len = int(strlen(text));
  if (len == 0) {
    return 0;
  }

  /* Binary search for the offset where remaining text fits in max_lines */
  int low = 0;
  int high = len;
  int best_offset = 0;

  while (low < high) {
    int mid = (low + high) / 2;

    /* Measure lines from mid onwards */
    int remaining_lines = get_visual_line_count(text + mid, wrap_width, font_size);

    if (remaining_lines > max_lines) {
      /* Still too many lines, need to skip more */
      low = mid + 1;
    }
    else {
      /* Fits or equals max_lines - this could be our answer */
      best_offset = mid;
      high = mid;
    }
  }

  /* Snap to word boundary - find next space or newline after offset */
  while (best_offset < len && text[best_offset] != ' ' && text[best_offset] != '\n') {
    best_offset++;
  }

  /* Skip the space/newline to start at the actual word */
  if (best_offset < len && (text[best_offset] == ' ' || text[best_offset] == '\n')) {
    best_offset++;
  }

  return best_offset;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Ephemeral Bubble API
 * \{ */

const char *chat_ui_loader_status_text(const LoaderSlotData *loader,
                                       bool has_loader,
                                       const char *fallback)
{
  if (has_loader && loader && loader->text_count > 0 && loader->current_text_index >= 0 &&
      loader->current_text_index < loader->text_count)
  {
    return loader->texts[loader->current_text_index];
  }
  return fallback;
}

/* Wrapped height of a "◐ <status>" line at content_width, min one line.
 * Backend loader strings can exceed one line (especially in the narrow agent
 * bubble window), so the status must WRAP — never truncate. Measured with a
 * fixed spinner glyph: the four frames are same-advance circle variants, so
 * the height matches whichever frame the draw pass uses. MUST stay in sync
 * between the calc and draw functions below. */
static float status_line_wrapped_height(const ChatBubbleStyle *style,
                                        const char *status_message,
                                        float content_width)
{
  const int font_id = BLF_default();
  BLF_size(font_id, style->font_size);
  const float line_height = float(BLF_height_max(font_id));

  char line[512];
  snprintf(line, sizeof(line), "%s %s", g_thinking_spinners[0], status_message);
  float w, h;
  chat_ui_calc_text_bounds(line, content_width, style->font_size, 0, &w, &h);
  return std::max(h, line_height);
}

/**
 * Calculate height for ephemeral bubble with status line.
 * Layout identical to thinking: status line (wrapped) + gap (0.5 line) +
 * content (4 lines).
 */
float chat_ui_calc_ephemeral_bubble_height(const ChatBubbleStyle *style,
                                           const char *status_text,
                                           float content_width)
{
  const int font_id = BLF_default();
  BLF_size(font_id, style->font_size);

  int line_height = BLF_height_max(font_id);

  float status_height = status_line_wrapped_height(style, status_text, content_width);
  float gap = float(line_height) * 0.5f;
  float content_height = float(line_height * THINKING_BUBBLE_MAX_LINES);

  return status_height + gap + content_height + style->v_padding * 2.0f;
}

/**
 * Draw an ephemeral bubble with loader/status on top and FIFO 4-line scrolling text below.
 *
 * \param style: Bubble style configuration
 * \param ephemeral_text: Full ephemeral text (may be longer than 4 lines)
 * \param loader: Loader slot data with rotating texts (may be nullptr)
 * \param has_loader: Whether loader is active
 * \param x: Bubble X position
 * \param y: Bubble Y position (bottom-left)
 * \param bubble_width: Total bubble width
 * \param bubble_height: Total bubble height
 * \param content_width: Text content width (bubble_width - h_padding * 2)
 */
void chat_ui_draw_ephemeral_bubble(const ChatBubbleStyle *style,
                                   const char *ephemeral_text,
                                   const LoaderSlotData *loader,
                                   bool has_loader,
                                   float x,
                                   float y,
                                   float bubble_width,
                                   float bubble_height,
                                   float content_width)
{
  /* Flat block: no filled card — a hairline divider at the top separates the
   * thinking section from the prose above, consistent with the steps block.
   * LIVE rail: this block streams right now, so it carries the one accent. */
  rctf bubble_rect;
  bubble_rect.xmin = x;
  bubble_rect.xmax = x + bubble_width;
  bubble_rect.ymin = y;
  bubble_rect.ymax = y + bubble_height;

  const float live_accent[4] = CHAT_ACCENT_LIVE;
  chat_ui_draw_accent_bar(x, bubble_rect.ymin, bubble_height, live_accent,
                          UI_SCALE_FAC);

  /* Get font metrics */
  const int font_id = BLF_default();
  BLF_size(font_id, style->font_size);
  int line_height = BLF_height_max(font_id);

  /* Build status line: spinner + loader text or "Processing..." fallback */
  int spinner_frame = 0;
  if (has_loader && loader) {
    spinner_frame = loader->spinner_frame;
  }
  /* Clamp negative frames: C's `%` keeps the sign, so a stale/negative RNA
   * value would index before the start of g_thinking_spinners. */
  int spinner_idx = spinner_frame % THINKING_SPINNER_COUNT;
  if (spinner_idx < 0) {
    spinner_idx += THINKING_SPINNER_COUNT;
  }
  const char *spinner_char = g_thinking_spinners[spinner_idx];

  const char *status_message = chat_ui_loader_status_text(loader, has_loader, "Processing...");

  char status_line[512];
  snprintf(status_line, sizeof(status_line), "%s %s", spinner_char, status_message);

  /* Calculate layout heights. The status wraps (long backend loader strings)
   * — height mirrors chat_ui_calc_ephemeral_bubble_height. */
  float status_line_height = status_line_wrapped_height(style, status_message, content_width);
  float gap = float(line_height) * 0.5f;

  /* Draw status line at top (bright color) */
  float status_y = y + bubble_height - style->v_padding - status_line_height;
  rctf status_rect;
  status_rect.xmin = x + style->h_padding;
  status_rect.xmax = x + style->h_padding + content_width;
  status_rect.ymin = status_y;
  status_rect.ymax = status_y + status_line_height;

  chat_ui_draw_text_wrapped(status_line, &status_rect, style->font_size, 0, style->text_color);

  /* Find offset for last 4 lines of ephemeral content (FIFO) */
  int offset = find_visible_text_offset(
      ephemeral_text, content_width, style->font_size, THINKING_BUBBLE_MAX_LINES);

  const char *display_text = ephemeral_text + offset;

  /* Draw ephemeral content below status line (dimmed, 60% alpha) */
  if (display_text && display_text[0] != '\0') {
    float dimmed_color[4];
    dimmed_color[0] = style->text_color[0];
    dimmed_color[1] = style->text_color[1];
    dimmed_color[2] = style->text_color[2];
    dimmed_color[3] = style->text_color[3] * 0.6f;

    float content_top = status_y - gap;
    rctf text_rect;
    text_rect.xmin = x + style->h_padding;
    text_rect.xmax = x + style->h_padding + content_width;
    text_rect.ymin = y + style->v_padding;
    text_rect.ymax = content_top;

    chat_ui_draw_text_wrapped(display_text, &text_rect, style->font_size, 0, dimmed_color);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Live Thinking Line (compact, evolving)
 * \{ */

float chat_ui_calc_live_thinking_height(const ChatBubbleStyle *style,
                                        const char *status_text,
                                        float content_width)
{
  return status_line_wrapped_height(style, status_text, content_width) +
         style->v_padding * 2.0f;
}

void chat_ui_draw_live_thinking(const ChatBubbleStyle *style,
                                const char *thinking_text,
                                int spinner_frame,
                                float x,
                                float y,
                                float bubble_width,
                                float bubble_height,
                                float content_width)
{
  (void)bubble_width;
  /* LIVE rail: narration is streaming — the one accent marks it. */
  const float live_accent[4] = CHAT_ACCENT_LIVE;
  chat_ui_draw_accent_bar(x, y, bubble_height, live_accent, UI_SCALE_FAC);

  const int font_id = BLF_default();
  BLF_size(font_id, style->font_size);

  const char *spinner = g_thinking_spinners[spinner_frame % THINKING_SPINNER_COUNT];

  /* Full status, wrapped — never truncated. The block height was sized from
   * the same text (chat_ui_calc_live_thinking_height), so the whole line
   * always fits. */
  char line[640];
  BLI_snprintf(line, sizeof(line), "%s %s", spinner, thinking_text);

  float col[4] = {style->text_color[0], style->text_color[1],
                  style->text_color[2], style->text_color[3] * 0.8f};
  rctf line_rect;
  line_rect.xmin = x + style->h_padding;
  line_rect.xmax = x + style->h_padding + content_width;
  line_rect.ymax = y + bubble_height - style->v_padding;
  line_rect.ymin = y + style->v_padding;
  chat_ui_draw_text_wrapped(line, &line_rect, style->font_size, 0, col);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Finalized Thinking Dropdown
 * \{ */

float chat_ui_calc_thinking_dropdown_height(const ChatBubbleStyle *style,
                                            const char *thinking_text,
                                            bool collapsed,
                                            float content_width)
{
  const int font_id = BLF_default();
  BLF_size(font_id, style->font_size);
  float line_height = float(BLF_height_max(font_id));

  /* Collapsed: just the "Thought for Ns" header line. */
  float height = line_height + style->v_padding * 2.0f;
  if (collapsed || !thinking_text || thinking_text[0] == '\0') {
    return height;
  }

  /* Expanded: header + gap + full reasoning text, indented under the header
   * label (width MUST match chat_ui_draw_thinking_dropdown). */
  float tw, th;
  chat_ui_calc_text_bounds(thinking_text, content_width - chat_ui_chevron_indent(),
                           style->font_size, 0, &tw, &th);
  height += float(line_height) * 0.5f + th;
  return height;
}

void chat_ui_draw_thinking_dropdown(const ChatBubbleStyle *style,
                                    const char *thinking_text,
                                    bool collapsed,
                                    int duration_ms,
                                    float x,
                                    float y,
                                    float bubble_width,
                                    float bubble_height,
                                    float content_width,
                                    rctf *out_header_bounds)
{
  rctf rect;
  rect.xmin = x;
  rect.xmax = x + bubble_width;
  rect.ymin = y;
  rect.ymax = y + bubble_height;
  /* Flat: hairline top divider instead of a filled card. */
  const float think_accent[4] = CHAT_ACCENT_THINKING;
  chat_ui_draw_accent_bar(x, rect.ymin, bubble_height, think_accent, UI_SCALE_FAC);

  const int font_id = BLF_default();
  BLF_size(font_id, style->font_size);
  float line_height = float(BLF_height_max(font_id));

  /* Header: chevron icon + "Thought for Ns" (muted — secondary UI). */
  int secs = (duration_ms + 500) / 1000; /* round to nearest second */
  if (secs < 1) {
    secs = 1;
  }
  char header[128];
  BLI_snprintf(header, sizeof(header), "Thought for %ds", secs);

  const float chevron_indent = chat_ui_chevron_indent();
  float header_top = rect.ymax - style->v_padding;
  float header_y = header_top - line_height;

  /* 0.65 matches the steps-block header — same secondary-caption role. */
  float dim[4] = {style->text_color[0], style->text_color[1],
                  style->text_color[2], style->text_color[3] * 0.65f};
  /* Chevron on the header text's first-line visual center (the text draw
   * bottom-aligns its ink box; the geometric line center reads high). */
  const float header_center = chat_ui_wrapped_first_line_center(
      style->font_size, header, content_width - chevron_indent, header_y);
  chat_ui_draw_chevron(x + style->h_padding, header_center, collapsed, dim);

  rctf header_rect;
  header_rect.xmin = x + style->h_padding + chevron_indent;
  header_rect.xmax = x + style->h_padding + content_width;
  header_rect.ymin = header_y;
  header_rect.ymax = header_top;
  chat_ui_draw_text_wrapped(header, &header_rect, style->font_size, 0, dim);

  if (out_header_bounds) {
    /* Full card width; include the vertical padding (the whole collapsed
     * card is one click target). */
    out_header_bounds->xmin = x;
    out_header_bounds->xmax = x + bubble_width;
    out_header_bounds->ymin = collapsed ? rect.ymin : header_y;
    out_header_bounds->ymax = rect.ymax;
  }

  if (collapsed || !thinking_text || thinking_text[0] == '\0') {
    return;
  }

  /* Expanded reasoning body (dimmed further), indented under the header
   * label so it reads as the chevron's disclosure content. */
  /* 0.6 matches the steps-block detail body — same disclosure-body role. */
  float body_dim[4] = {style->text_color[0], style->text_color[1],
                       style->text_color[2], style->text_color[3] * 0.6f};
  rctf body_rect;
  body_rect.xmin = x + style->h_padding + chevron_indent;
  body_rect.xmax = x + style->h_padding + content_width;
  body_rect.ymin = y + style->v_padding;
  body_rect.ymax = header_y - float(line_height) * 0.5f;
  chat_ui_draw_text_wrapped(thinking_text, &body_rect, style->font_size, 0, body_dim);
}

/** \} */
}  // namespace blender
