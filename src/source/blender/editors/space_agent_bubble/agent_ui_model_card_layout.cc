/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The model card's metrics and layout. Every size is a multiple of the
 * island's body text size, so the card follows the interface scale and the
 * font preference exactly like the chip that opens it. All rects are window
 * pixels — the space of the window draw callback and of `wmEvent::xy`.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLF_api.hh"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "DNA_windowmanager_types.h"

#include "WM_api.hh"
#include "WM_types.hh"

#include "UI_mixar_motion.hh"

#include "agent_ui_model_card_intern.hh"

namespace blender::agent_model_card {

namespace {

/** The card rises into place over this long (reduced motion: at once). */
constexpr double APPEAR_SECONDS = 0.14;
/** From this far below its place, in body text sizes. */
constexpr float RISE_FS = 0.6f;
/** An eased value this close to its goal lands on it (the timer then rests). */
constexpr float SNAP = 0.002f;

/** One eased step of \a value toward \a goal; true when it changed. */
bool ease(float &value, const float goal, const float k, const float snap)
{
  const float before = value;
  value += (goal - value) * k;
  if (std::abs(goal - value) < snap) {
    value = goal;
  }
  return value != before;
}

}  // namespace

Metrics metrics(const State &state)
{
  const float fs = state.text_size > 0.0f ? state.text_size : 24.0f;
  Metrics m;
  m.fs = fs;
  m.pad = fs * 0.62f;
  m.radius = fs * 0.9f;
  m.tabs_h = fs * 2.2f;
  m.tab_inset = fs * 0.2f;
  m.caption_h = fs * 1.95f;
  m.row_h = fs * 2.15f;
  m.level_h = fs * 1.8f;
  m.note_h = fs * 1.75f;
  m.footer_h = fs * 2.0f;
  m.check_w = fs * 1.6f;
  m.bar_w = fs * 0.3f;
  m.gap = fs * 0.45f;
  m.margin = fs * 0.45f;
  m.width = fs * 24.0f;
  return m;
}

float appear_factor(const State &state)
{
  if (ui::mixar_motion_reduced()) {
    return 1.0f;
  }
  const float t = float((BLI_time_now_seconds() - state.opened_at) / APPEAR_SECONDS);
  const float x = std::clamp(t, 0.0f, 1.0f);
  return 1.0f - (1.0f - x) * (1.0f - x) * (1.0f - x); /* Ease out. */
}

float card_rise(const State &state)
{
  return (1.0f - appear_factor(state)) * metrics(state).fs * RISE_FS;
}

Layout layout_compute(const State &state, const float rise)
{
  const Metrics m = metrics(state);
  Layout l;
  const float win_w = state.win ? float(WM_window_native_pixel_x(state.win)) : 1000.0f;
  const float win_h = state.win ? float(WM_window_native_pixel_y(state.win)) : 1000.0f;

  l.content_h = 0.0f;
  for (const Line &line : state.lines) {
    l.content_h = std::max(l.content_h, line.top + line.height);
  }
  const bool has_footer = !state.footers.empty();
  const float header = m.pad + m.tabs_h + m.caption_h;
  const float footer = has_footer ? m.footer_h + m.pad * 0.9f : m.pad * 0.6f;

  /* Above the chip, as wide as the design asks, kept inside the window
   * wherever the island sits; the left edge follows the chip. */
  const float width = std::clamp(m.width, std::min(m.fs * 15.0f, win_w - 2.0f * m.margin),
                                 win_w - 2.0f * m.margin);
  const float x0 = std::clamp(
      state.anchor.xmin - m.pad * 0.5f, m.margin, std::max(m.margin, win_w - m.margin - width));
  const float bottom = state.anchor.ymax - rise + m.gap;
  const float room = std::max(0.0f, win_h - m.margin - bottom);
  const float wanted = header + l.content_h + footer;
  const float height = std::min(wanted, std::max(room, header + footer + m.row_h));
  l.card = {x0, x0 + width, bottom, bottom + height};

  l.tabs = {l.card.xmin + m.pad, l.card.xmax - m.pad, l.card.ymax - m.pad - m.tabs_h,
            l.card.ymax - m.pad};
  l.caption = {l.card.xmin + m.pad, l.card.xmax - m.pad, l.tabs.ymin - m.caption_h, l.tabs.ymin};
  if (has_footer) {
    l.footer = {l.card.xmin + m.pad * 0.5f, l.card.xmax - m.pad * 0.5f,
                l.card.ymin + m.pad * 0.45f, l.card.ymin + m.pad * 0.45f + m.footer_h};
  }
  else {
    l.footer = {l.card.xmin, l.card.xmax, l.card.ymin, l.card.ymin};
  }
  l.list = {l.card.xmin + m.pad * 0.4f, l.card.xmax - m.pad * 0.4f,
            has_footer ? l.footer.ymax + m.pad * 0.45f : l.card.ymin + m.pad * 0.6f,
            l.caption.ymin};
  if (l.list.ymax < l.list.ymin) {
    l.list.ymax = l.list.ymin;
  }
  const float list_h = BLI_rctf_size_y(&l.list);
  l.max_scroll = std::max(0.0f, l.content_h - list_h);

  /* Tabs: equal cells inside the track. */
  const int count = std::max(1, int(state.tabs.size()));
  const rctf inner = {l.tabs.xmin + m.tab_inset, l.tabs.xmax - m.tab_inset,
                      l.tabs.ymin + m.tab_inset, l.tabs.ymax - m.tab_inset};
  for (int i = 0; i < int(state.tabs.size()); i++) {
    const float w = BLI_rctf_size_x(&inner) / float(count);
    l.tab_cells.push_back({inner.xmin + w * i, inner.xmin + w * (i + 1), inner.ymin, inner.ymax});
  }
  /* Footer: one cell per action, side by side. */
  for (int i = 0; i < int(state.footers.size()); i++) {
    const float w = BLI_rctf_size_x(&l.footer) / float(state.footers.size());
    l.footer_cells.push_back(
        {l.footer.xmin + w * i, l.footer.xmin + w * (i + 1), l.footer.ymin, l.footer.ymax});
  }

  /* Scrollbar: a slim thumb at the list's right edge. */
  l.bar_track = {l.list.xmax - m.bar_w - m.pad * 0.2f, l.list.xmax - m.pad * 0.2f,
                 l.list.ymin + m.pad * 0.25f, l.list.ymax - m.pad * 0.25f};
  if (l.max_scroll > 0.0f && l.content_h > 0.0f) {
    const float track_h = BLI_rctf_size_y(&l.bar_track);
    const float thumb_h = std::clamp(track_h * list_h / l.content_h, m.fs * 1.4f, track_h);
    const float t = std::clamp(state.scroll / l.max_scroll, 0.0f, 1.0f);
    const float top = l.bar_track.ymax - (track_h - thumb_h) * t;
    l.bar_thumb = {l.bar_track.xmin, l.bar_track.xmax, top - thumb_h, top};
  }
  else {
    l.bar_thumb = {0, 0, 0, 0};
  }
  return l;
}

bool line_rect(const State &state, const Layout &layout, const int line, rctf *r_rect)
{
  if (line < 0 || line >= int(state.lines.size())) {
    return false;
  }
  const Metrics m = metrics(state);
  const Line &l = state.lines[line];
  const float right = layout.max_scroll > 0.0f ? layout.bar_track.xmin - m.pad * 0.2f :
                                                 layout.list.xmax;
  const float top = layout.list.ymax - (l.top - state.scroll);
  *r_rect = {layout.list.xmin, right, top - l.height, top};
  return r_rect->ymax > layout.list.ymin && r_rect->ymin < layout.list.ymax;
}

rctf trailing_rect(const State &state, const Layout & /*layout*/, const rctf &line)
{
  const Metrics m = metrics(state);
  const int font = blf_mono_font;
  BLF_size(font, m.fs * 0.78f);
  int index = -1;
  for (int i = 0; i < int(state.lines.size()); i++) {
    if (state.lines[i].disclosure) {
      index = i;
    }
  }
  const char *text = index >= 0 ? state.lines[index].trailing.c_str() : "";
  const float w = BLF_width(font, text, strlen(text));
  return {line.xmax - m.pad * 0.6f - w - m.pad * 0.6f, line.xmax, line.ymin, line.ymax};
}

bool pickable(const State &state, const int line)
{
  if (line < 0 || line >= int(state.lines.size()) || state.gated) {
    return false;
  }
  const Line &l = state.lines[line];
  return l.kind != LineKind::Note && l.row >= 0 && state.rows[l.row].enabled;
}

bool footer_enabled(const State &state, const int footer)
{
  return footer >= 0 && footer < int(state.footers.size()) &&
         state.rows[state.footers[footer]].enabled;
}


Hit hit_test(const State &state, const Layout &layout, const float mx, const float my)
{
  Hit hit;
  hit.chip = state.anchor_valid && BLI_rctf_isect_pt(&state.anchor, mx, my);
  hit.inside = BLI_rctf_isect_pt(&layout.card, mx, my);
  if (!hit.inside) {
    return hit;
  }
  for (int i = 0; i < int(layout.tab_cells.size()); i++) {
    if (BLI_rctf_isect_pt(&layout.tab_cells[i], mx, my)) {
      hit.tab = i;
      return hit;
    }
  }
  for (int i = 0; i < int(layout.footer_cells.size()); i++) {
    if (BLI_rctf_isect_pt(&layout.footer_cells[i], mx, my)) {
      hit.footer = i;
      return hit;
    }
  }
  if (layout.max_scroll > 0.0f) {
    rctf track = layout.bar_track;
    BLI_rctf_pad(&track, metrics(state).pad * 0.25f, 0.0f);
    if (BLI_rctf_isect_pt(&track, mx, my)) {
      hit.thumb = BLI_rctf_isect_pt(&layout.bar_thumb, mx, my) ||
                  (mx >= layout.bar_thumb.xmin - metrics(state).pad * 0.25f &&
                   my >= layout.bar_thumb.ymin && my <= layout.bar_thumb.ymax);
      hit.track = !hit.thumb;
      return hit;
    }
  }
  if (!BLI_rctf_isect_pt(&layout.list, mx, my)) {
    return hit;
  }
  for (int i = 0; i < int(state.lines.size()); i++) {
    rctf r;
    if (line_rect(state, layout, i, &r) && BLI_rctf_isect_pt(&r, mx, my)) {
      if (ELEM(state.lines[i].kind, LineKind::Note, LineKind::Divider)) {
        return hit;
      }
      hit.line = i;
      if (state.lines[i].disclosure) {
        const rctf t = trailing_rect(state, layout, r);
        hit.trailing = BLI_rctf_isect_pt(&t, mx, my);
      }
      return hit;
    }
  }
  return hit;
}

void scroll_into_view(State &state, const int line)
{
  const Layout layout = layout_compute(state);
  if (line < 0 || line >= int(state.lines.size())) {
    return;
  }
  const Line &l = state.lines[line];
  const float view = BLI_rctf_size_y(&layout.list);
  if (l.top < state.scroll_target) {
    state.scroll_target = l.top;
  }
  else if (l.top + l.height > state.scroll_target + view) {
    state.scroll_target = l.top + l.height - view;
  }
  state.scroll_target = std::clamp(state.scroll_target, 0.0f, layout.max_scroll);
}

void reveal_levels(State &state, const int line)
{
  int last = line;
  while (last + 1 < int(state.lines.size()) && state.lines[last + 1].kind == LineKind::Level) {
    last++;
  }
  /* The last level first, then the disclosure: when the block is taller than
   * the list, the line the user clicked wins. */
  scroll_into_view(state, last);
  scroll_into_view(state, line);
}

void reveal_current(State &state)
{
  for (int i = 0; i < int(state.lines.size()); i++) {
    const Line &line = state.lines[i];
    if (line.kind == LineKind::Pick && line.row >= 0 && state.rows[line.row].current) {
      scroll_into_view(state, i);
      break;
    }
  }
  state.scroll = state.scroll_target;
}

void move_focus(State &state, const int step)
{
  const int count = int(state.lines.size());
  int i = state.focus >= 0 ? state.focus : (step > 0 ? -1 : count);
  for (int n = 0; n < count; n++) {
    i += step;
    if (i < 0 || i >= count) {
      return;
    }
    if (pickable(state, i)) {
      state.focus = i;
      scroll_into_view(state, i);
      return;
    }
  }
}

bool step_motion(State &state)
{
  const bool reduced = ui::mixar_motion_reduced();
  const float k = reduced ? 1.0f : 0.25f;
  bool moved = ease(state.scroll, state.scroll_target, reduced ? 1.0f : 0.3f, 0.5f);
  const float goal_pill = float(std::max(0, tab_index(state, state.tab)));
  moved |= ease(state.pill, goal_pill, reduced ? 1.0f : 0.28f, SNAP);
  for (int i = 0; i < int(state.hover_mix.size()); i++) {
    const float goal = (state.hover == i || state.focus == i) ? 1.0f : 0.0f;
    moved |= ease(state.hover_mix[i], goal, k, SNAP);
  }
  for (int i = 0; i < int(state.footer_mix.size()); i++) {
    moved |= ease(state.footer_mix[i], state.hover_footer == i ? 1.0f : 0.0f, k, SNAP);
  }
  const float bar_goal = (state.hover_bar || state.dragging_bar) ? 1.0f : 0.0f;
  moved |= ease(state.bar_mix, bar_goal, k, SNAP);
  return moved;
}

void drag_bar(State &state, const Layout &layout, const float my)
{
  const float track_h = BLI_rctf_size_y(&layout.bar_track);
  const float thumb_h = BLI_rctf_size_y(&layout.bar_thumb);
  const float travel = std::max(1.0f, track_h - thumb_h);
  const float t = std::clamp((layout.bar_track.ymax - (my + state.drag_grab)) / travel, 0.0f, 1.0f);
  state.scroll = state.scroll_target = t * layout.max_scroll;
}

}  // namespace blender::agent_model_card
