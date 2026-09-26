/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Widgets of the Zen Mode Scenes drawer's draw pass: the RNA readers that
 * pull `wm.mixar_scene_tabs` into the region runtime, elided text, the status
 * pill palette and the pill painter. The layout of the pass itself is
 * `view3d_scenes_drawer_draw.cc`.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLF_api.hh"

#include "BLI_math_base.h"
#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_userdef_types.h"
#include "DNA_windowmanager_types.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"
#include "UI_mixar_theme.hh"
#include "UI_resources.hh"

#include "view3d_scenes_drawer.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::view3d_scenes_drawer {

void read_string(PointerRNA *ptr, const char *name, std::string &out)
{
  out.clear();
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (prop == nullptr) {
    return;
  }
  char fixed[256];
  char *buf = RNA_property_string_get_alloc(ptr, prop, fixed, sizeof(fixed), nullptr);
  out.assign(buf ? buf : "");
  if (buf != fixed && buf != nullptr) {
    /* 5.2: MEM_freeN is gone for void*; same port as view3d_agent_panel_sync.cc. */
    MEM_delete_void(static_cast<void *>(buf));
  }
}

int read_int(PointerRNA *ptr, const char *name, const int fallback)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return prop ? RNA_property_int_get(ptr, prop) : fallback;
}

bool read_bool(PointerRNA *ptr, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return prop ? RNA_property_boolean_get(ptr, prop) : false;
}

/** Pull the tab list Python keeps on the WindowManager into the runtime,
 * keeping the previous rects until this pass lays them out again. */
void sync_cards(const bContext *C, ScenesDrawerRuntime *runtime)
{
  runtime->cards.clear();
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *tabs = RNA_struct_find_property(&wm_ptr, "mixar_scene_tabs");
  if (tabs == nullptr) {
    return;
  }
  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&wm_ptr, tabs, &iter);
  while (iter.valid) {
    PointerRNA tab_ptr = iter.ptr;
    ScenesDrawerCard card;
    read_string(&tab_ptr, "scene_name", card.scene_name);
    read_string(&tab_ptr, "session_id", card.session_id);
    read_string(&tab_ptr, "last_text", card.last_text);
    const int status = read_int(&tab_ptr, "status", 0);
    card.status = (status >= 0 && status <= 3) ? ScenesDrawerTabStatus(status) :
                                                 ScenesDrawerTabStatus::Idle;
    card.workers_done = read_int(&tab_ptr, "workers_done", 0);
    card.workers_total = read_int(&tab_ptr, "workers_total", 0);
    card.is_active = read_bool(&tab_ptr, "is_active");
    card.attention = read_bool(&tab_ptr, "attention");
    runtime->cards.push_back(std::move(card));
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
}

void with_alpha(const float src[4], const float alpha, float r_out[4])
{
  r_out[0] = src[0];
  r_out[1] = src[1];
  r_out[2] = src[2];
  r_out[3] = src[3] * alpha;
}

void draw_elided(const int font_id,
                 const std::string &text,
                 const float x,
                 const float baseline_y,
                 const float max_width,
                 const float color[4])
{
  if (text.empty() || max_width <= 0.0f) {
    return;
  }
  BLF_color4fv(font_id, color);
  if (BLF_width(font_id, text.c_str(), text.size()) <= max_width) {
    BLF_position(font_id, x, baseline_y, 0.0f);
    BLF_draw(font_id, text.c_str(), text.size());
    return;
  }
  const float ellipsis_w = BLF_width(font_id, "…", strlen("…"));
  float measured = 0.0f;
  const size_t fit = BLF_width_to_strlen(
      font_id, text.c_str(), text.size(), std::max(max_width - ellipsis_w, 0.0f), &measured);
  std::string cut = text.substr(0, fit) + "…";
  BLF_position(font_id, x, baseline_y, 0.0f);
  BLF_draw(font_id, cut.c_str(), cut.size());
}

const char *status_label(const ScenesDrawerTabStatus status)
{
  switch (status) {
    case ScenesDrawerTabStatus::Working:
      return "Working";
    case ScenesDrawerTabStatus::Waiting:
      return "Waiting for you";
    case ScenesDrawerTabStatus::Done:
      return "Done";
    default:
      return "Idle";
  }
}

const float *status_color(const ScenesDrawerTabStatus status)
{
  const ui::mixar_tokens::Palette &zen = ui::mixar_tokens::mixar_zen();
  switch (status) {
    case ScenesDrawerTabStatus::Working:
      return zen.primary;
    case ScenesDrawerTabStatus::Waiting:
      return zen.warning;
    case ScenesDrawerTabStatus::Done:
      return zen.action;
    default:
      return zen.secondary;
  }
}

void draw_pill(const rctf &rect, const float fill[4], const float radius)
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&rect, true, radius, fill);
}

}  // namespace blender::view3d_scenes_drawer
