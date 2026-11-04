/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Dropping an asset-picker tile into a 3D viewport.
 *
 * A picker tile (`space_agent_bubble/agent_ui_asset_picker.cc`) carries a
 * name drag (#WM_DRAG_NAME) whose payload is #MIXIE_ASSET_PICK_DRAG_PREFIX
 * followed by the pick's action VALUE — the same pattern as the moodboard's
 * template drag. The View3D hosts the "Mixie" dropbox map (registered ahead
 * of Blender's own, `space_view3d.cc`), so this dropbox sees the drop first:
 * it forwards the pick and the drop point to the Python operator
 * `MIXIE_CHAT_OT_place_asset_pick`, which appends the asset where it landed
 * and answers the agent's question with it — exactly what a Library tile
 * does, plus the answer.
 *
 * The drop operator is C++ because #WM_dropbox_add validates the operator
 * name at registration (startup), before Python operators exist; the Python
 * half is resolved at drop time (`mixie_chat_dragdrop.cc` has the same
 * shape for reference images).
 */

#include <cstring>

#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "DNA_screen_types.h"
#include "DNA_space_enums.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "BKE_context.hh"
#include "BKE_report.hh"

#include "ED_screen.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "ED_mixie_chat_asset_picker.hh"

#include "mixie_chat_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

static constexpr char place_operator[] = "MIXIE_CHAT_OT_place_asset_pick";

static bool asset_pick_drop_poll(bContext *C, wmDrag *drag, const wmEvent * /*event*/)
{
  if (drag->type != WM_DRAG_NAME || !drag->poin ||
      !STRPREFIX(static_cast<const char *>(drag->poin), MIXIE_ASSET_PICK_DRAG_PREFIX))
  {
    return false;
  }
  return ED_operator_region_view3d_active(C);
}

static void asset_pick_drop_copy(bContext * /*C*/, wmDrag *drag, wmDropBox *drop)
{
  RNA_string_set(drop->ptr,
                 "value",
                 static_cast<const char *>(drag->poin) + strlen(MIXIE_ASSET_PICK_DRAG_PREFIX));
}

static wmOperatorStatus asset_pick_drop_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  /* The island can show a picker before deferred Python UI registration
   * finishes; never write into the fallback OperatorProperties. */
  if (!WM_operatortype_find(place_operator, true)) {
    BKE_report(op->reports, RPT_WARNING, "Chat is still loading. Please drop the asset again.");
    return OPERATOR_CANCELLED;
  }
  const ARegion *region = CTX_wm_region(C);
  if (!region) {
    return OPERATOR_CANCELLED;
  }
  char value[256];
  RNA_string_get(op->ptr, "value", value);

  PointerRNA props = WM_operator_properties_create(place_operator);
  RNA_string_set(&props, "value", value);
  /* Region-relative, what `bpy_extras.view3d_utils` projects from. */
  RNA_int_set(&props, "mouse_x", event->xy[0] - region->winrct.xmin);
  RNA_int_set(&props, "mouse_y", event->xy[1] - region->winrct.ymin);
  const auto result = WM_operator_name_call(
      C, place_operator, wm::OpCallContext::ExecDefault, &props, nullptr);
  WM_operator_properties_free(&props);
  return wmOperatorStatus(result);
}

void MIXIE_CHAT_OT_drop_asset_pick(wmOperatorType *ot)
{
  ot->name = "Place Library Pick";
  ot->idname = "MIXIE_CHAT_OT_drop_asset_pick";
  ot->description = "Place the dragged library asset where it is dropped and answer the agent with it";

  ot->invoke = asset_pick_drop_invoke;
  ot->poll = ED_operator_region_view3d_active;

  ot->flag = OPTYPE_UNDO;

  PropertyRNA *prop = RNA_def_string(
      ot->srna, "value", nullptr, 256, "Pick", "Action value of the dropped pick");
  RNA_def_property_flag(prop, PROP_HIDDEN | PROP_SKIP_SAVE);
}

void mixie_chat_asset_pick_dropboxes()
{
  /* The map every View3D main region carries (space_view3d.cc), shared with
   * the moodboard's own View3D drops; found-or-created, so registration
   * order between the spacetypes does not matter. */
  ListBaseT<wmDropBox> *lb = WM_dropboxmap_find("Mixie", SPACE_MIXIE, RGN_TYPE_WINDOW);
  WM_dropbox_add(lb,
                 "MIXIE_CHAT_OT_drop_asset_pick",
                 asset_pick_drop_poll,
                 asset_pick_drop_copy,
                 nullptr,
                 nullptr);
}

}  // namespace blender
