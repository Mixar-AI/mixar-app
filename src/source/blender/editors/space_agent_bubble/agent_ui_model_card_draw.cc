/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The model card's painter: the window draw callback. Everything is drawn
 * here by hand — the card and its soft shadow, the tab track with the green
 * pill that slides between tabs, the monospace caption, the rows with the
 * current one checked on a tinted plate, the trailing notes, the folded
 * thinking levels, the pinned footer and the scrollbar thumb. The list is
 * clipped hard at its edges: no fades (they read as bands and cost rows). Literal
 * palette, like the chip.
 */

#include <algorithm>
#include <cmath>
#include <cstring>
#include <string>

#include "BLF_api.hh"
#include "BLI_rect.h"

#include "DNA_userdef_types.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_mixar.hh"

#include "agent_ui_model_card_intern.hh"

namespace blender::agent_model_card {

namespace {

#define HEX(c, a) {((c) >> 16 & 0xFF) / 255.0f, ((c) >> 8 & 0xFF) / 255.0f, ((c) & 0xFF) / 255.0f, a}

constexpr float CARD[4] = HEX(0x1E1F1F, 1.0f);
constexpr float BORDER[4] = HEX(0xFFFFFF, 0.07f);
constexpr float TRACK[4] = HEX(0x121313, 1.0f);
constexpr float PILL[4] = HEX(0x2E5E32, 1.0f);
constexpr float INK[4] = HEX(0xEDEDED, 1.0f);
constexpr float INK_TAB_IDLE[4] = HEX(0x8E8E8E, 1.0f);
constexpr float INK_TAB_HOVER[4] = HEX(0xC4C4C4, 1.0f);
constexpr float CAPTION[4] = HEX(0x8A8A8A, 1.0f);
constexpr float TRAILING[4] = HEX(0x9C9C9C, 1.0f);
constexpr float NOTE[4] = HEX(0xC9A85C, 1.0f);
constexpr float PLATE_CURRENT[4] = HEX(0xFFFFFF, 0.06f);
constexpr float PLATE_HOVER[4] = HEX(0xFFFFFF, 0.045f);
constexpr float CHECK[4] = HEX(0x7DDB8E, 1.0f);
constexpr float FOOTER_INK[4] = HEX(0x8FDB9C, 1.0f);
constexpr float DIVIDER[4] = HEX(0xFFFFFF, 0.07f);
constexpr float THUMB[4] = HEX(0xFFFFFF, 0.18f);
constexpr float THUMB_HOT[4] = HEX(0xFFFFFF, 0.34f);

#undef HEX

constexpr int WEIGHT_REGULAR = 500;
constexpr int WEIGHT_STRONG = 650;

/** The weight the island's other text is drawn at: the widget style's. Text
 * here goes back to it after its own weight (other island text assumes it). */
int widget_weight()
{
  const uiStyle *style = ui::style_get();
  return style ? style->widget.character_weight : WEIGHT_REGULAR - 100;
}

void with_alpha(const float in[4], const float alpha, float r_out[4])
{
  r_out[0] = in[0];
  r_out[1] = in[1];
  r_out[2] = in[2];
  r_out[3] = in[3] * alpha;
}

void mix(const float a[4], const float b[4], const float t, float r_out[4])
{
  for (int i = 0; i < 4; i++) {
    r_out[i] = a[i] + (b[i] - a[i]) * t;
  }
}

/** Text with its ink centred on cy; \a mono picks the caption face. */
float text(const char *str,
           float x,
           const float cy,
           const float size,
           const float col[4],
           const int weight,
           const bool mono,
           const int align /* -1 left, 0 centre, 1 right */)
{
  if (!str || !str[0]) {
    return 0.0f;
  }
  const int font = mono ? blf_mono_font : BLF_default();
  BLF_size(font, size);
  if (!mono) {
    BLF_character_weight(font, weight);
  }
  BLF_disable(font, BLF_CLIPPING);
  const size_t len = strlen(str);
  const float w = BLF_width(font, str, len);
  if (align == 0) {
    x -= w * 0.5f;
  }
  else if (align > 0) {
    x -= w;
  }
  rcti box;
  BLF_boundbox(font, "Hg", 2, &box);
  BLF_color4fv(font, col);
  BLF_position(font, x, cy - float(box.ymin + box.ymax) * 0.5f, 0.0f);
  BLF_draw(font, str, len);
  if (!mono) {
    BLF_character_weight(font, widget_weight());
  }
  return w;
}

/** \a str shortened with an ellipsis to fit \a width. */
std::string fit(const char *str, const float width, const float size, const int weight)
{
  BLF_character_weight(BLF_default(), weight);
  std::string out = ui::mixar_fit_text(str, width, size);
  BLF_character_weight(BLF_default(), widget_weight());
  return out;
}

void fill(const rctf &r, const float radius, const float col[4])
{
  if (BLI_rctf_size_x(&r) <= 0.0f || BLI_rctf_size_y(&r) <= 0.0f) {
    return;
  }
  ui::mixar_fill_round(r, std::min(radius, BLI_rctf_size_y(&r) * 0.5f), col);
}

void outline(const rctf &r, const float radius, const float col[4])
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&r, false, radius, col);
}

void check_mark(const float cx, const float cy, const float size, const float col[4])
{
  float viewport[4];
  GPU_viewport_size_get_f(viewport);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_POLYLINE_UNIFORM_COLOR);
  immUniform2fv("viewportSize", &viewport[2]);
  immUniform1f("lineWidth", std::max(1.5f, size * 0.16f));
  immUniform1i("lineSmooth", 1);
  immUniformColor4fv(col);
  immBegin(GPU_PRIM_LINE_STRIP, 3);
  immVertex2f(pos, cx - size * 0.42f, cy + size * 0.02f);
  immVertex2f(pos, cx - size * 0.12f, cy - size * 0.30f);
  immVertex2f(pos, cx + size * 0.45f, cy + size * 0.36f);
  immEnd();
  immUnbindProgram();
}

void shadow(const rctf &card, const float radius, const float fs, const float alpha)
{
  for (int i = 4; i >= 1; i--) {
    rctf r = card;
    const float grow = fs * 0.16f * float(i);
    BLI_rctf_pad(&r, grow, grow);
    BLI_rctf_translate(&r, 0.0f, -fs * 0.22f);
    const float col[4] = {0.0f, 0.0f, 0.0f, 0.09f * alpha * float(5 - i) / 4.0f};
    fill(r, radius + grow, col);
  }
}

void draw_tabs(const State &state, const Layout &l, const Metrics &m, const float a)
{
  float col[4];
  with_alpha(TRACK, a, col);
  fill(l.tabs, m.radius * 0.85f, col);
  if (l.tab_cells.empty()) {
    return;
  }
  /* The pill slides between cells (eased index). */
  const int n = int(l.tab_cells.size());
  const float p = std::clamp(state.pill, 0.0f, float(n - 1));
  const int i0 = int(std::floor(p)), i1 = std::min(n - 1, i0 + 1);
  const float t = p - float(i0);
  rctf pill;
  pill.xmin = l.tab_cells[i0].xmin + (l.tab_cells[i1].xmin - l.tab_cells[i0].xmin) * t;
  pill.xmax = l.tab_cells[i0].xmax + (l.tab_cells[i1].xmax - l.tab_cells[i0].xmax) * t;
  pill.ymin = l.tab_cells[0].ymin;
  pill.ymax = l.tab_cells[0].ymax;
  with_alpha(PILL, a, col);
  fill(pill, m.radius * 0.7f, col);
  for (int i = 0; i < n; i++) {
    const Tab &tab = state.tabs[i];
    const bool active = tab.id == state.tab;
    const rctf &c = l.tab_cells[i];
    float ink[4];
    if (active) {
      with_alpha(INK, a, ink);
    }
    else {
      with_alpha(state.hover_tab == i ? INK_TAB_HOVER : INK_TAB_IDLE, a * (tab.enabled ? 1.0f : 0.4f), ink);
    }
    const std::string label = fit(tab.label.c_str(), BLI_rctf_size_x(&c) - m.pad, m.fs, WEIGHT_STRONG);
    text(label.c_str(), BLI_rctf_cent_x(&c), BLI_rctf_cent_y(&c), m.fs, ink, WEIGHT_STRONG, false, 0);
  }
}

void draw_caption(const State &state, const Layout &l, const Metrics &m, const float a)
{
  const Tab *tab = nullptr;
  for (const Tab &t : state.tabs) {
    if (t.id == state.tab) {
      tab = &t;
    }
  }
  if (!tab) {
    return;
  }
  float col[4];
  with_alpha(CAPTION, a, col);
  const float cy = BLI_rctf_cent_y(&l.caption) - m.fs * 0.1f;
  const float size = m.fs * 0.78f;
  text(tab->heading.c_str(), l.caption.xmin + m.pad * 0.15f, cy, size, col, 0, true, -1);
  text(tab->cost.c_str(), l.caption.xmax - m.pad * 0.15f, cy, size, col, 0, true, 1);
}

void draw_line(const State &state, const Layout &l, const Metrics &m, const int i, const float a)
{
  rctf r;
  if (!line_rect(state, l, i, &r)) {
    return;
  }
  const Line &line = state.lines[i];
  float col[4];
  if (line.kind == LineKind::Divider) {
    /* A hairline across the plates' width, centred in its gap. */
    with_alpha(DIVIDER, a, col);
    const float h = std::max(1.0f, m.fs * 0.05f);
    const float cy = BLI_rctf_cent_y(&r);
    fill({r.xmin + m.pad * 0.6f, r.xmax - m.pad * 0.6f, cy - h * 0.5f, cy + h * 0.5f}, 0.0f, col);
    return;
  }
  if (line.kind == LineKind::Note) {
    with_alpha(NOTE, a, col);
    const std::string note = fit(line.trailing.c_str(), BLI_rctf_size_x(&r) - m.pad * 1.2f,
                                 m.fs * 0.88f, WEIGHT_REGULAR);
    text(note.c_str(), r.xmin + m.pad * 0.6f, BLI_rctf_cent_y(&r), m.fs * 0.88f, col,
         WEIGHT_REGULAR, false, -1);
    return;
  }
  const Row &row = state.rows[line.row];
  const bool level = line.kind == LineKind::Level;
  const bool live = row.enabled && !state.gated;
  rctf plate = r;
  BLI_rctf_pad(&plate, -m.pad * 0.15f, -m.fs * 0.12f);
  if (level) {
    plate.xmin += m.check_w * 0.75f;
  }
  if (row.current) {
    with_alpha(PLATE_CURRENT, a, col);
    fill(plate, m.radius * 0.6f, col);
  }
  const float hover = i < int(state.hover_mix.size()) ? state.hover_mix[i] : 0.0f;
  if (hover > 0.01f && live) {
    with_alpha(PLATE_HOVER, a * hover, col);
    fill(plate, m.radius * 0.6f, col);
  }
  const float alpha = a * (live ? 1.0f : 0.42f);
  const float size = level ? m.fs * 0.92f : m.fs * 1.02f;
  const float x_check = plate.xmin + m.pad * 0.45f + m.check_w * 0.35f;
  const float cy = BLI_rctf_cent_y(&r);
  if (row.current) {
    with_alpha(CHECK, alpha, col);
    check_mark(x_check, cy, size * 0.62f, col);
  }
  /* The trailing note: thinking disclosure, "Not on your plan", "saved". */
  float trailing_w = 0.0f;
  if (!level && !line.trailing.empty()) {
    const bool hot = line.disclosure && state.hover == i && state.hover_trailing;
    /* "Mixar default" carries its tag in the accent: the server's pick. */
    const float *ink = is_default_row(row) ? FOOTER_INK : (hot ? INK_TAB_HOVER : TRAILING);
    with_alpha(ink, a * (is_default_row(row) ? 0.85f : 1.0f), col);
    trailing_w = text(line.trailing.c_str(), plate.xmax - m.pad * 0.6f, cy, m.fs * 0.78f, col, 0,
                      true, 1) +
                 m.pad;
  }
  const float x = plate.xmin + m.pad * 0.45f + m.check_w;
  const int weight = row.current ? WEIGHT_STRONG : WEIGHT_REGULAR;
  const std::string label = fit(
      row.label.c_str(), plate.xmax - m.pad * 0.6f - trailing_w - x, size, weight);
  with_alpha(INK, alpha, col);
  if (level && !row.current) {
    mix(INK, TRAILING, 0.35f, col);
    col[3] = alpha;
  }
  text(label.c_str(), x, cy, size, col, weight, false, -1);
}

void draw_footer(const State &state, const Layout &l, const Metrics &m, const float a)
{
  if (state.footers.empty()) {
    return;
  }
  float col[4];
  with_alpha(DIVIDER, a, col);
  const rctf line = {l.card.xmin + m.pad, l.card.xmax - m.pad, l.footer.ymax + m.pad * 0.2f,
                     l.footer.ymax + m.pad * 0.2f + std::max(1.0f, m.fs * 0.05f)};
  fill(line, 0.0f, col);
  for (int i = 0; i < int(state.footers.size()); i++) {
    const Row &row = state.rows[state.footers[i]];
    const rctf &c = l.footer_cells[i];
    const float hover = i < int(state.footer_mix.size()) ? state.footer_mix[i] : 0.0f;
    if (hover > 0.01f) {
      rctf plate = c;
      BLI_rctf_pad(&plate, -m.pad * 0.15f, -m.fs * 0.15f);
      with_alpha(PLATE_HOVER, a * hover, col);
      fill(plate, m.radius * 0.6f, col);
    }
    with_alpha(FOOTER_INK, a * (row.enabled ? 1.0f : 0.4f), col);
    const std::string label = fit(row.label.c_str(), BLI_rctf_size_x(&c) - m.pad, m.fs * 0.95f,
                                  WEIGHT_STRONG);
    text(label.c_str(), BLI_rctf_cent_x(&c), BLI_rctf_cent_y(&c), m.fs * 0.95f, col,
         WEIGHT_STRONG, false, 0);
  }
}

void draw_scrollbar(const State &state, const Layout &l, const Metrics &m, const float a)
{
  if (l.max_scroll <= 0.0f) {
    return;
  }
  float col[4];
  mix(THUMB, THUMB_HOT, state.bar_mix, col);
  col[3] *= a;
  rctf thumb = l.bar_thumb;
  /* The thumb fattens a little under the pointer. */
  const float grow = m.bar_w * 0.35f * state.bar_mix;
  thumb.xmin -= grow;
  fill(thumb, BLI_rctf_size_x(&thumb) * 0.5f, col);
}

}  // namespace

void draw(const wmWindow * /*win*/, void *customdata)
{
  const State &state = *static_cast<const State *>(customdata);
  if (!state.anchor_valid) {
    return;
  }
  const Metrics m = metrics(state);
  const float a = appear_factor(state);
  /* Rise into place (the modal hit-tests the same layout). */
  const Layout l = layout_compute(state, card_rise(state));

  const GPUBlend blend_prev = GPU_blend_get();
  GPU_blend(GPU_BLEND_ALPHA);
  shadow(l.card, m.radius, m.fs, a);
  float col[4];
  with_alpha(CARD, a, col);
  fill(l.card, m.radius, col);
  with_alpha(BORDER, a, col);
  outline(l.card, m.radius, col);

  draw_tabs(state, l, m, a);
  draw_caption(state, l, m, a);

  int scissor[4];
  GPU_scissor_get(scissor);
  GPU_scissor_test(true);
  GPU_scissor(int(l.list.xmin), int(l.list.ymin), int(BLI_rctf_size_x(&l.list)),
              int(BLI_rctf_size_y(&l.list)));
  for (int i = 0; i < int(state.lines.size()); i++) {
    draw_line(state, l, m, i, a);
  }
  GPU_scissor(scissor[0], scissor[1], scissor[2], scissor[3]);
  /* Window draw callbacks run with the test off; GPU has no getter for it. */
  GPU_scissor_test(false);

  draw_scrollbar(state, l, m, a);
  draw_footer(state, l, m, a);
  GPU_blend(blend_prev);
}

}  // namespace blender::agent_model_card
