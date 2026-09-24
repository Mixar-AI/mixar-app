/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * QA targets for the asset picker, so the harness can select a tile and
 * answer the agent by the same buttons a user presses:
 *  - `asset_pick_tile`: value = the pick's action value, `sel` = the tile
 *    the detail column is describing;
 *  - `asset_pick_action`: value = the answer it sends ("Use This Asset" sends
 *    the selected pick, then "Model from Scratch" and Cancel).
 */

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

#include "ED_mixie_chat_asset_picker.hh"

#include "agent_ui_asset_picker.hh"

namespace blender {
namespace {
void targets(const wmWindow * /*win*/,
             const ScrArea * /*area*/,
             const ARegion *region,
             std::vector<MixarQATarget> &result)
{
  if (region->regiontype != RGN_TYPE_WINDOW || !region->runtime || !G_MAIN ||
      G_MAIN->wm.is_empty())
  {
    return;
  }
  PointerRNA wm = RNA_id_pointer_create(&static_cast<wmWindowManager *>(G_MAIN->wm.first)->id);
  const std::string selected = RNA_struct_find_property(&wm, MIXIE_ASSET_PICKER_SELECTED_PROP) ?
                                   RNA_string_get(&wm, MIXIE_ASSET_PICKER_SELECTED_PROP) :
                                   std::string();
  for (const ui::Block &block : region->runtime->uiblocks) {
    if (block.name != AGENT_ASSET_PICKER_BLOCK) {
      continue;
    }
    bool first_tile = true;
    for (const auto &button : block.buttons_ptrs) {
      if (!button->opptr) {
        continue;
      }
      MixarQATarget target;
      if (RNA_struct_find_property(button->opptr, "data_path")) {
        target.surface = "asset_pick_tile";
        target.value = RNA_string_get(button->opptr, "value");
        /* Empty or stale selection means the first (best) pick. */
        target.sel = selected.empty() ? first_tile : target.value == selected;
        first_tile = false;
      }
      else if (RNA_struct_find_property(button->opptr, "action_value")) {
        target.surface = "asset_pick_action";
        target.value = RNA_string_get(button->opptr, "action_value");
      }
      else {
        continue;
      }
      target.text = target.value;
      ui::button_to_pixelrect(&target.rect_win, region, &block, button.get());
      BLI_rcti_translate(&target.rect_win, region->winrct.xmin, region->winrct.ymin);
      if (BLI_rcti_isect(&target.rect_win, &region->winrct, &target.rect_win)) {
        result.push_back(std::move(target));
      }
    }
  }
}
}  // namespace
void agent_ui_asset_picker_qa_register()
{
  Mixar_qa_register_target_provider(SPACE_AGENT_BUBBLE, targets);
}
}  // namespace blender
