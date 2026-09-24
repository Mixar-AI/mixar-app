/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "../interface/interface_intern.hh"
#include "../interface/interface_qa_inspect.hh"
#include "BKE_global.hh"
#include "BKE_main.hh"
#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "RNA_access.hh"
#include "agent_ui_generations.hh"

namespace blender {
namespace {
void targets(const wmWindow * /*win*/,
             const ScrArea * /*area*/,
             const ARegion *region,
             std::vector<MixarQATarget> &result)
{
  if (region->regiontype != RGN_TYPE_WINDOW || !region->runtime || !G_MAIN ||
      G_MAIN->wm.is_empty()) {
    return;
  }
  PointerRNA wm = RNA_id_pointer_create(&static_cast<wmWindowManager *>(G_MAIN->wm.first)->id);
  for (const ui::Block &block : region->runtime->uiblocks) {
    if (block.name != "agent_island_generations") {
      continue;
    }
    for (const auto &button : block.buttons_ptrs) {
      if (!button->opptr || !RNA_struct_find_property(button->opptr, "data_path")) {
        continue;
      }
      const std::string path = RNA_string_get(button->opptr, "data_path");
      const bool tile = path == "window_manager.mixar_generations_selected";
      const bool library = path == "window_manager.mixar_generations_library";
      const bool filter = path == "window_manager.mixar_generations_filter";
      const bool source = path == "window_manager.mixar_generations_source";
      if (!tile && !library && !filter && !source) {
        continue;
      }
      MixarQATarget target;
      target.surface = tile ? "library_tile" :
                       library ? "library_source" :
                       filter ? "library_filter" : "library_source_kind";
      target.value = RNA_string_get(button->opptr, "value");
      if (library && target.value.empty()) {
        target.value = RNA_string_get(&wm, "mixar_generations_library");
      }
      target.text = target.value;
      const char *property = tile ? "mixar_generations_selected" :
                             library ? "mixar_generations_library" :
                             filter ? "mixar_generations_filter" : "mixar_generations_source";
      if (tile || library) {
        target.sel = target.value == RNA_string_get(&wm, property);
      }
      else {
        const char *identifier = nullptr;
        RNA_property_enum_identifier(nullptr,
                                     &wm,
                                     RNA_struct_find_property(&wm, property),
                                     RNA_enum_get(&wm, property),
                                     &identifier);
        target.sel = identifier && target.value == identifier;
      }
      ui::button_to_pixelrect(&target.rect_win, region, &block, button.get());
      BLI_rcti_translate(&target.rect_win, region->winrct.xmin, region->winrct.ymin);
      if (BLI_rcti_isect(&target.rect_win, &region->winrct, &target.rect_win)) {
        result.push_back(std::move(target));
      }
    }
  }
}
}  // namespace
void agent_ui_generations_qa_register()
{
  Mixar_qa_register_target_provider(SPACE_AGENT_BUBBLE, targets);
}
}  // namespace blender
