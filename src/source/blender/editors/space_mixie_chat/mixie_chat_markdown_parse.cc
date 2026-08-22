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
#include <cstdint>
#include <cstring>
#include <memory>

#include "BLI_string.h"

#include "mixie_chat_markdown_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

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

/* -------------------------------------------------------------------- */
/** \name Parsed Segment Cache
 *
 * Height calculation and drawing both run for every markdown message on
 * every redraw. Re-parsing the metadata JSON each time rebuilt a
 * MARKDOWN_MAX_SEGMENTS array (~680 KB) on the stack per call — a large
 * per-frame cost and a stack-exhaustion risk. Parsed segments are cached
 * here keyed by a hash of the JSON, with lazily heap-allocated slots.
 *
 * Main-thread only (like all chat drawing) — no locking needed.
 * \{ */

/* 24 slots so a whole conversation stays cached. With only 4 slots, any
 * chat with more than 4 markdown messages thrashed the LRU during the
 * layout pass (which measures every message), forcing a full JSON
 * re-parse of every message on every layout rebuild — i.e. every frame
 * while the agent streams. Entries hold a right-sized copy of the
 * parsed segments (one segment is ~11 KB, messages rarely exceed a
 * handful), so total cache memory scales with real content. */
#define MD_PARSE_CACHE_SLOTS 24

struct MarkdownParseCacheEntry {
  uint64_t key_hash = 0;
  size_t key_len = 0;
  int segment_count = -1; /* -1 = slot unused */
  uint64_t stamp = 0;
  std::unique_ptr<MarkdownSegment[]> segments;
};

static MarkdownParseCacheEntry g_md_parse_cache[MD_PARSE_CACHE_SLOTS];
static uint64_t g_md_parse_stamp = 0;

/* FNV-1a, also reporting the string length so hash collisions additionally
 * need a length match. A collision only risks one stale frame, not memory
 * unsafety. */
static uint64_t md_metadata_hash(const char *s, size_t *r_len)
{
  uint64_t h = 1469598103934665603ULL;
  const char *p = s;
  while (*p) {
    h = (h ^ uint64_t(uint8_t(*p))) * 1099511628211ULL;
    p++;
  }
  *r_len = size_t(p - s);
  return h;
}

const MarkdownSegment *markdown_segments_get_cached(const char *metadata_json, int *r_count)
{
  size_t len = 0;
  const uint64_t hash = md_metadata_hash(metadata_json, &len);

  MarkdownParseCacheEntry *lru = &g_md_parse_cache[0];
  for (int i = 0; i < MD_PARSE_CACHE_SLOTS; i++) {
    MarkdownParseCacheEntry &entry = g_md_parse_cache[i];
    if (entry.segment_count >= 0 && entry.key_hash == hash && entry.key_len == len) {
      entry.stamp = ++g_md_parse_stamp;
      *r_count = entry.segment_count;
      return entry.segments.get();
    }
    if (entry.stamp < lru->stamp) {
      lru = &entry;
    }
  }

  /* Miss: (re)parse into a static scratch array, then keep a copy sized
   * to the actual segment count so slot memory scales with real content
   * instead of a fixed MARKDOWN_MAX_SEGMENTS array per slot. Drawing is
   * main-thread only, so the shared scratch is safe. Parse failures are
   * cached too (count 0) so malformed JSON isn't re-parsed every frame. */
  static MarkdownSegment scratch[MARKDOWN_MAX_SEGMENTS];
  const int count = parse_markdown_segments(metadata_json, scratch, MARKDOWN_MAX_SEGMENTS);
  if (count > 0) {
    lru->segments = std::make_unique<MarkdownSegment[]>(size_t(count));
    memcpy(lru->segments.get(), scratch, sizeof(MarkdownSegment) * size_t(count));
  }
  else {
    lru->segments.reset();
  }
  lru->segment_count = count;
  lru->key_hash = hash;
  lru->key_len = len;
  lru->stamp = ++g_md_parse_stamp;
  *r_count = lru->segment_count;
  return lru->segments.get();
}

/** \} */
}  // namespace blender
