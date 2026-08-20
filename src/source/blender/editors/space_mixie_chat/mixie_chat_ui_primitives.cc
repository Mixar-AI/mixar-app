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

#include "BLI_math_vector.h"
#include "BLI_rect.h"

#include "BLF_api.hh"

#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"

#include "mixie_chat_ui_types.hh"

/* -------------------------------------------------------------------- */
/** \name Constants
 * \{ */

static const int CORNER_SEGMENTS = 8;
static const float PI = 3.14159265f;

/** \} */

/* -------------------------------------------------------------------- */
/** \name Rounded Rectangle Drawing
 * \{ */

void chat_ui_draw_rounded_rect_outline(const rctf *rect,
                                       float radius,
                                       const float color[4],
                                       float line_width)
{
  /* PERFORMANCE: Assumes GPU_blend already set by caller - avoids state thrashing */

  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);

  GPU_line_width(line_width);

  float x = rect->xmin;
  float y = rect->ymin;
  float w = BLI_rctf_size_x(rect);
  float h = BLI_rctf_size_y(rect);

  /* Clamp radius to half of smaller dimension */
  float r = radius;
  if (r > w / 2.0f) {
    r = w / 2.0f;
  }
  if (r > h / 2.0f) {
    r = h / 2.0f;
  }

  /* Calculate number of vertices: 4 corners * CORNER_SEGMENTS + 4 straight edges + 1 to close */
  int total_verts = 4 * (CORNER_SEGMENTS + 1) + 1;

  immBegin(GPU_PRIM_LINE_STRIP, total_verts);

  /* Bottom-left corner (arc from 180 to 270 degrees) */
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = PI + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + r + r * cosf(angle), y + r + r * sinf(angle));
  }

  /* Bottom-right corner (arc from 270 to 360 degrees) */
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = (3.0f * PI / 2.0f) + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + w - r + r * cosf(angle), y + r + r * sinf(angle));
  }

  /* Top-right corner (arc from 0 to 90 degrees) */
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = 0.0f + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + w - r + r * cosf(angle), y + h - r + r * sinf(angle));
  }

  /* Top-left corner (arc from 90 to 180 degrees) */
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = (PI / 2.0f) + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + r + r * cosf(angle), y + h - r + r * sinf(angle));
  }

  /* Close the loop - connect back to start */
  immVertex2f(pos, x, y + r);

  immEnd();
  immUnbindProgram();

  /* Reset line width */
  GPU_line_width(1.0f);

  /* PERFORMANCE: GPU state managed by caller - no reset needed */
}

void chat_ui_draw_rounded_rect(const rctf *rect, float radius, const float color[4])
{
  /* PERFORMANCE: Assumes GPU_blend already set by caller - avoids state thrashing */

  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);

  float x = rect->xmin;
  float y = rect->ymin;
  float w = BLI_rctf_size_x(rect);
  float h = BLI_rctf_size_y(rect);

  /* Clamp radius to half of smaller dimension */
  float r = radius;
  if (r > w / 2.0f) {
    r = w / 2.0f;
  }
  if (r > h / 2.0f) {
    r = h / 2.0f;
  }

  /* Draw main body rectangles */
  /* Center rectangle (full height, reduced width) */
  immRectf(pos, x + r, y, x + w - r, y + h);

  /* Left rectangle */
  immRectf(pos, x, y + r, x + r, y + h - r);

  /* Right rectangle */
  immRectf(pos, x + w - r, y + r, x + w, y + h - r);

  /* Draw 4 corner arcs as triangle fans */

  /* Bottom-left corner */
  immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
  immVertex2f(pos, x + r, y + r);
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = PI + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + r + r * cosf(angle), y + r + r * sinf(angle));
  }
  immEnd();

  /* Bottom-right corner */
  immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
  immVertex2f(pos, x + w - r, y + r);
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = (3.0f * PI / 2.0f) + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + w - r + r * cosf(angle), y + r + r * sinf(angle));
  }
  immEnd();

  /* Top-right corner */
  immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
  immVertex2f(pos, x + w - r, y + h - r);
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = 0.0f + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + w - r + r * cosf(angle), y + h - r + r * sinf(angle));
  }
  immEnd();

  /* Top-left corner */
  immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
  immVertex2f(pos, x + r, y + h - r);
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = (PI / 2.0f) + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + r + r * cosf(angle), y + h - r + r * sinf(angle));
  }
  immEnd();

  immUnbindProgram();

  /* PERFORMANCE: GPU state managed by caller - no reset needed */
}

void chat_ui_draw_rounded_rect_bordered(const rctf *rect,
                                        float radius,
                                        const float fill_color[4],
                                        const float border_color[4],
                                        float border_width)
{
  /* Draw border (larger rect) */
  rctf border_rect = *rect;
  BLI_rctf_pad(&border_rect, border_width, border_width);
  chat_ui_draw_rounded_rect(&border_rect, radius + border_width, border_color);

  /* Draw fill (inner rect) */
  chat_ui_draw_rounded_rect(rect, radius, fill_color);
}

void chat_ui_draw_accent_bar(float x,
                             float y_bottom,
                             float height,
                             const float color[4],
                             float scale)
{
  if (height <= 0.0f) {
    return;
  }
  const float width = 2.5f * scale;
  rctf bar;
  bar.xmin = x;
  bar.xmax = x + width;
  bar.ymin = y_bottom;
  bar.ymax = y_bottom + height;
  chat_ui_draw_rounded_rect(&bar, width * 0.5f, color);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Text Drawing
 * \{ */

/* Forward declarations — the plain wrappers below delegate to these
 * font-parameterized variants defined later in this file. */
void chat_ui_calc_text_bounds_font(const char *text,
                                   float max_width,
                                   int font_size,
                                   int flags,
                                   int font_id,
                                   float *out_width,
                                   float *out_height,
                                   BLFWrapMode wrap_mode = BLFWrapMode::Minimal);
float chat_ui_draw_text_wrapped_font(const char *text,
                                     const rctf *rect,
                                     int font_size,
                                     int flags,
                                     int font_id,
                                     const float color[4],
                                     BLFWrapMode wrap_mode = BLFWrapMode::Minimal);

int chat_ui_mono_font()
{
  static int mono = -1;
  if (mono == -1) {
    mono = BLF_load_mono_default(false);
  }
  return mono;
}

/* Memoization for chat_ui_calc_text_bounds.
 *
 * The layout pass re-measures every message (and every markdown segment)
 * whenever the layout cache rebuilds — which during agent streaming is
 * every draw. BLF word-wrapped bound-boxing is O(text length) glyph
 * shaping, so long conversations made each frame cost the full
 * conversation's worth of text shaping. Identical (text, width, font,
 * flags) queries dominate: only the streaming tail message actually
 * changes between frames.
 *
 * Direct-mapped cache keyed by an FNV-1a hash of the text plus the
 * measurement parameters. A slot collision simply recomputes and
 * overwrites — worst case equals the previous uncached behaviour. A
 * hash collision (same 64-bit hash + same length + same params for
 * different text) could return a stale size for one frame; with 64-bit
 * FNV over UI strings this is not a practical concern (same trade-off
 * as the markdown parse cache in mixie_chat_markdown.cc). */
struct TextBoundsCacheEntry {
  uint64_t text_hash = 0;
  size_t text_len = 0;
  float max_width = -1.0f;
  int font_size = 0;
  int flags = 0;
  int font_id = -1;
  int wrap_mode = 0;
  float width = 0.0f;
  float height = 0.0f;
};

#define TEXT_BOUNDS_CACHE_SLOTS 512 /* power of two, ~24 KB total */

static TextBoundsCacheEntry g_text_bounds_cache[TEXT_BOUNDS_CACHE_SLOTS];

static uint64_t text_bounds_hash(const char *s, size_t *r_len)
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

void chat_ui_calc_text_bounds(const char *text,
                              float max_width,
                              int font_size,
                              int flags,
                              float *out_width,
                              float *out_height)
{
  chat_ui_calc_text_bounds_font(
      text, max_width, font_size, flags, BLF_default(), out_width, out_height);
}

void chat_ui_calc_text_bounds_font(const char *text,
                                   float max_width,
                                   int font_size,
                                   int flags,
                                   int font_id,
                                   float *out_width,
                                   float *out_height,
                                   BLFWrapMode wrap_mode)
{
  if (!text || text[0] == '\0') {
    *out_width = 0.0f;
    *out_height = 0.0f;
    return;
  }

  size_t text_len = 0;
  const uint64_t hash = text_bounds_hash(text, &text_len);
  TextBoundsCacheEntry &entry =
      g_text_bounds_cache[hash & (TEXT_BOUNDS_CACHE_SLOTS - 1)];
  if (entry.text_hash == hash && entry.text_len == text_len &&
      entry.max_width == max_width && entry.font_size == font_size &&
      entry.flags == flags && entry.font_id == font_id &&
      entry.wrap_mode == int(wrap_mode))
  {
    *out_width = entry.width;
    *out_height = entry.height;
    return;
  }

  BLF_size(font_id, font_size);

  if (flags != 0) {
    BLF_enable(font_id, FontFlags(flags));
  }

  BLF_enable(font_id, BLF_WORD_WRAP);

  /* Use max_width directly - draw will use the same width from rect.
   * This ensures consistent wrapping between bounds calculation and rendering. */
  BLF_wordwrap(font_id, int(max_width), wrap_mode);

  rcti bbox;
  BLF_boundbox(font_id, text, text_len, &bbox);

  /* Return actual dimensions - width clamped to max_width, height from bbox */
  float bbox_width = float(BLI_rcti_size_x(&bbox));
  *out_width = (bbox_width < max_width) ? bbox_width : max_width;
  *out_height = float(BLI_rcti_size_y(&bbox));

  BLF_disable(font_id, BLF_WORD_WRAP);

  if (flags != 0) {
    BLF_disable(font_id, FontFlags(flags));
  }

  entry.text_hash = hash;
  entry.text_len = text_len;
  entry.max_width = max_width;
  entry.font_size = font_size;
  entry.flags = flags;
  entry.font_id = font_id;
  entry.wrap_mode = int(wrap_mode);
  entry.width = *out_width;
  entry.height = *out_height;
}

float chat_ui_draw_text_wrapped(const char *text,
                                const rctf *rect,
                                int font_size,
                                int flags,
                                const float color[4])
{
  return chat_ui_draw_text_wrapped_font(
      text, rect, font_size, flags, BLF_default(), color);
}

float chat_ui_draw_text_wrapped_font(const char *text,
                                     const rctf *rect,
                                     int font_size,
                                     int flags,
                                     int font_id,
                                     const float color[4],
                                     BLFWrapMode wrap_mode)
{
  if (!text || text[0] == '\0') {
    return 0.0f;
  }

  float wrap_width = BLI_rctf_size_x(rect);

  BLF_size(font_id, font_size);

  if (flags != 0) {
    BLF_enable(font_id, FontFlags(flags));
  }

  BLF_enable(font_id, BLF_WORD_WRAP);
  BLF_wordwrap(font_id, int(wrap_width), wrap_mode);
  BLF_color4fv(font_id, color);

  /* Calculate bbox with CURRENT wrap settings for accurate positioning.
   * This ensures positioning matches actual rendered text layout. */
  rcti bbox;
  BLF_boundbox(font_id, text, strlen(text), &bbox);

  /* Position so bottom of text aligns with rect bottom (bottom-aligned).
   * bbox.ymin is negative (distance from baseline to bottom of lowest descender).
   * For baseline_y: we want (baseline_y + bbox.ymin) = rect.ymin
   * So: baseline_y = rect.ymin - bbox.ymin */
  float baseline_y = rect->ymin - float(bbox.ymin);

  /* Draw text - View2D handles clipping automatically, no scissor test needed */
  BLF_position(font_id, rect->xmin, baseline_y, 0.0f);
  BLF_draw(font_id, text, strlen(text));

  BLF_disable(font_id, BLF_WORD_WRAP);
  
  if (flags != 0) {
    BLF_disable(font_id, FontFlags(flags));
  }

  return float(BLI_rcti_size_y(&bbox));
}

void chat_ui_draw_label(const char *text,
                        float x,
                        float y,
                        int font_size,
                        int flags,
                        const float color[4],
                        bool right_align)
{
  if (!text || text[0] == '\0') {
    return;
  }

  const int font_id = BLF_default();

  BLF_size(font_id, font_size);
  
  if (flags != 0) {
    BLF_enable(font_id, FontFlags(flags));
  }
  
  BLF_color4fv(font_id, color);

  float draw_x = x;
  if (right_align) {
    rcti bbox;
    BLF_boundbox(font_id, text, strlen(text), &bbox);
    float label_width = float(BLI_rcti_size_x(&bbox));
    draw_x = x - label_width;
  }

  BLF_position(font_id, draw_x, y, 0.0f);
  BLF_draw(font_id, text, strlen(text));

  if (flags != 0) {
    BLF_disable(font_id, FontFlags(flags));
  }
}

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

    /* A word: maximal non-space run (may span style boundaries). */
    const int ws = i;
    while (i < n && buf[i] != ' ' && buf[i] != '\t' && buf[i] != '\n') {
      i++;
    }
    const int we = i;

    float word_w = 0.0f;
    for (int j = ws; j < we;) {
      const unsigned char rf = st[j];
      int k = j;
      while (k < we && st[k] == rf) {
        k++;
      }
      word_w += rt_run_width(buf, j, k, rf, font_size, mono_font);
      j = k;
    }

    if (pen_x + word_w > right && pen_x > left) {
      max_line_w = fmaxf(max_line_w, pen_x - left);
      line_top -= line_h;
      pen_x = left;
    }

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

/* -------------------------------------------------------------------- */
/** \name Image Drawing
 * \{ */

void chat_ui_draw_image(blender::gpu::Texture *tex,
                        const rctf *rect,
                        float corner_radius)
{
  if (!tex) {
    return;
  }

  float width = BLI_rctf_size_x(rect);
  float height = BLI_rctf_size_y(rect);

  /* Clamp radius to half of smaller dimension */
  float r = corner_radius;
  if (r > width / 2.0f) {
    r = width / 2.0f;
  }
  if (r > height / 2.0f) {
    r = height / 2.0f;
  }

  GPU_texture_bind(tex, 0);
  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  uint texcoord = GPU_vertformat_attr_add(
      format, "texCoord", blender::gpu::VertAttrType::SFLOAT_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_IMAGE);
  GPU_texture_filter_mode(tex, true);

  /* If radius is too small, just draw rectangular image */
  if (r < 1.0f) {
    immBegin(GPU_PRIM_TRI_FAN, 4);
    immAttr2f(texcoord, 0.0f, 0.0f);
    immVertex2f(pos, rect->xmin, rect->ymin);
    immAttr2f(texcoord, 1.0f, 0.0f);
    immVertex2f(pos, rect->xmax, rect->ymin);
    immAttr2f(texcoord, 1.0f, 1.0f);
    immVertex2f(pos, rect->xmax, rect->ymax);
    immAttr2f(texcoord, 0.0f, 1.0f);
    immVertex2f(pos, rect->xmin, rect->ymax);
    immEnd();
  }
  else {
    /* Draw image with rounded corners using a rounded rectangle mesh */
    float x = rect->xmin;
    float y = rect->ymin;
    float w = width;
    float h = height;

    /* Helper lambdas to calculate texture coordinates */
    auto tex_u = [x, w](float px) { return (px - x) / w; };
    auto tex_v = [y, h](float py) { return (py - y) / h; };

    /* Draw center rectangle */
    immBegin(GPU_PRIM_TRI_FAN, 4);
    immAttr2f(texcoord, tex_u(x + r), tex_v(y));
    immVertex2f(pos, x + r, y);
    immAttr2f(texcoord, tex_u(x + w - r), tex_v(y));
    immVertex2f(pos, x + w - r, y);
    immAttr2f(texcoord, tex_u(x + w - r), tex_v(y + h));
    immVertex2f(pos, x + w - r, y + h);
    immAttr2f(texcoord, tex_u(x + r), tex_v(y + h));
    immVertex2f(pos, x + r, y + h);
    immEnd();

    /* Draw left rectangle */
    immBegin(GPU_PRIM_TRI_FAN, 4);
    immAttr2f(texcoord, tex_u(x), tex_v(y + r));
    immVertex2f(pos, x, y + r);
    immAttr2f(texcoord, tex_u(x + r), tex_v(y + r));
    immVertex2f(pos, x + r, y + r);
    immAttr2f(texcoord, tex_u(x + r), tex_v(y + h - r));
    immVertex2f(pos, x + r, y + h - r);
    immAttr2f(texcoord, tex_u(x), tex_v(y + h - r));
    immVertex2f(pos, x, y + h - r);
    immEnd();

    /* Draw right rectangle */
    immBegin(GPU_PRIM_TRI_FAN, 4);
    immAttr2f(texcoord, tex_u(x + w - r), tex_v(y + r));
    immVertex2f(pos, x + w - r, y + r);
    immAttr2f(texcoord, tex_u(x + w), tex_v(y + r));
    immVertex2f(pos, x + w, y + r);
    immAttr2f(texcoord, tex_u(x + w), tex_v(y + h - r));
    immVertex2f(pos, x + w, y + h - r);
    immAttr2f(texcoord, tex_u(x + w - r), tex_v(y + h - r));
    immVertex2f(pos, x + w - r, y + h - r);
    immEnd();

    /* Draw the 4 corners as triangle fans */
    /* Bottom-left corner */
    immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
    immAttr2f(texcoord, tex_u(x + r), tex_v(y + r));
    immVertex2f(pos, x + r, y + r);
    for (int i = 0; i <= CORNER_SEGMENTS; i++) {
      float angle = PI + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
      float px = x + r + r * cosf(angle);
      float py = y + r + r * sinf(angle);
      immAttr2f(texcoord, tex_u(px), tex_v(py));
      immVertex2f(pos, px, py);
    }
    immEnd();

    /* Bottom-right corner */
    immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
    immAttr2f(texcoord, tex_u(x + w - r), tex_v(y + r));
    immVertex2f(pos, x + w - r, y + r);
    for (int i = 0; i <= CORNER_SEGMENTS; i++) {
      float angle = (3.0f * PI / 2.0f) + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
      float px = x + w - r + r * cosf(angle);
      float py = y + r + r * sinf(angle);
      immAttr2f(texcoord, tex_u(px), tex_v(py));
      immVertex2f(pos, px, py);
    }
    immEnd();

    /* Top-right corner */
    immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
    immAttr2f(texcoord, tex_u(x + w - r), tex_v(y + h - r));
    immVertex2f(pos, x + w - r, y + h - r);
    for (int i = 0; i <= CORNER_SEGMENTS; i++) {
      float angle = 0.0f + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
      float px = x + w - r + r * cosf(angle);
      float py = y + h - r + r * sinf(angle);
      immAttr2f(texcoord, tex_u(px), tex_v(py));
      immVertex2f(pos, px, py);
    }
    immEnd();

    /* Top-left corner */
    immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
    immAttr2f(texcoord, tex_u(x + r), tex_v(y + h - r));
    immVertex2f(pos, x + r, y + h - r);
    for (int i = 0; i <= CORNER_SEGMENTS; i++) {
      float angle = (PI / 2.0f) + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
      float px = x + r + r * cosf(angle);
      float py = y + h - r + r * sinf(angle);
      immAttr2f(texcoord, tex_u(px), tex_v(py));
      immVertex2f(pos, px, py);
    }
    immEnd();
  }

  immUnbindProgram();
  GPU_texture_unbind(tex);
}

void chat_ui_calc_image_bounds(int tex_width,
                               int tex_height,
                               float max_width,
                               float max_height,
                               float *out_width,
                               float *out_height)
{
  if (tex_width <= 0 || tex_height <= 0) {
    *out_width = 0.0f;
    *out_height = 0.0f;
    return;
  }

  float aspect = float(tex_width) / float(tex_height);
  float display_width = max_width;
  float display_height = display_width / aspect;

  /* Clamp to max height */
  if (display_height > max_height) {
    display_height = max_height;
    display_width = display_height * aspect;
  }

  /* Clamp to max width again in case aspect made it exceed */
  if (display_width > max_width) {
    display_width = max_width;
    display_height = display_width / aspect;
  }

  *out_width = display_width;
  *out_height = display_height;
}

/** \} */
