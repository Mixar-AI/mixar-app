/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The Library pane's search results. The request itself is Python
 * (`agent_bubble/core/library_search.py`, started by the search row): it
 * writes its state onto the WindowManager, and this file reads that state
 * and narrows a gathered item list to the hits, best first.
 *
 * `wm.mixar_generations_search_hits` holds one line per hit, best first:
 * `score<TAB>library<TAB>blend_file<TAB>id_dir<TAB>name`, where `blend_file`
 * is library-relative with forward slashes. An item matches on library name,
 * ID folder and datablock name, and on its .blend path ending in the hit's.
 */

#include <algorithm>
#include <cstdlib>
#include <string>
#include <vector>

#include "MEM_guardedalloc.h"

#include "BLI_string.h"

#include "RNA_access.hh"

#include "agent_ui_generations_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

struct GenHit {
  float score;
  std::string library, blend, id_dir, name;
};

std::vector<GenHit> parse_hits(const std::string &text)
{
  std::vector<GenHit> hits;
  size_t start = 0;
  while (start < text.size()) {
    size_t end = text.find('\n', start);
    if (end == std::string::npos) {
      end = text.size();
    }
    const std::string line = text.substr(start, end - start);
    start = end + 1;
    std::string field[5];
    size_t pos = 0;
    int n = 0;
    for (; n < 5; n++) {
      const size_t tab = (n < 4) ? line.find('\t', pos) : std::string::npos;
      field[n] = line.substr(pos, tab == std::string::npos ? std::string::npos : tab - pos);
      if (tab == std::string::npos) {
        break;
      }
      pos = tab + 1;
    }
    if (n < 4 || field[4].empty()) {
      continue;
    }
    hits.push_back({float(std::atof(field[0].c_str())), field[1], field[2], field[3], field[4]});
  }
  return hits;
}

bool path_ends_with(const char *path, const std::string &tail)
{
  std::string p(path);
  std::replace(p.begin(), p.end(), '\\', '/');
  if (tail.empty() || p.size() < tail.size()) {
    return false;
  }
  if (p.compare(p.size() - tail.size(), tail.size(), tail) != 0) {
    return false;
  }
  /* Whole path segments only: "a/rust.blend" must not match "bigrust.blend". */
  return p.size() == tail.size() || p[p.size() - tail.size() - 1] == '/';
}

std::string read_hits(PointerRNA *wm_ptr)
{
  PropertyRNA *prop = RNA_struct_find_property(wm_ptr, "mixar_generations_search_hits");
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return {};
  }
  char *text = RNA_property_string_get_alloc(wm_ptr, prop, nullptr, 0, nullptr);
  std::string out = text ? text : "";
  if (text) {
    MEM_delete(text);
  }
  return out;
}

}  // namespace

void agent_ui_generations_read_search(PointerRNA *wm_ptr, GenPaneData *data)
{
  gen_read_string(
      wm_ptr, "mixar_generations_search_ref", data->search_ref, sizeof(data->search_ref));
  gen_read_enum_id(
      wm_ptr, "mixar_generations_search_state", data->search_state, sizeof(data->search_state));
  gen_read_string(wm_ptr,
                  "mixar_generations_search_message",
                  data->search_message,
                  sizeof(data->search_message));
  data->search_active = STREQ(data->search_state, "RUNNING") ||
                        STREQ(data->search_state, "DONE");
  data->search_hits = STREQ(data->search_state, "DONE") ? read_hits(wm_ptr) : std::string();
}

void agent_ui_generations_apply_search(GenPaneData *data)
{
  std::vector<GenItem> kept;
  for (const GenHit &hit : parse_hits(data->search_hits)) {
    for (const GenItem &item : data->items) {
      if (item.kind == GEN_ITEM_ASSET && hit.name == item.name && hit.id_dir == item.id_dir &&
          hit.library == item.model_label && path_ends_with(item.path, hit.blend))
      {
        kept.push_back(item);
        kept.back().score = hit.score;
        break;
      }
    }
  }
  data->items = std::move(kept);
  data->count = int(data->items.size());
}

}  // namespace blender
