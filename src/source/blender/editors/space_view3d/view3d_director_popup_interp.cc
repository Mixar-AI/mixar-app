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

#include <algorithm>
#include <string>

#include "MEM_guardedalloc.h"

#include "BLI_string.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_overlay_intern.hh"
#include "view3d_director_timeline.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

ui::Block *interpolation_popup_create(bContext *C, ARegion *region, void *arg)
{
  ui::Block *block = director_popup_block_begin(C, region, __func__);
  DirectorPopupData data;
  if (!director_popup_data_get(C, &data) || data.shot_ptr.data == nullptr) {
    director_popup_section_label(block, "No active shot", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }
  /* The SELECTED keyframes' own property when there is a selection, the
   * shot's default when there is not. A keyframe's interpolation governs the
   * segment from it to the next one, so writing the selection is exactly
   * "ease these spans differently"; the beat enum carries one extra row,
   * Shot Default, which hands a keyframe back to the take. */
  blender::Vector<int> selected;
  const bool has_selection = view3d_director_timeline_selection(C, &selected);
  PointerRNA list_ptr = data.shot_ptr;
  std::string indices;
  if (has_selection) {
    PropertyRNA *beats = RNA_struct_find_property(&data.shot_ptr, "beats");
    const int count = beats ? RNA_property_collection_length(&data.shot_ptr, beats) : 0;
    PointerRNA first_ptr;
    bool have_first = false;
    for (const int index : selected) {
      if (index < 0 || index >= count) {
        continue;
      }
      if (!indices.empty()) {
        indices += ',';
      }
      indices += std::to_string(index);
      if (!have_first &&
          RNA_property_collection_lookup_int(&data.shot_ptr, beats, index, &first_ptr))
      {
        list_ptr = first_ptr;
        have_first = true;
      }
    }
  }

  PropertyRNA *prop = RNA_struct_find_property(&list_ptr, "interpolation");
  if (prop == nullptr) {
    director_popup_section_label(block, "Interpolation unavailable", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }

  const int width = director_popup_width(arg, UI_UNIT_X * 11);
  const int row_h = int(UI_UNIT_Y * 1.1f);
  const int label_h = int(UI_UNIT_Y * 0.85f);
  const int current = RNA_property_enum_get(&list_ptr, prop);

  const EnumPropertyItem *items = nullptr;
  int items_count = 0;
  bool free_items = false;
  RNA_property_enum_items(C, &list_ptr, prop, &items, &items_count, &free_items);

  int y = 0;
  if (!indices.empty()) {
    char caption[64];
    const int count = int(std::count(indices.begin(), indices.end(), ',')) + 1;
    BLI_snprintf(caption, sizeof(caption), "%d keyframe%s", count, count == 1 ? "" : "s");
    y -= label_h;
    director_popup_section_label(block, caption, y, width);
  }
  for (int index = 0; index < items_count; index++) {
    if (items[index].identifier == nullptr || items[index].identifier[0] == '\0') {
      continue;
    }
    y -= row_h;
    ui::Button *but = director_overlay_operator_button(
        block,
        "MIXAR_OT_director_set_interpolation",
        ICON_NONE,
        items[index].name,
        0,
        y,
        width,
        row_h,
        indices.empty() ? "Ease the camera this way between this shot's keyframes" :
                          "Ease the camera this way out of the selected keyframes");
    PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
    RNA_enum_set_identifier(C, op_ptr, "interpolation", items[index].identifier);
    RNA_string_set(op_ptr, "indices", indices.c_str());
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
