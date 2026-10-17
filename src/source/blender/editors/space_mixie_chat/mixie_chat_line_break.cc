/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Line-break opportunities for the chat's inline-markdown renderer.
 *
 * chat_ui_rich_text lays text out unit by unit. Splitting units only on
 * spaces left Chinese and Japanese prose — which has no spaces — as one
 * unbreakable unit that ran past the bubble's right edge. Here a unit also
 * ends between two characters when either is a wide (CJK) character, except
 * where kinsoku forbids it: closing punctuation, small kana and the long
 * vowel mark never start a line, opening brackets never end one.
 *
 * Pure byte/codepoint logic (no BLF, no RNA) so it stays testable.
 */

#include <cstdint>

#include "mixie_chat_line_break.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/** Decode one UTF-8 character at `buf[i]` (bounded by `len`). A malformed or
 * truncated sequence (rt_parse can cut its buffer mid-character) decodes as
 * one opaque byte so the caller always advances. */
static uint32_t lb_decode(const char *buf, int i, int len, int *r_size)
{
  const uint8_t c = uint8_t(buf[i]);
  int size = 1;
  uint32_t cp = c;
  if (c >= 0xF0 && c < 0xF8) {
    size = 4;
    cp = c & 0x07;
  }
  else if (c >= 0xE0) {
    size = 3;
    cp = c & 0x0F;
  }
  else if (c >= 0xC0) {
    size = 2;
    cp = c & 0x1F;
  }
  if (size == 1 || i + size > len) {
    *r_size = 1;
    return c;
  }
  for (int k = 1; k < size; k++) {
    const uint8_t cc = uint8_t(buf[i + k]);
    if ((cc & 0xC0) != 0x80) {
      *r_size = 1;
      return c;
    }
    cp = (cp << 6) | (cc & 0x3F);
  }
  *r_size = size;
  return cp;
}

/** Characters that may break on either side: CJK punctuation, kana,
 * ideographs, Hangul syllables and full-width forms. */
static bool lb_is_wide(const uint32_t cp)
{
  return (cp >= 0x2E80 && cp <= 0x9FFF) ||   /* Radicals, CJK punctuation, kana, ideographs. */
         (cp >= 0xAC00 && cp <= 0xD7A3) ||   /* Hangul syllables. */
         (cp >= 0xF900 && cp <= 0xFAFF) ||   /* CJK compatibility ideographs. */
         (cp >= 0xFE30 && cp <= 0xFE4F) ||   /* CJK compatibility forms. */
         (cp >= 0xFF00 && cp <= 0xFFEF) ||   /* Half- and full-width forms. */
         (cp >= 0x20000 && cp <= 0x3FFFF);   /* Supplementary ideographic planes. */
}

/** Kinsoku: may not begin a line. */
static bool lb_no_line_start(const uint32_t cp)
{
  switch (cp) {
    /* Closing brackets and quotes. */
    case 0x3001: case 0x3002: case 0x3009: case 0x300B: case 0x300D: case 0x300F:
    case 0x3011: case 0x3015: case 0x3017: case 0x3019: case 0x301B: case 0x301E:
    case 0xFF09: case 0xFF3D: case 0xFF5D: case 0xFF60: case 0xFF61: case 0xFF63:
    case 0xFF64:
    /* Full-width punctuation. */
    case 0xFF01: case 0xFF0C: case 0xFF0E: case 0xFF1A: case 0xFF1B: case 0xFF1F:
    /* Middle dot, iteration marks, long vowel mark, wave dash. */
    case 0x30FB: case 0x3005: case 0x309D: case 0x309E: case 0x30FD: case 0x30FE:
    case 0x30FC: case 0xFF70: case 0x301C: case 0xFF5E:
    /* Small hiragana. */
    case 0x3041: case 0x3043: case 0x3045: case 0x3047: case 0x3049: case 0x3063:
    case 0x3083: case 0x3085: case 0x3087: case 0x308E: case 0x3095: case 0x3096:
    /* Small katakana. */
    case 0x30A1: case 0x30A3: case 0x30A5: case 0x30A7: case 0x30A9: case 0x30C3:
    case 0x30E3: case 0x30E5: case 0x30E7: case 0x30EE: case 0x30F5: case 0x30F6:
    /* ASCII closers glued to the previous character. */
    case ')': case ']': case '}': case ',': case '.': case ':': case ';': case '!':
    case '?':
      return true;
    default:
      return false;
  }
}

/** Kinsoku: may not end a line. */
static bool lb_no_line_end(const uint32_t cp)
{
  switch (cp) {
    case 0x3008: case 0x300A: case 0x300C: case 0x300E: case 0x3010: case 0x3014:
    case 0x3016: case 0x3018: case 0x301A: case 0x301D: case 0xFF08: case 0xFF3B:
    case 0xFF5B: case 0xFF5F: case 0xFF62:
    case '(': case '[': case '{':
      return true;
    default:
      return false;
  }
}

static bool lb_is_space(const char c)
{
  return c == ' ' || c == '\t' || c == '\n';
}

int chat_ui_line_unit_end(const char *buf, const int start, const int len)
{
  int size = 1;
  uint32_t prev = lb_decode(buf, start, len, &size);
  int i = start + size;
  while (i < len && !lb_is_space(buf[i])) {
    const uint32_t cp = lb_decode(buf, i, len, &size);
    if ((lb_is_wide(prev) || lb_is_wide(cp)) && !lb_no_line_start(cp) &&
        !lb_no_line_end(prev))
    {
      break;
    }
    prev = cp;
    i += size;
  }
  return i;
}

int chat_ui_kinsoku_break(const char *buf, const int line_start, const int brk, const int len)
{
  if (brk <= line_start || brk >= len) {
    return brk;
  }
  int b = brk;
  for (;;) {
    /* Start of the line's last character. */
    int p = b - 1;
    while (p > line_start && (uint8_t(buf[p]) & 0xC0) == 0x80) {
      p--;
    }
    if (p <= line_start || lb_is_space(buf[p])) {
      /* Pulling another character down would empty the line, or the line
       * already ends at a space: keep the break the wrapper chose. */
      return brk;
    }
    int size = 1;
    const uint32_t next = lb_decode(buf, b, len, &size);
    const uint32_t last = lb_decode(buf, p, len, &size);
    if (!lb_no_line_start(next) && !lb_no_line_end(last)) {
      return b;
    }
    b = p;
  }
}

int chat_ui_utf8_char_size(const char *buf, const int i, const int len)
{
  int size = 1;
  lb_decode(buf, i, len, &size);
  return size;
}

}  // namespace blender
