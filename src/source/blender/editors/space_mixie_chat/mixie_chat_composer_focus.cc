/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Restore native editing after an asynchronous composer insertion. */

#include "BKE_context.hh"
#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "DNA_scene_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "RNA_access.hh"
#include "UI_interface_c.hh"
#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"

namespace blender {

static wmOperatorStatus focus_composer_exec(bContext *C, wmOperator * /*op*/)
{
  ScrArea *area = CTX_wm_area(C);
  Scene *scene = CTX_data_scene(C);
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!area || !scene || !wm ||
      (area->spacetype != SPACE_AGENT_BUBBLE))
  {
    return OPERATOR_CANCELLED;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *ink = RNA_struct_find_property(&wm_ptr, "mixie_chat_ink_visible");
  if (ink && RNA_property_boolean_get(&wm_ptr, ink)) {
    return OPERATOR_CANCELLED;
  }
  int composer_region = RGN_TYPE_TOOLS;
  if (area->spacetype == SPACE_AGENT_BUBBLE) {
    PropertyRNA *tab = RNA_struct_find_property(&wm_ptr, "mixar_bubble_tab");
    int agent_tab = 0;
    if (tab && (!RNA_property_enum_value(C, &wm_ptr, tab, "AGENT", &agent_tab) ||
                RNA_property_enum_get(&wm_ptr, tab) != agent_tab))
    {
      return OPERATOR_CANCELLED;
    }
    PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
    PropertyRNA *messages = RNA_struct_find_property(&scene_ptr, "mixie_chat_messages");
    const bool has_messages = messages && RNA_property_collection_length(&scene_ptr, messages) > 0;
    composer_region = has_messages ? RGN_TYPE_TOOLS : RGN_TYPE_WINDOW;
  }
  for (ARegion &region : area->regionbase) {
    if (region.regiontype == composer_region && !(region.flag & RGN_FLAG_HIDDEN) &&
        ui::textbutton_activate_rna(C, &region, scene, "mixie_chat_input", true))
    {
      return OPERATOR_FINISHED;
    }
  }
  return OPERATOR_CANCELLED;
}

void MIXIE_CHAT_OT_focus_composer(wmOperatorType *ot)
{
  ot->name = "Focus Chat Composer";
  ot->idname = "MIXIE_CHAT_OT_focus_composer";
  ot->description = "Resume editing the visible chat draft after voice transcription";
  ot->exec = focus_composer_exec;
  ot->flag = OPTYPE_INTERNAL;
}

}  // namespace blender
