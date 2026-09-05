/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Markdown segment rendering for chat messages.
 * Calculates height and draws each segment type with appropriate styling.
 */

#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>

#include "BLI_string.h"

#include "BLF_api.hh"

#include "mixie_chat_intern.hh"
#include "mixie_chat_markdown_intern.hh"
#include "mixie_chat_ui_types.hh"

/* Parsed-segment cache lives in mixie_chat_markdown_parse.cc
 * (markdown_segments_get_cached in mixie_chat_markdown_intern.hh). */

/* -------------------------------------------------------------------- */
/** \name Segment Height Calculation
 * \{ */

/* Header row of a code card (language label + Copy button). ALWAYS reserved
 * — even without a language tag — so the Copy button never overlaps the
 * first code line. Must match between calc_segment_height, draw_code_block
 * and nothing else. */
static float code_block_header_height(const ChatBubbleStyle *style, float scale_factor)
{
  return float(style->font_size) + 10.0f * scale_factor;
}

static float calc_segment_height(const MarkdownSegment *seg,
                                 const ChatBubbleStyle *style,
                                 float content_width,
                                 float scale_factor)
{
  float text_width, text_height;
  int font_size = style->font_size;

  /* A zero-origin probe rect: chat_ui_rich_text only uses the width for
   * wrapping in the measure pass, so the y values are irrelevant here. */
  rctf probe;
  probe.xmin = 0.0f;
  probe.ymin = 0.0f;
  probe.ymax = 0.0f;

  switch (seg->type) {
    case MD_SEGMENT_PARAGRAPH: {
      probe.xmax = content_width;
      float h = chat_ui_rich_text(
          seg->text, &probe, font_size, 0, style->text_color, scale_factor, false, nullptr);
      return h + 8.0f * scale_factor;
    }

    case MD_SEGMENT_HEADING: {
      /* Headings are BOLD and have extra padding. */
      probe.xmax = content_width;
      float h = chat_ui_rich_text(
          seg->text, &probe, font_size, BLF_BOLD, style->text_color, scale_factor, false, nullptr);
      /* Underline bar (2) + gap (4) — must match draw_segment's HEADING case. */
      float underline_height = (seg->heading_level <= 2) ? 6.0f * scale_factor : 0;
      return h + 12.0f * scale_factor + underline_height;
    }

    case MD_SEGMENT_CODE_BLOCK: {
      float code_width = content_width - 16.0f * scale_factor;
      /* HardLimit: an unbreakable token (bpy.context.collection.objects...)
       * wraps at the card edge instead of overflowing it — MUST match
       * draw_code_block and the selection mapping. */
      chat_ui_calc_text_bounds_font(seg->text,
                                    code_width,
                                    font_size,
                                    0,
                                    chat_ui_mono_font(),
                                    &text_width,
                                    &text_height,
                                    BLFWrapMode::HardLimit);
      return text_height + 16.0f * scale_factor +
             code_block_header_height(style, scale_factor);
    }

    case MD_SEGMENT_LIST: {
      float total_height = 0;
      float item_indent = 28.0f * scale_factor;
      probe.xmax = content_width - item_indent;
      for (int i = 0; i < seg->item_count; i++) {
        float h = chat_ui_rich_text(
            seg->items[i], &probe, font_size, 0, style->text_color, scale_factor, false, nullptr);
        total_height += h + 4.0f * scale_factor;
      }
      return total_height + 8.0f * scale_factor;
    }

    case MD_SEGMENT_QUOTE: {
      /* Bar (3) + padding both sides (8*2) — must match draw_quote. */
      float quote_width = content_width - (3.0f + 16.0f) * scale_factor;
      /* Quotes are ITALIC. */
      probe.xmax = quote_width;
      float h = chat_ui_rich_text(
          seg->text, &probe, font_size, BLF_ITALIC, style->text_color, scale_factor, false, nullptr);
      return h + 16.0f * scale_factor;
    }

    case MD_SEGMENT_HR:
      /* Padding both sides (8*2) + rule (1) — must match draw_hr. */
      return 17.0f * scale_factor;

    case MD_SEGMENT_NEWLINE:
      return 12.0f * scale_factor; /* Increased newline spacing for hierarchy */

    case MD_SEGMENT_TABLE:
      return chat_ui_calc_table_height(seg, style, content_width, scale_factor);

    default:
      return 0;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Segment Drawing
 * \{ */

/* Forward declaration for theme color getter */
void chat_ui_get_button_bg_color(float out_color[4]);

static float draw_code_block(const MarkdownSegment *seg,
                             float x,
                             float y,
                             float content_width,
                             const ChatBubbleStyle *style,
                             float scale_factor)
{
  float padding = 8.0f * scale_factor;
  float code_width = content_width - padding * 2;

  float text_width, text_height;
  /* HardLimit wrap — MUST match calc_segment_height and the text draw so
   * unbreakable tokens fold at the card edge instead of overflowing it. */
  chat_ui_calc_text_bounds_font(seg->text,
                                code_width,
                                style->font_size,
                                0,
                                chat_ui_mono_font(),
                                &text_width,
                                &text_height,
                                BLFWrapMode::HardLimit);

  const float header_height = code_block_header_height(style, scale_factor);
  float block_height = text_height + padding * 2 + header_height;

  float bg_color[4];
  chat_ui_get_button_bg_color(bg_color);
  bg_color[3] = 1.0f;

  rctf code_rect;
  code_rect.xmin = x;
  code_rect.xmax = x + content_width;
  code_rect.ymin = y - block_height;
  code_rect.ymax = y;

  chat_ui_draw_rounded_rect(&code_rect, 4.0f * scale_factor, bg_color);

  /* Header row: language label on the left, Copy button on the right. The
   * row is always reserved (code_block_header_height) so the button never
   * sits on top of code. */
  float text_y = y - padding;
  if (seg->lang[0]) {
    float label_color[4] = {0.6f, 0.6f, 0.6f, 1.0f};
    chat_ui_draw_label(seg->lang, x + padding, text_y - 12.0f * scale_factor,
                       int(style->font_size * 0.8f), 0, label_color, false);
  }
  text_y -= header_height;

  rctf text_rect;
  text_rect.xmin = x + padding;
  text_rect.xmax = x + content_width - padding;
  text_rect.ymin = code_rect.ymin + padding;
  text_rect.ymax = text_y;

  chat_ui_draw_text_wrapped_font(seg->text,
                                 &text_rect,
                                 style->font_size,
                                 0,
                                 chat_ui_mono_font(),
                                 style->text_color,
                                 BLFWrapMode::HardLimit);

  /* Selection maps against this exact rect/font/wrap. */
  mixie_chat_md_seg_record(&text_rect, /*mono=*/true, style->font_size);

  /* Copy button in the card's header row (drawn over the card, after the
   * text). No-op unless the messages pass activated the hit collector. */
  mixie_chat_code_chip_draw(code_rect.xmax, code_rect.ymax, scale_factor, style->font_size);

  return block_height;
}

static float draw_quote(const MarkdownSegment *seg,
                        float x,
                        float y,
                        float content_width,
                        const ChatBubbleStyle *style,
                        float scale_factor)
{
  float bar_width = 3.0f * scale_factor;
  float padding = 8.0f * scale_factor;
  float quote_width = content_width - bar_width - padding * 2;

  float quote_text_color[4];
  quote_text_color[0] = style->text_color[0] * 0.85f;
  quote_text_color[1] = style->text_color[1] * 0.85f;
  quote_text_color[2] = style->text_color[2] * 0.85f;
  quote_text_color[3] = style->text_color[3];

  /* Measure with the SAME width used for drawing so height is exact. */
  rctf measure;
  measure.xmin = 0.0f;
  measure.xmax = quote_width;
  measure.ymin = 0.0f;
  measure.ymax = 0.0f;
  float text_height = chat_ui_rich_text(
      seg->text, &measure, style->font_size, BLF_ITALIC, quote_text_color, scale_factor, false, nullptr);

  float block_height = text_height + padding * 2;

  float bar_color[4] = {0.4f, 0.5f, 0.7f, 0.8f};
  rctf bar_rect;
  bar_rect.xmin = x;
  bar_rect.xmax = x + bar_width;
  bar_rect.ymin = y - block_height;
  bar_rect.ymax = y;

  chat_ui_draw_rounded_rect(&bar_rect, 1.0f, bar_color);

  rctf text_rect;
  text_rect.xmin = x + bar_width + padding;
  text_rect.xmax = text_rect.xmin + quote_width;
  text_rect.ymin = y - block_height + padding;
  text_rect.ymax = y - padding;

  chat_ui_rich_text(
      seg->text, &text_rect, style->font_size, BLF_ITALIC, quote_text_color, scale_factor, true, nullptr);

  mixie_chat_md_seg_record(&text_rect, /*mono=*/false, style->font_size);

  return block_height;
}

static float draw_list(const MarkdownSegment *seg,
                       float x,
                       float y,
                       float content_width,
                       const ChatBubbleStyle *style,
                       float scale_factor)
{
  float total_height = 0;
  float item_indent = 28.0f * scale_factor;
  float item_spacing = 4.0f * scale_factor;
  float current_y = y;

  for (int i = 0; i < seg->item_count; i++) {
    char prefix[16];
    if (seg->ordered) {
      BLI_snprintf(prefix, sizeof(prefix), "%d. ", i + seg->start_index);
    }
    else {
      BLI_strncpy(prefix, "\xE2\x80\xA2", sizeof(prefix));
    }

    /* Align the bullet/number to the SAME baseline chat_ui_rich_text uses for
     * its first line: baseline = line_top - ascender. Using the real BLF
     * ascender (not an 0.8 approximation) keeps "1." level with the text. */
    const int list_font = BLF_default();
    BLF_size(list_font, style->font_size);
    float bullet_y = current_y - float(BLF_ascender(list_font));
    chat_ui_draw_label(prefix, x + 4.0f * scale_factor, bullet_y, style->font_size, 0,
                       style->text_color, false);

    rctf text_rect;
    text_rect.xmin = x + item_indent;
    text_rect.xmax = x + content_width;
    text_rect.ymin = current_y - 100000.0f;
    text_rect.ymax = current_y;

    float text_height = chat_ui_rich_text(seg->items[i], &text_rect, style->font_size, 0,
                                          style->text_color, scale_factor, true, nullptr);

    float item_height = text_height + item_spacing;
    current_y -= item_height;
    total_height += item_height;
  }

  /* Trailing gap must match calc_segment_height's LIST case (+8). */
  return total_height + 8.0f * scale_factor;
}

static float draw_hr(float x, float y, float content_width, float scale_factor)
{
  float hr_height = 1.0f * scale_factor;
  float padding = 8.0f * scale_factor;

  float hr_color[4] = {0.5f, 0.5f, 0.5f, 0.5f};
  rctf hr_rect;
  hr_rect.xmin = x;
  hr_rect.xmax = x + content_width;
  hr_rect.ymin = y - padding - hr_height;
  hr_rect.ymax = y - padding;

  chat_ui_draw_rounded_rect(&hr_rect, 0, hr_color);

  return padding * 2 + hr_height;
}

static float draw_segment(const MarkdownSegment *seg,
                          float x,
                          float y,
                          float content_width,
                          const ChatBubbleStyle *style,
                          float scale_factor)
{
  float text_width, text_height;

  switch (seg->type) {
    case MD_SEGMENT_PARAGRAPH: {
      rctf text_rect;
      text_rect.xmin = x;
      text_rect.xmax = x + content_width;
      text_rect.ymin = y - 100000.0f;
      text_rect.ymax = y;

      text_height = chat_ui_rich_text(seg->text, &text_rect, style->font_size, 0,
                                      style->text_color, scale_factor, true, nullptr);

      rctf sel_rect = text_rect;
      sel_rect.ymin = y - text_height;
      mixie_chat_md_seg_record(&sel_rect, /*mono=*/false, style->font_size);

      return text_height + 8.0f * scale_factor;
    }

    case MD_SEGMENT_HEADING: {
      float heading_color[4];
      heading_color[0] = fminf(style->text_color[0] * 1.1f, 1.0f);
      heading_color[1] = fminf(style->text_color[1] * 1.1f, 1.0f);
      heading_color[2] = fminf(style->text_color[2] * 1.1f, 1.0f);
      heading_color[3] = style->text_color[3];

      rctf text_rect;
      text_rect.xmin = x;
      text_rect.xmax = x + content_width;
      text_rect.ymin = y - 100000.0f;
      text_rect.ymax = y;

      /* Headings are BOLD; capture the widest line for the underline. */
      text_height = chat_ui_rich_text(seg->text, &text_rect, style->font_size, BLF_BOLD,
                                      heading_color, scale_factor, true, &text_width);

      rctf sel_rect = text_rect;
      sel_rect.ymin = y - text_height;
      mixie_chat_md_seg_record(&sel_rect, /*mono=*/false, style->font_size);

      float underline_height = 0;
      if (seg->heading_level <= 2) {
        underline_height = 2.0f * scale_factor;
        rctf underline_rect;
        underline_rect.xmin = x;
        underline_rect.xmax = x + text_width;
        underline_rect.ymin = (y - text_height) - 4.0f * scale_factor;
        underline_rect.ymax = underline_rect.ymin + underline_height;
        chat_ui_draw_rounded_rect(&underline_rect, 0, heading_color);
        underline_height += 4.0f * scale_factor;
      }

      return text_height + 12.0f * scale_factor + underline_height;
    }

    case MD_SEGMENT_CODE_BLOCK:
      return draw_code_block(seg, x, y, content_width, style, scale_factor);

    case MD_SEGMENT_LIST:
      return draw_list(seg, x, y, content_width, style, scale_factor);

    case MD_SEGMENT_QUOTE:
      return draw_quote(seg, x, y, content_width, style, scale_factor);

    case MD_SEGMENT_HR:
      return draw_hr(x, y, content_width, scale_factor);

    case MD_SEGMENT_NEWLINE:
      return 12.0f * scale_factor;

    case MD_SEGMENT_TABLE:
      return chat_ui_draw_table(seg, x, y, content_width, style, scale_factor);

    default:
      return 0;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Public API
 * \{ */

bool chat_ui_has_markdown_segments(const char *metadata_json)
{
  if (!metadata_json || metadata_json[0] == '\0') {
    return false;
  }

  const char *key = strstr(metadata_json, "\"markdown_segments\"");
  if (!key) {
    return false;
  }

  const char *arr_start = strstr(key, "[");
  if (!arr_start) {
    return false;
  }

  arr_start++;
  while (*arr_start == ' ' || *arr_start == '\n' || *arr_start == '\t') {
    arr_start++;
  }

  if (*arr_start == ']') {
    return false;
  }

  return true;
}

float chat_ui_calc_markdown_height(const char *metadata_json,
                                   const ChatBubbleStyle *style,
                                   float content_width,
                                   float scale_factor)
{
  if (!metadata_json || !style || metadata_json[0] == '\0') {
    return 0;
  }

  if (content_width <= 0 || scale_factor <= 0) {
    return 0;
  }

  if (content_width < 10.0f) {
    return 0;
  }

  int segment_count = 0;
  const MarkdownSegment *segments = markdown_segments_get_cached(metadata_json, &segment_count);

  if (segment_count <= 0) {
    return 0;
  }

  float total_height = 0;
  for (int i = 0; i < segment_count; i++) {
    if (segments[i].type != MD_SEGMENT_HR &&
        segments[i].type != MD_SEGMENT_NEWLINE &&
        segments[i].type != MD_SEGMENT_LIST &&
        segments[i].text[0] == '\0') {
      continue;
    }
    float seg_height = calc_segment_height(&segments[i], style, content_width, scale_factor);
    if (seg_height > 0) {
      total_height += seg_height;
    }
  }

  return total_height;
}

void chat_ui_draw_markdown(const char *metadata_json,
                           float x,
                           float y,
                           float content_width,
                           const ChatBubbleStyle *style,
                           float scale_factor)
{
  if (!metadata_json || !style || metadata_json[0] == '\0') {
    return;
  }

  if (content_width <= 0 || scale_factor <= 0) {
    return;
  }

  if (content_width < 10.0f || style->font_size <= 0) {
    return;
  }

  int segment_count = 0;
  const MarkdownSegment *segments = markdown_segments_get_cached(metadata_json, &segment_count);

  if (segment_count <= 0) {
    return;
  }

  float current_y = y;
  for (int i = 0; i < segment_count; i++) {
    if (segments[i].type != MD_SEGMENT_HR &&
        segments[i].type != MD_SEGMENT_NEWLINE &&
        segments[i].type != MD_SEGMENT_LIST &&
        segments[i].text[0] == '\0') {
      continue;
    }
    /* Report the segment index so code-block copy chips can identify their
     * block (mixie_chat_code_copy.cc). Must be the PARSED index — clicks
     * re-resolve the text via chat_ui_markdown_segment_text below. */
    mixie_chat_code_hits_set_segment(i);
    float seg_height = draw_segment(&segments[i], x, current_y, content_width, style, scale_factor);
    if (seg_height > 0) {
      current_y -= seg_height;
    }
  }
  mixie_chat_code_hits_set_segment(-1);
}

const char *chat_ui_markdown_segment_text(const char *metadata_json,
                                          int seg_index,
                                          bool code_only)
{
  if (!metadata_json || metadata_json[0] == '\0' || seg_index < 0) {
    return nullptr;
  }
  int segment_count = 0;
  const MarkdownSegment *segments = markdown_segments_get_cached(metadata_json, &segment_count);
  if (seg_index >= segment_count) {
    return nullptr;
  }
  const MarkdownSegmentType type = segments[seg_index].type;
  if (code_only) {
    if (type != MD_SEGMENT_CODE_BLOCK) {
      return nullptr;
    }
  }
  else if (type != MD_SEGMENT_CODE_BLOCK && type != MD_SEGMENT_PARAGRAPH &&
           type != MD_SEGMENT_HEADING && type != MD_SEGMENT_QUOTE)
  {
    return nullptr;
  }
  return segments[seg_index].text;
}

/** \} */
