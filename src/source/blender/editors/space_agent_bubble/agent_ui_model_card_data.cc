/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The model card's data: Python's picker read off the WindowManager
 * (`wm.mixar_agent_tabs` / `_rows`, byok/core/picker.py's wire format: records
 * split by U+001E, fields by U+001F), the pick operator's poll, and the open
 * tab's list built from them.
 */

#include <algorithm>

#include "MEM_guardedalloc.h"

#include "BLI_time.h"

#include "BLT_translation.hh"

#include "BKE_context.hh"

#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_ui_model_card_intern.hh"

namespace blender::agent_model_card {

namespace {

constexpr const char *PICK_OP = "MIXAR_OT_agent_pick";
/** The pick poll is Python (a turn in flight, a change being saved): asked at
 * 10 Hz, not every 60 Hz tick. The operator checks it again when it runs. */
constexpr double POLL_SECONDS = 0.1;
constexpr char RS = '\x1e';
constexpr char FS = '\x1f';

std::vector<std::string> split(const std::string &text, const char sep)
{
  std::vector<std::string> out;
  if (text.empty()) {
    return out;
  }
  size_t start = 0;
  while (true) {
    const size_t end = text.find(sep, start);
    out.push_back(text.substr(start, end == std::string::npos ? std::string::npos : end - start));
    if (end == std::string::npos) {
      return out;
    }
    start = end + 1;
  }
}

std::string wm_string(wmWindowManager *wm, const char *name)
{
  PointerRNA ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return "";
  }
  char fixed[256];
  int len = 0;
  char *value = RNA_property_string_get_alloc(&ptr, prop, fixed, sizeof(fixed), &len);
  std::string out = value ? std::string(value, size_t(len)) : std::string();
  if (value && value != fixed) {
    MEM_delete(value);
  }
  return out;
}

}  // namespace

bool is_default_row(const Row &row)
{
  return row.tab == "MIXIE" && row.kind == "model" && row.model.empty();
}

int tab_index(const State &state, const std::string &id)
{
  for (int i = 0; i < int(state.tabs.size()); i++) {
    if (state.tabs[i].id == id) {
      return i;
    }
  }
  return -1;
}

/** The open tab's list: notes, picks (the current one carrying the thinking
 * disclosure), levels while unfolded; footers go to the pinned bar. */
void rebuild_lines(State &state)
{
  const Metrics m = metrics(state);
  state.lines.clear();
  state.footers.clear();
  float y = 0.0f;
  auto push = [&](Line line, const float height) {
    line.top = y;
    line.height = height;
    y += height;
    state.lines.push_back(std::move(line));
  };
  if (state.gated && !state.gate_text.empty()) {
    Line note;
    note.kind = LineKind::Note;
    note.trailing = state.gate_text;
    push(note, m.note_h);
  }
  const int tab = tab_index(state, state.tab);
  if (tab >= 0 && !state.tabs[tab].note.empty()) {
    Line note;
    note.kind = LineKind::Note;
    note.trailing = state.tabs[tab].note;
    push(note, m.note_h);
  }
  int last_pick = -1;
  for (int i = 0; i < int(state.rows.size()); i++) {
    const Row &row = state.rows[i];
    if (row.tab != state.tab) {
      continue;
    }
    if (row.kind == "model") {
      Line line;
      line.kind = LineKind::Pick;
      line.row = i;
      line.trailing = row.meta;
      last_pick = int(state.lines.size());
      push(line, m.row_h);
      if (is_default_row(row)) {
        Line divider;
        divider.kind = LineKind::Divider;
        push(divider, m.fs * 0.7f);
      }
    }
    else if (row.kind == "thinking" && last_pick >= 0) {
      Line &pick = state.lines[last_pick];
      pick.disclosure = true;
      pick.trailing = row.label + (state.thinking_open ? "  \xe2\x96\xbe" : "  \xe2\x80\xba");
    }
    else if (row.kind == "level" && state.thinking_open && last_pick >= 0) {
      Line line;
      line.kind = LineKind::Level;
      line.row = i;
      line.level_of = last_pick;
      push(line, m.level_h);
    }
    else if (row.kind == "note") {
      Line note;
      note.kind = LineKind::Note;
      note.trailing = row.label;
      push(note, m.note_h);
    }
    else if (row.kind == "footer") {
      state.footers.push_back(i);
    }
  }
  state.hover_mix.assign(state.lines.size(), 0.0f);
  state.footer_mix.assign(state.footers.size(), 0.0f);
  state.hover = state.pressed = state.focus = -1;
  state.hover_footer = -1;
  const Layout layout = layout_compute(state);
  state.scroll_target = std::clamp(state.scroll_target, 0.0f, layout.max_scroll);
  state.scroll = std::clamp(state.scroll, 0.0f, layout.max_scroll);
}

/** Read Python's picker and the pick operator's poll; rebuild on a change. */
bool refresh(bContext *C, State &state, const bool force)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  const std::string tabs = wm_string(wm, "mixar_agent_tabs");
  const std::string rows = wm_string(wm, "mixar_agent_rows");
  bool gated = state.gated;
  const double now = BLI_time_now_seconds();
  if (force || now - state.polled_at >= POLL_SECONDS) {
    wmOperatorType *ot = WM_operatortype_find(PICK_OP, true);
    gated = ot && !WM_operator_poll_context(C, ot, wm::OpCallContext::InvokeDefault);
    state.polled_at = now;
  }
  if (!force && tabs == state.raw_tabs && rows == state.raw_rows && gated == state.gated) {
    return false;
  }
  state.raw_tabs = tabs;
  state.raw_rows = rows;
  state.source = wm_string(wm, "mixar_agent_source");
  state.gated = gated;
  state.gate_text = !gated ? "" :
                    wm_string(wm, "mixar_agent_source_state") == "BUSY" ?
                             IFACE_("Saving your change\xe2\x80\xa6") :
                             IFACE_("Finish or stop the current reply to change the model");
  state.tabs.clear();
  for (const std::string &rec : split(tabs, RS)) {
    const std::vector<std::string> f = split(rec, FS);
    if (f.size() >= 6) {
      state.tabs.push_back({f[0], f[1], f[3], f[4], f[5], f[2] == "1", f.size() > 6 ? f[6] : ""});
    }
  }
  state.rows.clear();
  for (const std::string &rec : split(rows, RS)) {
    const std::vector<std::string> f = split(rec, FS);
    if (f.size() >= 9) {
      state.rows.push_back({f[0], f[1], f[2], f[3], f[6], f[7], f[8], f[4] == "1", f[5] == "1"});
    }
  }
  if (tab_index(state, state.tab) < 0) {
    state.tab = tab_index(state, state.source) >= 0 ? state.source :
                !state.tabs.empty()                 ? state.tabs[0].id :
                                                      "";
  }
  rebuild_lines(state);
  return true;
}

}  // namespace blender::agent_model_card
