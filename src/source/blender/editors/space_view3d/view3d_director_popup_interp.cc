/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Native block popup listing every keyframe interpolation type for the
 * Cinema Mode top strip. Presentation only: the rows are read from the
 * shot's own `interpolation` enum, so the list is exactly what the Python
 * property accepts, and each row invokes the Python-owned
 * `mixar.director_set_interpolation`.
 */

#include "MEM_guardedalloc.h"

#include "BKE_context.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_overlay_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

ui::Block *interpolation_popup_create(bContext *C, ARegion *region, void * /*arg*/)
{
  ui::Block *block = director_popup_block_begin(C, region, __func__);
  DirectorPopupData data;
  if (!director_popup_data_get(C, &data) || data.shot_ptr.data == nullptr) {
    director_popup_section_label(block, "No active shot", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }
  PropertyRNA *prop = RNA_struct_find_property(&data.shot_ptr, "interpolation");
  if (prop == nullptr) {
    director_popup_section_label(block, "Interpolation unavailable", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }

  const int width = UI_UNIT_X * 11;
  const int row_h = int(UI_UNIT_Y * 1.1f);
  const int current = RNA_property_enum_get(&data.shot_ptr, prop);

  const EnumPropertyItem *items = nullptr;
  int items_count = 0;
  bool free_items = false;
  RNA_property_enum_items(C, &data.shot_ptr, prop, &items, &items_count, &free_items);

  int y = 0;
  for (int index = 0; index < items_count; index++) {
    if (items[index].identifier == nullptr || items[index].identifier[0] == '\0') {
      continue;
    }
    y -= row_h;
    ui::Button *but = director_overlay_operator_button(block,
                                                       "MIXAR_OT_director_set_interpolation",
                                                       ICON_NONE,
                                                       items[index].name,
                                                       0,
                                                       y,
                                                       width,
                                                       row_h,
                                                       "Ease the camera this way between keyframes");
    RNA_enum_set_identifier(
        C, ui::button_operator_ptr_ensure(but), "interpolation", items[index].identifier);
    director_popup_state(but, items[index].value == current, data.editable);
  }
  if (free_items && items) {
    MEM_delete_void(static_cast<void *>(const_cast<EnumPropertyItem *>(items)));
  }
  director_popup_block_end(block);
  return block;
}

}  // namespace

ui::Block *view3d_director_interpolation_popup_create(bContext *C, ARegion *region, void *arg)
{
  return interpolation_popup_create(C, region, arg);
}

}  // namespace blender
