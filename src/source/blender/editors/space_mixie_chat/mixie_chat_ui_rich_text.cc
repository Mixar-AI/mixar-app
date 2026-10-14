/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Low-level GPU drawing primitives for chat UI.
 * Provides rounded rectangles, text rendering, and image drawing.
 */

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <string>

#include "BLI_math_vector.h"
#include "BLI_rect.h"

#include "BLF_api.hh"

#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"

#include "ED_mixar_glass.hh"

#include "mixie_chat_line_break.hh"
#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Inline-markdown Rich Text
 * \{ */

/* Internal inline style bits (distinct from BLF flag bits). */
enum { RT_BOLD = 1, RT_ITALIC = 2, RT_CODE = 4 };

#define RT_MAX_CHARS 8192

/* Parse inline markdown markers (**bold**, *italic*, `code`) into a parallel
 * (char, style) buffer with the markers removed. base_rt is OR'd into every
 * char. Returns the stripped length. */
static int rt_parse(const char *text, int base_rt, char *out, unsigned char *style_out)
{
  int n = 0;
  int style = 0;
  for (const char *p = text; *p && n < RT_MAX_CHARS - 1;) {
    if (*p == '`') {
      style ^= RT_CODE;
      p++;
      continue;
    }
    if (!(style & RT_CODE) && p[0] == '*' && p[1] == '*') {
      style ^= RT_BOLD;
      p += 2;
      continue;
    }
    if (!(style & RT_CODE) && p[0] == '*') {
      style ^= RT_ITALIC;
      p += 1;
      continue;
    }
    out[n] = *p;
    style_out[n] = (unsigned char)(style | base_rt);
    n++;
    p++;
  }
  out[n] = '\0';
  return n;
}

static int rt_blf_flags(unsigned char rt)
{
  int f = 0;
  if (rt & RT_BOLD) {
    f |= BLF_BOLD;
  }
  if (rt & RT_ITALIC) {
    f |= BLF_ITALIC;
  }
  return f;
}

/* Measure a same-style run [s,e) of buf. */
static float rt_run_width(
    const char *buf, int s, int e, unsigned char rt, int font_size, int mono_font)
{
  if (e <= s) {
    return 0.0f;
  }
  int font = (rt & RT_CODE) ? mono_font : BLF_default();
  BLF_size(font, font_size);
  int bf = rt_blf_flags(rt);
  if (bf) {
    BLF_enable(font, FontFlags(bf));
  }
  float w = BLF_width(font, buf + s, size_t(e - s));
  if (bf) {
    BLF_disable(font, FontFlags(bf));
  }
  return w;
}

/* Width of [s,e) of buf across its style runs. */
static float rt_span_width(const char *buf,
                           const unsigned char *st,
                           int s,
                           int e,
                           int font_size,
                           int mono_font)
{
  float w = 0.0f;
  for (int j = s; j < e;) {
    const unsigned char rf = st[j];
    int k = j;
    while (k < e && st[k] == rf) {
      k++;
    }
    w += rt_run_width(buf, j, k, rf, font_size, mono_font);
    j = k;
  }
  return w;
}

/* End of the longest prefix of [s,e) that fits `avail` (at least one
 * character), measured a character at a time so a long token stays linear. */
static int rt_fit_prefix(const char *buf,
                         const unsigned char *st,
                         int s,
                         int e,
                         float avail,
                         int font_size,
                         int mono_font)
{
  float w = 0.0f;
  int j = s;
  while (j < e) {
    const int size = chat_ui_utf8_char_size(buf, j, e);
    w += rt_run_width(buf, j, j + size, st[j], font_size, mono_font);
    if (w > avail && j > s) {
      break;
    }
    j += size;
  }
  return j;
}

float chat_ui_rich_text(const char *text,
                        const rctf *rect,
                        int font_size,
                        int base_flags,
                        const float color[4],
                        float scale_factor,
                        bool do_draw,
                        float *out_max_width)
{
  if (out_max_width) {
    *out_max_width = 0.0f;
  }
  if (!text || text[0] == '\0' || font_size <= 0) {
    return 0.0f;
  }

  const int def_font = BLF_default();
  const int mono_font = chat_ui_mono_font();

  BLF_size(def_font, font_size);
  const float line_h = float(BLF_height_max(def_font)) * 1.15f;
  const float ascender = float(BLF_ascender(def_font));
  BLF_size(def_font, font_size);
  const float space_w = BLF_width(def_font, " ", 1);

  static char buf[RT_MAX_CHARS];
  static unsigned char st[RT_MAX_CHARS];
  int base_rt = 0;
  if (base_flags & BLF_BOLD) {
    base_rt |= RT_BOLD;
  }
  if (base_flags & BLF_ITALIC) {
    base_rt |= RT_ITALIC;
  }
  const int n = rt_parse(text, base_rt, buf, st);

  const float left = rect->xmin;
  const float right = rect->xmax;
  float pen_x = left;
  float line_top = rect->ymax;
  float max_line_w = 0.0f;

  /* Inline-code styling. */
  const float code_bg[4] = {0.32f, 0.34f, 0.42f, 0.55f};
  float code_col[4] = {
      fminf(color[0] * 0.6f + 0.45f, 1.0f),
      fminf(color[1] * 0.6f + 0.5f, 1.0f),
      fminf(color[2] * 0.6f + 0.6f, 1.0f),
      color[3],
  };
  const float code_pad = 2.0f * scale_factor;

  int i = 0;
  while (i < n) {
    const char c = buf[i];
    if (c == '\n') {
      max_line_w = fmaxf(max_line_w, pen_x - left);
      line_top -= line_h;
      pen_x = left;
      i++;
      continue;
    }
    if (c == ' ' || c == '\t') {
      while (i < n && (buf[i] == ' ' || buf[i] == '\t')) {
        if (pen_x > left) {
          pen_x += space_w; /* collapse leading spaces at line start */
        }
        i++;
      }
      continue;
    }

    /* A unit: a non-space run (may span style boundaries) that also ends at
     * a CJK break opportunity, so Chinese and Japanese prose wraps. */
    const int ws = i;
    int we = chat_ui_line_unit_end(buf, i, n);

    float word_w = rt_span_width(buf, st, ws, we, font_size, mono_font);

    if (pen_x + word_w > right && pen_x > left) {
      max_line_w = fmaxf(max_line_w, pen_x - left);
      line_top -= line_h;
      pen_x = left;
    }

    /* Wider than a whole line (a URL, a long identifier): fold at the edge;
     * the remainder is the next unit. */
    if (word_w > right - left) {
      we = rt_fit_prefix(buf, st, ws, we, right - left, font_size, mono_font);
      word_w = rt_span_width(buf, st, ws, we, font_size, mono_font);
    }
    i = we;

    if (do_draw) {
      const float baseline = line_top - ascender;
      float wx = pen_x;
      for (int j = ws; j < we;) {
        const unsigned char rf = st[j];
        int k = j;
        while (k < we && st[k] == rf) {
          k++;
        }
        const int font = (rf & RT_CODE) ? mono_font : def_font;
        BLF_size(font, font_size);
        const int bf = rt_blf_flags(rf);
        if (bf) {
          BLF_enable(font, FontFlags(bf));
        }
        const float sub_w = BLF_width(font, buf + j, size_t(k - j));

        if (rf & RT_CODE) {
          rctf bg;
          bg.xmin = wx - code_pad;
          bg.xmax = wx + sub_w + code_pad;
          bg.ymin = baseline - 2.0f * scale_factor;
          bg.ymax = baseline + ascender * 0.92f;
          GPU_blend(GPU_BLEND_ALPHA);
          chat_ui_draw_rounded_rect(&bg, 3.0f * scale_factor, code_bg);
        }

        BLF_color4fv(font, (rf & RT_CODE) ? code_col : color);
        BLF_position(font, wx, baseline, 0.0f);
        BLF_draw(font, buf + j, size_t(k - j));
        if (bf) {
          BLF_disable(font, FontFlags(bf));
        }
        wx += sub_w;
        j = k;
      }
    }

    pen_x += word_w;
    max_line_w = fmaxf(max_line_w, pen_x - left);
  }

  if (out_max_width) {
    *out_max_width = max_line_w;
  }
  return (rect->ymax - line_top) + line_h;
}

/** \} */

}  // namespace blender
