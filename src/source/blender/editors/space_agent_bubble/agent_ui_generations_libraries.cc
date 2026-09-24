/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "BKE_context.hh"
#include "BLI_string.h"
#include "DNA_windowmanager_types.h"
#include "RNA_access.hh"
#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "WM_types.hh"
#include "agent_ui_generations_intern.hh"
#include "agent_ui_text.hh"
#include "agent_ui_theme.hh"
#include <algorithm>
#include <cmath>
#include "agent_ui_generations_clip.hh"

namespace blender {
GenLibraryMetrics agent_ui_generations_library_metrics(const GenFrame &frame,
                                                       const GenPaneData &data)
{
  GenLibraryMetrics m{};
  const float pad = frame.pad;
  m.add = {frame.rail[0].xmin,
           frame.rail[0].xmax,
           frame.grid_bottom,
           frame.grid_bottom + frame.lib_row_h};
  const float list_gap = std::max(frame.gap * 0.5f, 4.0f * frame.u);
  m.view = {m.add.xmin, m.add.xmax, m.add.ymax + list_gap, frame.rail[1].ymin - list_gap};
  if (m.view.ymax < m.view.ymin) {
    m.view.ymax = m.view.ymin;
  }
  m.pitch = std::max(frame.lib_row_h + frame.gap * 0.35f, frame.font_lib * 1.5f);
  const float height = std::max(0.0f, BLI_rctf_size_y(&m.view));
  m.max_scroll = std::max(0.0f, data.lib_names.size() * m.pitch - list_gap - height);
  m.offset = std::clamp(data.library_scroll / 100.0f, 0.0f, 1.0f) * m.max_scroll;
  m.first_row = m.pitch > 0.0f ? int(m.offset / m.pitch) : 0;
  m.end_row = m.pitch > 0.0f ?
                  std::min(int(data.lib_names.size()), int(std::ceil((m.offset + height) / m.pitch))) :
                  0;
  const float bar = std::max(6.0f, frame.gap * 0.45f);
  m.scrollbar = {frame.rail[0].xmax + pad * 0.25f,
                 std::max(frame.rail[0].xmax + pad * 0.25f + bar, frame.rail_div_x - pad * 0.2f),
                 m.view.ymin,
                 m.view.ymax};
  return m;
}

void agent_ui_generations_scrollbar(ui::Block *block,
                                    PointerRNA *wm,
                                    const char *property,
                                    const rctf &rect,
                                    const float visible_height,
                                    const float maximum)
{
  if (maximum <= 0 || visible_height <= 0 || !RNA_struct_find_property(wm, property)) {
    return;
  }
  ui::block_emboss_set(block, ui::EmbossType::Emboss);
  ui::Button *scroll = uiDefButR(block,
                                 ui::ButtonType::Scroll,
                                 "",
                                 int(rect.xmin),
                                 int(rect.ymin),
                                 int(BLI_rctf_size_x(&rect)),
                                 int(BLI_rctf_size_y(&rect)),
                                 wm,
                                 property,
                                 0,
                                 0,
                                 100,
                                 "Scroll library");
  ui::button_scrollbar_visual_height_set(scroll, 100.0f * visible_height / maximum);
  ui::block_emboss_set(block, ui::EmbossType::None);
}

void agent_ui_generations_libraries(
    const bContext *C, ui::Block *block, const GenFrame &frame, const GenPaneData &data)
{
  if (data.source != GEN_SOURCE_LIBRARY) {
    return;
  }
  const auto m = agent_ui_generations_library_metrics(frame, data);
  const float u = frame.u;
  const float inner = std::max(frame.pad * GEN_PAD_SHRINK, 0.4f * frame.font_lib);
  MIXAR_THEME_LOAD(text, Text);
  MIXAR_THEME_LOAD(dim, TextSecondary);
  const float bg[4] = GEN_COL_PILL_OFF;
  {
    const GenViewportClip clip(m.view);
    for (int i = m.first_row; i < m.end_row; i++) {
      const std::string &name = data.lib_names[i];
      const bool active = name == data.library;
      rctf r = m.view;
      r.ymax += m.offset - i * m.pitch;
      r.ymin = r.ymax - m.pitch + frame.gap * 0.35f;
      if (active) {
        pane_fill_round(&r, std::min(GEN_META_RADIUS * u, BLI_rctf_size_y(&r) * 0.35f), bg);
      }
      char label[64];
      BLI_strncpy(label, name.c_str(), sizeof(label));
      pane_fit_text(label, std::max(1.0f, BLI_rctf_size_x(&r) - 2.0f * inner), frame.font_lib);
      pane_label_left(label, r.xmin + inner, BLI_rctf_cent_y(&r), frame.font_lib, active ? text : dim);
      rctf hit;
      if (!BLI_rctf_isect(&r, &m.view, &hit) || BLI_rctf_size_y(&hit) < 1.0f) {
        continue;
      }
      ui::Button *but = uiDefButO(block,
                                  ui::ButtonType::But,
                                  "wm.context_set_string",
                                  wm::OpCallContext::InvokeDefault,
                                  "",
                                  int(hit.xmin),
                                  int(hit.ymin),
                                  short(BLI_rctf_size_x(&hit)),
                                  short(BLI_rctf_size_y(&hit)),
                                  "");
      pane_but_tooltip_owned(but, name.c_str());
      PointerRNA *op = ui::button_operator_ptr_ensure(but);
      RNA_string_set(op, "data_path", "window_manager.mixar_generations_library");
      RNA_string_set(op, "value", active ? "" : name.c_str());
      ui::button_func_identity_compare_set(but, agent_ui_generations_button_identity);
    }
  }
  const rctf &r = m.add;
  pane_fill_round(&r, std::min(GEN_META_RADIUS * u, BLI_rctf_size_y(&r) * 0.35f), bg);
  char add_label[64];
  BLI_strncpy(add_label, "+  Add Library…", sizeof(add_label));
  pane_fit_text(add_label, std::max(1.0f, BLI_rctf_size_x(&r) - 2.0f * inner), frame.font_lib);
  pane_label_left(add_label, r.xmin + inner, BLI_rctf_cent_y(&r), frame.font_lib, text);
  uiDefButO(block,
            ui::ButtonType::But,
            "mixar.generations_add_library",
            wm::OpCallContext::InvokeDefault,
            "",
            int(r.xmin),
            int(r.ymin),
            short(BLI_rctf_size_x(&r)),
            short(BLI_rctf_size_y(&r)),
            "Connect a folder as an asset library");
  PointerRNA wm = RNA_id_pointer_create(&CTX_wm_manager(C)->id);
  agent_ui_generations_scrollbar(
      block, &wm, "mixar_generations_library_scroll", m.scrollbar, BLI_rctf_size_y(&m.view), m.max_scroll);
}
}  // namespace blender
