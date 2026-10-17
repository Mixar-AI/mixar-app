/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The model card's QA targets, exported once per island window through its
 * WINDOW region as window-level targets (the card is drawn over every region):
 * `model_card` (text = the open tab's id), `model_card_tab` (label; value =
 * id; sel = open), `model_card_row` (label; value = model; detail = "pick" |
 * "level"; sel = current; only the visible part of a row),
 * `model_card_disclosure` (value = "open" | "closed"), `model_card_note`,
 * `model_card_footer` and `model_card_scrollbar` (value = scroll fraction).
 */

#include <string>

#include "BLI_listbase_iterator.hh"
#include "BLI_rect.h"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "../interface/interface_qa_inspect.hh"

#include "agent_ui_model_card_intern.hh"

namespace blender::agent_model_card {

namespace {

bool is_host_region(const ScrArea *area, const ARegion *region)
{
  for (const ARegion &r : area->regionbase) {
    if (r.regiontype == RGN_TYPE_WINDOW && !(r.flag & RGN_FLAG_HIDDEN)) {
      return &r == region;
    }
  }
  return false;
}

void qa_targets(const wmWindow *win,
                const ScrArea *area,
                const ARegion *region,
                std::vector<MixarQATarget> &r_targets)
{
  const State *state = g_state;
  if (!state || state->win != win || !is_host_region(area, region)) {
    return;
  }
  const Layout layout = layout_compute(*state, card_rise(*state)); /* As drawn. */
  auto add = [&](const char *surface, const std::string &text, const rctf &rect) -> MixarQATarget & {
    MixarQATarget target;
    target.surface = surface;
    target.text = text;
    BLI_rcti_rctf_copy_round(&target.rect_win, &rect);
    target.window_level = true;
    r_targets.push_back(std::move(target));
    return r_targets.back();
  };
  add("model_card", state->tab, layout.card);
  for (int i = 0; i < int(state->tabs.size()) && i < int(layout.tab_cells.size()); i++) {
    MixarQATarget &t = add("model_card_tab", state->tabs[i].label, layout.tab_cells[i]);
    t.value = state->tabs[i].id;
    t.index = i;
    t.sel = state->tabs[i].id == state->tab;
    t.enabled = state->tabs[i].enabled;
    t.detail = state->tabs[i].action;
  }
  for (int i = 0; i < int(state->lines.size()); i++) {
    rctf r;
    if (!line_rect(*state, layout, i, &r)) {
      continue;
    }
    rctf visible;
    BLI_rctf_isect(&r, &layout.list, &visible);
    const Line &line = state->lines[i];
    if (line.kind == LineKind::Divider) {
      continue;
    }
    if (line.kind == LineKind::Note) {
      add("model_card_note", line.trailing, visible).index = i;
      continue;
    }
    const Row &row = state->rows[line.row];
    MixarQATarget &t = add("model_card_row", row.label, visible);
    t.value = row.model;
    t.detail = line.kind == LineKind::Level ? "level" : "pick";
    t.index = i;
    t.sel = row.current;
    t.enabled = row.enabled && !state->gated;
    if (line.disclosure) {
      rctf trailing = trailing_rect(*state, layout, r);
      BLI_rctf_isect(&trailing, &layout.list, &trailing);
      MixarQATarget &d = add("model_card_disclosure", line.trailing, trailing);
      d.value = state->thinking_open ? "open" : "closed";
      d.enabled = t.enabled;
    }
  }
  for (int i = 0; i < int(state->footers.size()) && i < int(layout.footer_cells.size()); i++) {
    const Row &row = state->rows[state->footers[i]];
    MixarQATarget &t = add("model_card_footer", row.label, layout.footer_cells[i]);
    t.index = i;
    t.enabled = row.enabled;
  }
  if (layout.max_scroll > 0.0f) {
    MixarQATarget &t = add("model_card_scrollbar", "", layout.bar_thumb);
    t.value = std::to_string(state->scroll / layout.max_scroll);
  }
}

}  // namespace

void qa_register()
{
  Mixar_qa_register_target_provider(SPACE_AGENT_BUBBLE, qa_targets);
}

}  // namespace blender::agent_model_card
