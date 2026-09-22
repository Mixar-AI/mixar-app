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
GenLibraryMetrics agent_ui_generations_library_metrics(const rctf &panel,
                                                       const float u,
                                                       const GenPaneData &data)
{
  GenLibraryMetrics m{};
  m.add = {GEN_XL(panel, GEN_PAD, u),
           GEN_XL(panel, GEN_PAD + GEN_RAIL_W, u),
           panel.ymin + GEN_PAD * u,
           panel.ymin + (GEN_PAD + GEN_LIB_ROW_H) * u};
  m.view = {m.add.xmin,
            m.add.xmax,
            m.add.ymax + GEN_LIB_ROW_PITCH * u - GEN_LIB_ROW_H * u,
            GEN_YTOP(panel, GEN_LIB_ROWS_Y, u)};
  m.pitch = std::max(GEN_LIB_ROW_PITCH * u, GEN_LIB_FONT * agent_ui_text_unit() * 1.5f);
  const float height = std::max(0.0f, BLI_rctf_size_y(&m.view));
  m.max_scroll = std::max(0.0f, data.lib_names.size() * m.pitch - 4 * u - height);
  m.offset = std::clamp(data.library_scroll / 100.0f, 0.0f, 1.0f) * m.max_scroll;
  m.first_row = int(m.offset / m.pitch);
  m.end_row = std::min(int(data.lib_names.size()), int(std::ceil((m.offset + height) / m.pitch)));
  m.scrollbar = {GEN_XL(panel, GEN_DIVIDER_X - 18, u),
                 GEN_XL(panel, GEN_DIVIDER_X - 10, u),
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
    const bContext *C, ui::Block *block, const rctf &panel, const float u, const GenPaneData &data)
{
  if (data.source != GEN_SOURCE_LIBRARY) {
    return;
  }
  const auto m = agent_ui_generations_library_metrics(panel, u, data);
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
      r.ymin = r.ymax - m.pitch + 4 * u;
      if (active) {
        pane_fill_round(&r, GEN_META_RADIUS * u, bg);
      }
      char label[64];
      BLI_strncpy(label, name.c_str(), sizeof(label));
      pane_fit_text(label, BLI_rctf_size_x(&r) - 24 * u, GEN_LIB_FONT * agent_ui_text_unit());
      pane_label_left(label,
                      r.xmin + 12 * u,
                      BLI_rctf_cent_y(&r),
                      GEN_LIB_FONT * agent_ui_text_unit(),
                      active ? text : dim);
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
  pane_fill_round(&r, GEN_META_RADIUS * u, bg);
  pane_label_left("+  Add Library…",
                  r.xmin + 12 * u,
                  BLI_rctf_cent_y(&r),
                  GEN_LIB_FONT * agent_ui_text_unit(),
                  text);
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
