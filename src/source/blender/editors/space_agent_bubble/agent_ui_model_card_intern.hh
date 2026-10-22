/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The model card's state, layout and painter, shared by
 * agent_ui_model_card.cc (data, layout, operator, QA) and
 * agent_ui_model_card_draw.cc (paint). See agent_ui_model_card.hh.
 */

#pragma once

#include <string>
#include <vector>

#include "BLI_rect.h"

namespace blender {

struct bContext;
struct wmTimer;
struct wmWindow;

namespace agent_model_card {

/** One source tab: `id|label|enabled|cost|note|heading|action` on the wire.
 * `action == "settings"`: the tab is a button, not a page — a click opens AI
 * Provider Settings (no key saved: there is nothing to pick from). */
struct Tab {
  std::string id, label, cost, note, heading;
  bool enabled = true;
  std::string action;
};

/** One row: `tab|kind|label|meta|current|enabled|provider|model|thinking`. */
struct Row {
  std::string tab, kind, label, meta, provider, model, thinking;
  bool current = false;
  bool enabled = true;
};

/** Divider: the hairline under "Mixar default", setting the server's pick
 * apart from the specific models. */
enum class LineKind { Pick, Level, Note, Divider };

/** One drawn line of the open tab's list. A pick that owns the thinking
 * disclosure carries it as its trailing text (`disclosure`). */
struct Line {
  LineKind kind = LineKind::Pick;
  int row = -1;      /* Index into State::rows. */
  int level_of = -1; /* A level line: the pick line it unfolds from. */
  std::string trailing;
  bool disclosure = false;
  float top = 0.0f, height = 0.0f; /* Content space, 0 = top of the list. */
};

/** Sizes in window pixels, all derived from the island's body text size. */
struct Metrics {
  float fs, pad, radius, tabs_h, tab_inset, caption_h, row_h, level_h, note_h, footer_h;
  float check_w, bar_w, gap, margin, width;
};

struct Layout {
  rctf card, tabs, caption, list, footer, bar_track, bar_thumb;
  std::vector<rctf> tab_cells;
  std::vector<rctf> footer_cells; /* One per footer row, left to right. */
  float content_h = 0.0f, max_scroll = 0.0f;
};

struct State {
  wmWindow *win = nullptr;
  void *draw_handle = nullptr;
  wmTimer *timer = nullptr;
  double opened_at = 0.0;

  /* The chip (window px) and the island's body text size, from the last
   * draw of the chip row. */
  rctf anchor = {};
  bool anchor_valid = false;
  float text_size = 0.0f;

  /* Python's picker, as last read; the raw strings detect a change. */
  std::string raw_tabs, raw_rows, source;
  std::vector<Tab> tabs;
  std::vector<Row> rows;
  double polled_at = 0.0; /* When the pick operator's poll last ran. */

  /* The card's own state. */
  std::string tab;          /* The open tab's id. */
  bool thinking_open = false;
  std::vector<Line> lines;  /* The open tab's list. */
  std::vector<int> footers; /* Rows of the open tab's footer, in order. */
  bool gated = false;       /* The pick operator's poll fails. */
  std::string gate_text;

  /* Motion. */
  float scroll = 0.0f, scroll_target = 0.0f;
  float pill = 0.0f; /* Eased tab index of the green pill. */
  std::vector<float> hover_mix;
  std::vector<float> footer_mix;
  float bar_mix = 0.0f;
  bool risen = false; /* The open rise has drawn its last frame. */

  /* Pointer. */
  int hover = -1, pressed = -1, focus = -1; /* Line indices. */
  int hover_tab = -1, hover_footer = -1;
  bool hover_trailing = false, hover_bar = false;
  bool dragging_bar = false;
  float drag_grab = 0.0f;
  int cursor = -1; /* The cursor the card set over itself; -1: the regions'. */
};

/** The open card, or null (one island, one card). */
extern State *g_state;

Metrics metrics(const State &state);
/** \a rise: how far below its place the card sits (#card_rise while it opens). */
Layout layout_compute(const State &state, float rise = 0.0f);
/** The visible rect of \a line (window px), scrolled; false when outside the list. */
bool line_rect(const State &state, const Layout &layout, int line, rctf *r_rect);
/** The trailing (disclosure) rect of a pick line. */
rctf trailing_rect(const State &state, const Layout &layout, const rctf &line_rect);
float appear_factor(const State &state);
/** How far below its place the card is drawn now, rising in as it opens. */
float card_rise(const State &state);

/** The window draw callback (agent_ui_model_card_draw.cc). */
void draw(const wmWindow *win, void *customdata);

/* Data (agent_ui_model_card_data.cc). */

/** "Mixar default": the Mixie tab's pick without a model (the server's). */
bool is_default_row(const Row &row);
/** Index of the tab \a id, or -1. */
int tab_index(const State &state, const std::string &id);
/** The open tab's list (notes, picks, unfolded levels) and its footers. */
void rebuild_lines(State &state);
/** Read Python's picker and the pick poll; rebuild on a change or \a force.
 * True when it rebuilt. */
bool refresh(bContext *C, State &state, bool force);

/* Input (agent_ui_model_card_layout.cc). */

/** What is under the pointer. */
struct Hit {
  int line = -1, tab = -1, footer = -1;
  bool trailing = false, thumb = false, track = false, inside = false, chip = false;
};
bool pickable(const State &state, int line);
/** The footer action \a footer can be clicked (drawn dimmed otherwise). */
bool footer_enabled(const State &state, int footer);
Hit hit_test(const State &state, const Layout &layout, float mx, float my);
void scroll_into_view(State &state, int line);
/** After the thinking disclosure on \a line unfolds: bring its levels into
 * view, keeping \a line itself visible when both do not fit. */
void reveal_levels(State &state, int line);
/** Jump (no easing) so the open tab's current pick is in view. */
void reveal_current(State &state);
void move_focus(State &state, int step);
/** One 60 Hz step of every eased value; true while any of them moved. */
bool step_motion(State &state);
void drag_bar(State &state, const Layout &layout, float my);

}  // namespace agent_model_card
}  // namespace blender
