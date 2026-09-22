/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: every line of text the surface paints.
 *
 * Split out of `view3d_director_cinema_paint.cc` when measuring arrived:
 * the surface paints into fixed cards and until then nothing checked a
 * label against the box it was in, so a long camera name ran out under the
 * delete chip and off the card. Fitting, ellipsising and the shared font
 * state are one job, and one file.
 *
 * Two rules everything here obeys:
 *
 * - A baseline comes from the FONT's ascender, never from the string's own
 *   ink box (#baseline_for), so labels do not drift against each other
 *   depending on whether they happen to contain a descender.
 * - BLF clipping is a shared state with no getter, so it is always left in a
 *   known one (#draw_text) rather than switched off and walked away from.
 */

#include <algorithm>
#include <cstring>

#include "BLF_api.hh"

#include "view3d_director_cinema.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {


namespace {

/**
 * Baseline that centres a line of this font on \a center_y.
 *
 * On the CAP HEIGHT, measured from a reference capital, and on neither of
 * the two things this tried first:
 *
 * - Not the string's own ink box. That makes the baseline depend on which
 *   glyphs the string happens to contain, so "My Cameras" and "Depth of
 *   Field" (a `p`) sat one to two pixels apart on the same row.
 * - Not `BLF_ascender`. A font's ascender carries the space above the
 *   capitals that accents and line gap need — for the UI font it is about
 *   0.97 em against a 0.73 em cap height — so centring it hangs every label
 *   low in its pill. Measured on a screenshot: 5.5 px below centre on a
 *   72 px row, which reads as text resting on the bottom edge.
 *
 * Centring the capital band is what a single-line label wants: capitals and
 * digits land dead centre, and a descender hangs below them the way it does
 * in every other typeset row.
 */
float cap_height(const int font, const float size)
{
  /* One glyph, and the same one every time, so the answer cannot vary with
   * the text. `H` sits ON the baseline, so its box top IS the cap height.
   * Cached because this runs once per painted label. */
  static int cached_font = -1;
  static float cached_size = 0.0f;
  static float cached_cap = 0.0f;
  if (font != cached_font || size != cached_size) {
    rcti box;
    BLF_boundbox(font, "H", 1, &box);
    cached_font = font;
    cached_size = size;
    cached_cap = float(box.ymax);
  }
  return cached_cap;
}

float baseline_for(const int font, const float size, const float center_y)
{
  return center_y - cap_height(font, size) * 0.5f;
}

/**
 * \a text, shortened with an ellipsis until it fits \a max_width.
 *
 * Returns the string to draw — \a text itself when it already fits, else
 * \a buffer. The surface paints into fixed cards, and until this existed
 * nothing measured: a long camera name ran out under the delete chip and off
 * the card, and a focus object's name did the same to the Depth of Field
 * row.
 */
const char *fit_text(
    const int font, const char *text, const float max_width, char *buffer, const int buffer_size)
{
  const size_t length = strlen(text);
  if (max_width <= 0.0f || BLF_width(font, text, length) <= max_width) {
    return text;
  }
  /* The ellipsis is part of the budget, so measure what is left for the
   * text itself rather than cutting first and overflowing by the glyph. */
  const char *ellipsis = "...";
  const float ellipsis_w = BLF_width(font, ellipsis, strlen(ellipsis));
  const float room = max_width - ellipsis_w;
  if (room <= 0.0f) {
    buffer[0] = '\0';
    return buffer;
  }
  float used = 0.0f;
  const size_t keep = BLF_width_to_strlen(font, text, length, room, &used);
  if (keep == 0 || keep + strlen(ellipsis) >= size_t(buffer_size)) {
    buffer[0] = '\0';
    return buffer;
  }
  memcpy(buffer, text, keep);
  memcpy(buffer + keep, ellipsis, strlen(ellipsis) + 1);
  return buffer;
}

/** Shared body: \a max_width of 0 means "do not measure". */
void draw_text(const char *text,
               const float x,
               const float center_y,
               const float size,
               const float max_width,
               const float col[4])
{
  if (text == nullptr || text[0] == '\0') {
    return;
  }
  const int font = BLF_default();
  BLF_size(font, size);
  char fitted[256];
  const char *drawn = fit_text(font, text, max_width, fitted, sizeof(fitted));
  if (drawn[0] == '\0') {
    return;
  }
  /* Clipping is a SHARED font state with no getter, so it is always left in
   * a known one: bounded to the cell when there is a cell, and off when the
   * caller asked for no bound. Disabling it and walking away — which is what
   * this did — leaves the next widget's own clip rect unset. */
  if (max_width > 0.0f) {
    BLF_clipping(font, x - 1.0f, center_y - size * 2.0f, x + max_width + 1.0f, center_y + size * 2.0f);
    BLF_enable(font, BLF_CLIPPING);
  }
  else {
    BLF_disable(font, BLF_CLIPPING);
  }
  BLF_color4fv(font, col);
  BLF_position(font, x, baseline_for(font, size, center_y), 0.0f);
  BLF_draw(font, drawn, strlen(drawn));
  if (max_width > 0.0f) {
    BLF_disable(font, BLF_CLIPPING);
  }
}

}  // namespace

float cinema_text_width(const char *text, const float size)
{
  if (text == nullptr || text[0] == '\0') {
    return 0.0f;
  }
  const int font = BLF_default();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}

void cinema_text_left(
    const char *text, const float x, const float center_y, const float size, const float col[4])
{
  draw_text(text, x, center_y, size, 0.0f, col);
}

void cinema_text_center(
    const char *text, const float cx, const float center_y, const float size, const float col[4])
{
  draw_text(text, cx - cinema_text_width(text, size) * 0.5f, center_y, size, 0.0f, col);
}

void cinema_text_right(
    const char *text, const float right, const float cy, const float size, const float col[4])
{
  draw_text(text, right - cinema_text_width(text, size), cy, size, 0.0f, col);
}

void cinema_text_left_fitted(const char *text,
                             const float x,
                             const float center_y,
                             const float size,
                             const float max_width,
                             const float col[4])
{
  draw_text(text, x, center_y, size, std::max(max_width, 0.0f), col);
}

void cinema_text_center_fitted(const char *text,
                               const float cx,
                               const float center_y,
                               const float size,
                               const float max_width,
                               const float col[4])
{
  const float width = std::min(cinema_text_width(text, size), std::max(max_width, 0.0f));
  draw_text(text, cx - width * 0.5f, center_y, size, std::max(max_width, 0.0f), col);
}

}  // namespace blender
