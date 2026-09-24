/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Native button drags; both canvas hosts share the same dropbox and creator. */

#include "mixie_moodboard_template_drag.hh"
#include "mixie_moodboard_canvas.hh"
#include "mixie_moodboard_ops_common.hh"
#include "../interface/interface_intern.hh"

#include "BLI_string.h"
#include "RNA_define.hh"

namespace blender::ed::mixie {

/* A readable, scoped payload, with labels resolved from the Python enum. */
static constexpr char template_prefix[] = "Node Template: ";
static constexpr char create_operator[] = "MIXIE_OT_moodboard_add_template";

void moodboard_template_drag_buttons(const bContext *C, ui::Block *block)
{
  for (ui::Button &button : block->buttons()) {
    if (!button.optype || !STREQ(button.optype->idname, create_operator) || !button.opptr) {
      continue;
    }
    PropertyRNA *prop = RNA_struct_find_property(button.opptr, "template");
    const char *label = nullptr;
    if (prop && RNA_property_enum_name(
                    const_cast<bContext *>(C), button.opptr, prop,
                    RNA_property_enum_get(button.opptr, prop), &label))
    {
      const std::string payload = std::string(template_prefix) + label;
      ui::button_drag_set_name(&button, BLI_strdup(payload.c_str()));
      /* Ownership transfers from the button to wmDrag on the first drag. */
      button.dragflag |= ui::BUT_DRAGPOIN_FREE | ui::BUT_DRAG_FULL_BUT;
    }
  }
}

static bool template_drop_poll(bContext *C, wmDrag *drag, const wmEvent *event)
{
  if (!moodboard_poll(C) || drag->type != WM_DRAG_NAME || !drag->poin ||
      !STRPREFIX(static_cast<const char *>(drag->poin), template_prefix))
  {
    return false;
  }
  ARegion *region = CTX_wm_region(C);
  if (!region || !ELEM(region->regiontype, RGN_TYPE_WINDOW, RGN_TYPE_TOOL_PROPS)) {
    return false;
  }
  /* Drop polling also runs on MOUSEMOVE: unlike event routing, it must test
   * the current destination even while crossing out of the canvas. */
  return WM_event_handler_region_v2d_mask_poll(
             CTX_wm_window(C), CTX_wm_area(C), region, event) &&
         moodboard_canvas_point_is_interactive(CTX_wm_area(C), region, event->xy);
}

static void template_drop_copy(bContext * /*C*/, wmDrag *drag, wmDropBox *drop)
{
  RNA_string_set(drop->ptr, "template_label",
                 static_cast<const char *>(drag->poin) + strlen(template_prefix));
}

static wmOperatorStatus template_drop_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  if (!WM_operatortype_find(create_operator, true)) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA properties = WM_operator_properties_create(create_operator);
  PropertyRNA *prop = RNA_struct_find_property(&properties, "template");
  char label[256];
  RNA_string_get(op->ptr, "template_label", label);
  const EnumPropertyItem *items = nullptr;
  bool free_items = false;
  RNA_property_enum_items(C, &properties, prop, &items, nullptr, &free_items);
  bool found = false;
  for (const EnumPropertyItem *item = items; item && item->identifier; item++) {
    if (item->name && STREQ(item->name, label)) {
      RNA_property_enum_set(&properties, prop, item->value);
      found = true;
      break;
    }
  }
  if (free_items) {
    MEM_delete_void(const_cast<void *>(static_cast<const void *>(items)));
  }
  wmOperatorStatus result = OPERATOR_CANCELLED;
  if (found) {
    ARegion *region = CTX_wm_region(C);
    float x, y;
    ui::view2d_region_to_view(&region->v2d,
                              event->xy[0] - region->winrct.xmin,
                              event->xy[1] - region->winrct.ymin, &x, &y);
    RNA_boolean_set(&properties, "from_drop", true);
    RNA_float_set(&properties, "drop_x", x);
    RNA_float_set(&properties, "drop_y", y);
    result = WM_operator_name_call(C, create_operator, wm::OpCallContext::ExecDefault,
                                   &properties, nullptr);
  }
  WM_operator_properties_free(&properties);
  return result;
}

void moodboard_template_dropboxes()
{
  ListBaseT<wmDropBox> *boxes = WM_dropboxmap_find("Mixie", SPACE_MIXIE, RGN_TYPE_WINDOW);
  WM_dropbox_add(boxes, "MIXIE_OT_moodboard_drop_template",
                  template_drop_poll, template_drop_copy, nullptr, nullptr);
}

}  // namespace blender::ed::mixie

namespace blender {
void MIXIE_OT_moodboard_drop_template(wmOperatorType *ot)
{
  ot->name = "Place Node Template";
  ot->idname = "MIXIE_OT_moodboard_drop_template";
  ot->description = "Place an editable node where the template is dropped";
  ot->poll = ed::mixie::moodboard_poll;
  ot->invoke = ed::mixie::template_drop_invoke;
  ot->flag = OPTYPE_UNDO;
  PropertyRNA *prop = RNA_def_string(
      ot->srna, "template_label", nullptr, 256, "Template", "Template to place");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}
}  // namespace blender
