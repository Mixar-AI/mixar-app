/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * JSON parsing for markdown segments in chat message metadata.
 * Minimal hand-rolled parser — avoids external JSON dependencies.
 */

#include <climits>
#include <cstring>

#include "BLI_string.h"

#include "mixie_chat_markdown_intern.hh"

/* -------------------------------------------------------------------- */
/** \name JSON Parsing Helpers
 * \{ */

static const char *skip_whitespace(const char *ptr)
{
  while (*ptr && (*ptr == ' ' || *ptr == '\t' || *ptr == '\n' || *ptr == '\r')) {
    ptr++;
  }
  return ptr;
}

static const char *extract_json_string(const char *ptr, char *out, int max_len)
{
  if (!ptr || !out || max_len <= 0) {
    if (out && max_len > 0) {
      out[0] = '\0';
    }
    return ptr;
  }

  if (*ptr != '"') {
    out[0] = '\0';
    return ptr;
  }
  ptr++;

  int i = 0;
  while (*ptr && *ptr != '"' && i < max_len - 1) {
    if (*ptr == '\\' && *(ptr + 1)) {
      ptr++;
      switch (*ptr) {
        case 'n':
          out[i++] = '\n';
          break;
        case 't':
          out[i++] = '\t';
          break;
        case 'r':
          out[i++] = '\r';
          break;
        case '"':
          out[i++] = '"';
          break;
        case '\\':
          out[i++] = '\\';
          break;
        default:
          out[i++] = *ptr;
          break;
      }
    }
    else {
      out[i++] = *ptr;
    }
    ptr++;
  }
  out[i] = '\0';

  /* If we stopped due to buffer full (not end-of-string or closing quote),
   * we must still advance past the closing quote so the caller doesn't
   * misparse remaining string content as JSON structure. */
  if (*ptr && *ptr != '"') {
    while (*ptr && *ptr != '"') {
      if (*ptr == '\\' && *(ptr + 1)) {
        ptr++; /* skip escaped char */
      }
      ptr++;
    }
  }

  if (*ptr == '"') {
    ptr++;
  }
  return ptr;
}

static const char *extract_json_int(const char *ptr, int *out)
{
  *out = 0;
  bool negative = false;

  if (*ptr == '-') {
    negative = true;
    ptr++;
  }

  while (*ptr >= '0' && *ptr <= '9') {
    /* Saturate instead of overflowing: the metadata JSON is backend-supplied,
     * and a long digit run would be signed-integer-overflow UB. */
    if (*out > (INT_MAX - (*ptr - '0')) / 10) {
      *out = INT_MAX;
      while (*ptr >= '0' && *ptr <= '9') {
        ptr++;
      }
      break;
    }
    *out = *out * 10 + (*ptr - '0');
    ptr++;
  }

  if (negative) {
    *out = -*out;
  }
  return ptr;
}

static const char *extract_json_bool(const char *ptr, bool *out)
{
  if (strncmp(ptr, "true", 4) == 0) {
    *out = true;
    return ptr + 4;
  }
  if (strncmp(ptr, "false", 5) == 0) {
    *out = false;
    return ptr + 5;
  }
  return ptr;
}

/**
 * Search for a JSON key within a bounded region [json, json_end).
 * If json_end is nullptr, search is unbounded (original behavior).
 * This prevents strstr from matching keys in subsequent JSON objects.
 */
static const char *find_json_key_bounded(const char *json,
                                          const char *json_end,
                                          const char *key)
{
  char search_key[128];
  BLI_snprintf(search_key, sizeof(search_key), "\"%s\"", key);
  size_t key_len = strlen(search_key);

  const char *search_from = json;
  while (true) {
    const char *found = strstr(search_from, search_key);
    if (!found) {
      return nullptr;
    }
    if (json_end && found >= json_end) {
      return nullptr;
    }

    found += key_len;
    if (json_end && found >= json_end) {
      return nullptr;
    }
    found = skip_whitespace(found);
    if (json_end && found >= json_end) {
      return nullptr;
    }

    if (*found == ':') {
      found++;
      found = skip_whitespace(found);
      if (json_end && found >= json_end) {
        return nullptr;
      }
      return found;
    }
    /* Not a real key (matched inside a string value), try next occurrence */
    search_from = found;
  }
}

static const char *find_json_key(const char *json, const char *key)
{
  return find_json_key_bounded(json, nullptr, key);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Segment Parsing
 * \{ */

static const char *parse_segment(const char *ptr, MarkdownSegment *seg)
{
  memset(seg, 0, sizeof(*seg));
  seg->type = MD_SEGMENT_PARAGRAPH;

  if (*ptr != '{') {
    return nullptr;
  }
  ptr++;

  /* Find the closing '}' of this segment, properly skipping strings,
   * nested objects, and arrays so that '{', '}', '[', ']' inside
   * JSON string values don't corrupt the depth tracking. */
  int brace_depth = 1;
  const char *end = ptr;
  while (*end && brace_depth > 0) {
    if (*end == '"') {
      /* Skip over JSON string value to avoid false brace/bracket matches */
      end++;
      while (*end && *end != '"') {
        if (*end == '\\' && *(end + 1)) {
          end++; /* skip escaped char */
        }
        end++;
      }
      if (*end == '"') {
        end++;
      }
      continue;
    }
    if (*end == '{')
      brace_depth++;
    else if (*end == '}')
      brace_depth--;
    else if (*end == '[') {
      int bracket_depth = 1;
      end++;
      while (*end && bracket_depth > 0) {
        if (*end == '"') {
          /* Skip strings inside arrays too */
          end++;
          while (*end && *end != '"') {
            if (*end == '\\' && *(end + 1)) {
              end++;
            }
            end++;
          }
          if (*end == '"') {
            end++;
          }
          continue;
        }
        if (*end == '[')
          bracket_depth++;
        else if (*end == ']')
          bracket_depth--;
        end++;
      }
      continue;
    }
    end++;
  }

  /* Use bounded key lookup to prevent matching keys in other segments */
  const char *type_ptr = find_json_key_bounded(ptr, end, "type");
  if (type_ptr) {
    char type_str[64];
    extract_json_string(type_ptr, type_str, sizeof(type_str));

    if (strcmp(type_str, "paragraph") == 0) {
      seg->type = MD_SEGMENT_PARAGRAPH;
    }
    else if (strcmp(type_str, "heading") == 0) {
      seg->type = MD_SEGMENT_HEADING;
    }
    else if (strcmp(type_str, "code_block") == 0) {
      seg->type = MD_SEGMENT_CODE_BLOCK;
    }
    else if (strcmp(type_str, "list") == 0) {
      seg->type = MD_SEGMENT_LIST;
    }
    else if (strcmp(type_str, "quote") == 0) {
      seg->type = MD_SEGMENT_QUOTE;
    }
    else if (strcmp(type_str, "hr") == 0) {
      seg->type = MD_SEGMENT_HR;
    }
    else if (strcmp(type_str, "newline") == 0) {
      seg->type = MD_SEGMENT_NEWLINE;
    }
    else if (strcmp(type_str, "table") == 0) {
      seg->type = MD_SEGMENT_TABLE;
    }
  }

  const char *text_ptr = find_json_key_bounded(ptr, end, "text");
  if (text_ptr) {
    extract_json_string(text_ptr, seg->text, sizeof(seg->text));
  }

  const char *level_ptr = find_json_key_bounded(ptr, end, "level");
  if (level_ptr) {
    extract_json_int(level_ptr, &seg->heading_level);
  }

  const char *lang_ptr = find_json_key_bounded(ptr, end, "lang");
  if (lang_ptr && *lang_ptr == '"') {
    extract_json_string(lang_ptr, seg->lang, sizeof(seg->lang));
  }

  const char *ordered_ptr = find_json_key_bounded(ptr, end, "ordered");
  if (ordered_ptr) {
    extract_json_bool(ordered_ptr, &seg->ordered);
  }

  /* Parse list start index (for ordered lists) */
  const char *start_ptr = find_json_key_bounded(ptr, end, "start");
  if (start_ptr) {
    extract_json_int(start_ptr, &seg->start_index);
  }
  else {
    seg->start_index = 1;
  }

  const char *items_ptr = find_json_key_bounded(ptr, end, "items");
  if (items_ptr && *items_ptr == '[') {
    items_ptr++;
    seg->item_count = 0;

    while (*items_ptr && seg->item_count < MARKDOWN_MAX_LIST_ITEMS) {
      items_ptr = skip_whitespace(items_ptr);
      if (*items_ptr == ']')
        break;
      if (*items_ptr == ',') {
        items_ptr++;
        continue;
      }
      if (*items_ptr == '"') {
        items_ptr = extract_json_string(items_ptr, seg->items[seg->item_count], 256);
        seg->item_count++;
      }
      else {
        items_ptr++;
      }
    }
  }

  return end;
}

int parse_markdown_segments(const char *metadata_json,
                            MarkdownSegment *segments,
                            int max_segments)
{
  if (!metadata_json || !segments || max_segments <= 0) {
    return 0;
  }

  const size_t json_len = strlen(metadata_json);
  if (json_len == 0 || json_len > 1000000) {
    return 0;
  }

  const char *json_end = metadata_json + json_len;

  const char *segments_ptr = find_json_key(metadata_json, "markdown_segments");
  if (!segments_ptr || *segments_ptr != '[') {
    return 0;
  }

  segments_ptr++;
  int count = 0;
  int iterations = 0;
  const int max_iterations = 10000;

  while (*segments_ptr && count < max_segments && segments_ptr < json_end) {
    if (++iterations > max_iterations) {
      return 0;
    }

    segments_ptr = skip_whitespace(segments_ptr);
    if (!segments_ptr || segments_ptr >= json_end) {
      break;
    }

    if (*segments_ptr == ']')
      break;
    if (*segments_ptr == ',') {
      segments_ptr++;
      continue;
    }
    if (*segments_ptr == '{') {
      const char *prev_ptr = segments_ptr;
      segments_ptr = parse_segment(segments_ptr, &segments[count]);
      if (segments_ptr && segments_ptr > prev_ptr && segments_ptr <= json_end) {
        count++;
      }
      else {
        break;
      }
    }
    else {
      segments_ptr++;
    }
  }

  return count;
}

/** \} */
