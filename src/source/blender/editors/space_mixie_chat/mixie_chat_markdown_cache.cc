/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Parsed-segment cache for chat markdown. Split out of
 * mixie_chat_markdown_parse.cc, which the cache pushed over the 500-line
 * rule; the parser there is now only the JSON reader.
 */

#include <cstdint>
#include <cstring>
#include <memory>

#include "mixie_chat_markdown_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

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
/* The layout pass touches every message, in collection order, on every
 * rebuild -- a strict cycle over the whole transcript. Strict LRU is the
 * worst possible policy for that: the moment the transcript is one message
 * longer than the cache, every single lookup evicts the entry it is about to
 * need next, and the hit rate falls off a cliff from ~99% to 0%. Measured
 * over the real access pattern at 24 slots: 24 messages 99.5%, 25 messages
 * 0.0%. Evicting a slot at random instead degrades gracefully (91.7% at 25,
 * 61.7% at 30), and a larger pool keeps ordinary conversations resident --
 * entries are right-sized copies, so an unused slot costs nothing. */
#define MD_PARSE_CACHE_SLOTS 64

struct MarkdownParseCacheEntry {
  uint64_t key_hash = 0;
  size_t key_len = 0;
  int segment_count = -1; /* -1 = slot unused */
  uint64_t stamp = 0;
  std::unique_ptr<MarkdownSegment[]> segments;
};

static MarkdownParseCacheEntry g_md_parse_cache[MD_PARSE_CACHE_SLOTS];
static uint64_t g_md_parse_stamp = 0;
static uint64_t g_md_parse_rng = 88172645463325252ULL;

/* xorshift64: a victim that does not track recency, so a cyclic scan cannot
 * systematically evict the entry it needs next. */
static uint64_t md_next_random()
{
  g_md_parse_rng ^= g_md_parse_rng << 13;
  g_md_parse_rng ^= g_md_parse_rng >> 7;
  g_md_parse_rng ^= g_md_parse_rng << 17;
  return g_md_parse_rng;
}

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

  MarkdownParseCacheEntry *free_slot = nullptr;
  for (int i = 0; i < MD_PARSE_CACHE_SLOTS; i++) {
    MarkdownParseCacheEntry &entry = g_md_parse_cache[i];
    if (entry.segment_count >= 0 && entry.key_hash == hash && entry.key_len == len) {
      entry.stamp = ++g_md_parse_stamp;
      *r_count = entry.segment_count;
      return entry.segments.get();
    }
    if (entry.segment_count < 0 && free_slot == nullptr) {
      free_slot = &entry;
    }
  }
  /* Fill the pool first, then evict at random (see the slot-count comment). */
  MarkdownParseCacheEntry *lru =
      free_slot != nullptr ? free_slot
                           : &g_md_parse_cache[md_next_random() % MD_PARSE_CACHE_SLOTS];

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
