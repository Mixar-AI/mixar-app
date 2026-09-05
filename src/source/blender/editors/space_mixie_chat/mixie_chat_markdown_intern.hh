/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Internal types and declarations shared between markdown parse and render files.
 */

#pragma once

/* Maximum segments to parse from JSON - keep small to avoid stack overflow */
#define MARKDOWN_MAX_SEGMENTS 64
/* Maximum list items per list segment */
#define MARKDOWN_MAX_LIST_ITEMS 10
/* Maximum text length per segment */
#define MARKDOWN_MAX_TEXT_LEN 8192

/* Table rendering limits */
#define MARKDOWN_TABLE_MAX_COLS 12
#define MARKDOWN_TABLE_MAX_ROWS 30

enum MarkdownSegmentType {
  MD_SEGMENT_PARAGRAPH = 0,
  MD_SEGMENT_HEADING,
  MD_SEGMENT_CODE_BLOCK,
  MD_SEGMENT_LIST,
  MD_SEGMENT_QUOTE,
  MD_SEGMENT_HR,
  MD_SEGMENT_NEWLINE,
  MD_SEGMENT_TABLE,
};

struct MarkdownSegment {
  MarkdownSegmentType type;
  char text[MARKDOWN_MAX_TEXT_LEN];
  int heading_level;
  char lang[64];
  bool ordered;
  int start_index;           /* For ordered lists: starting number */
  char items[MARKDOWN_MAX_LIST_ITEMS][256];
  int item_count;
};

/**
 * Parse markdown_segments array from metadata JSON.
 * Returns number of segments parsed, or 0 on error.
 */
int parse_markdown_segments(const char *metadata_json,
                            MarkdownSegment *segments,
                            int max_segments);

/**
 * Cached variant keyed on the metadata JSON (LRU, main-thread only —
 * mixie_chat_markdown_parse.cc). The returned pointer is valid until the
 * entry is evicted; consume it before the next cache access.
 */
const MarkdownSegment *markdown_segments_get_cached(const char *metadata_json, int *r_count);

/**
 * Table segment rendering (mixie_chat_table.cc).
 * Table text is tab-delimited columns, newline-delimited rows.
 * First row is always the header.
 */
float chat_ui_calc_table_height(const MarkdownSegment *seg,
                                 const struct ChatBubbleStyle *style,
                                 float content_width,
                                 float scale_factor);
float chat_ui_draw_table(const MarkdownSegment *seg,
                          float x,
                          float y,
                          float content_width,
                          const struct ChatBubbleStyle *style,
                          float scale_factor);
