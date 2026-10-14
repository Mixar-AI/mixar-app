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
/** \name Constants
 * \{ */



/** \} */

/* -------------------------------------------------------------------- */
/** \name Rounded Rectangle Drawing
 * \{ */

/* The glass counterpart of #chat_ui_draw_rounded_rect: the same bed geometry
 * with the MIXAR_GLASS_CHAT material over it. The bed is `color` — the theme's
 * User Bubble — so Preferences > Themes > Chat recolours the user's message;
 * the glass adds only its light and rim (`draw_tint = false`), and
 * `color[3]` fades the whole pane. The message area is drawn through the View2D
 * matrix (see mixie_chat_render_messages), so the painter's specular streak —
 * the one layer it clips with a region-px scissor — cannot be placed from here
 * and is off; the gloss, refraction wash and rim draw through that matrix fine. */
void chat_ui_draw_glass_pane(const rctf *rect, const float radius, const float color[4])
{
  chat_ui_draw_rounded_rect(rect, radius, color);
  rcti pane;
  BLI_rcti_rctf_copy(&pane, rect);
  ui::MixarGlassStyle style;
  style.role = ui::MIXAR_GLASS_CHAT;
  style.radius = radius;
  style.alpha = color[3];
  style.draw_specular = false;
  style.draw_tint = false;
  ui::mixar_glass_draw(pane, style);
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

/* A streaming turn remeasures every message. 512 slots aliased a long
 * transcript back onto itself (collision == full BLF measure). 4096 is
 * ~192 KB and keeps a few thousand segments direct-mapped. */
#define TEXT_BOUNDS_CACHE_SLOTS 4096 /* power of two */

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

  /* Kinsoku may move a break; measure the lines the draw pass will draw. */
  std::string prose_storage;
  const char *prose = chat_ui_prose_text(font_id, text, int(max_width), wrap_mode, prose_storage);

  rcti bbox;
  BLF_boundbox(font_id, prose, strlen(prose), &bbox);

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

  std::string prose_storage;
  const char *prose = chat_ui_prose_text(font_id, text, int(wrap_width), wrap_mode, prose_storage);

  /* Calculate bbox with CURRENT wrap settings for accurate positioning.
   * This ensures positioning matches actual rendered text layout. */
  rcti bbox;
  BLF_boundbox(font_id, prose, strlen(prose), &bbox);

  /* Position so bottom of text aligns with rect bottom (bottom-aligned).
   * bbox.ymin is negative (distance from baseline to bottom of lowest descender).
   * For baseline_y: we want (baseline_y + bbox.ymin) = rect.ymin
   * So: baseline_y = rect.ymin - bbox.ymin */
  float baseline_y = rect->ymin - float(bbox.ymin);

  /* Draw text - View2D handles clipping automatically, no scissor test needed */
  BLF_position(font_id, rect->xmin, baseline_y, 0.0f);
  BLF_draw(font_id, prose, strlen(prose));

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

}  // namespace blender
