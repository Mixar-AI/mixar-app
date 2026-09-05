/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The one definition of what a moodboard drag carries.
 *
 * A board holds four movable kinds -- images, text boxes, inference nodes and
 * 3D asset nodes -- but TWO operators drag them: MIXIE_OT_moodboard_select_image
 * for media and MIXIE_OT_moodboard_graph_select for cards. Each moved only its
 * own kinds, so a selection spanning both came apart under the mouse: grabbing
 * a picture left the selected node behind, and grabbing the card left the
 * picture. Both capture through here now, so a kind can never be draggable in
 * one gesture and stationary in the other.
 *
 * This mirrors the Python grab's `_GRAB_COLLECTIONS` table
 * (`ui/operators/transform_modal_ops.py`), which is the same list for the G
 * key -- and which is why G already moved a mixed selection correctly while
 * dragging did not.
 */

#include "mixie_moodboard_ops_common.hh"

namespace blender::ed::mixie {

/* Every collection a drag can move. All four carry `position_x`/`position_y`
 * and `selected`, which is the whole reason one capture can serve them. */
static const char *drag_collection_names[] = {
    "mixie_moodboard_images",
    "mixie_moodboard_textboxes",
    "mixie_moodboard_action_nodes",
    "mixie_moodboard_asset_nodes",
};

static bool drag_kind_wanted(const MoodboardDragKinds kinds, const char *collection)
{
  if (STREQ(collection, "mixie_moodboard_images")) {
    return (kinds & MOODBOARD_DRAG_IMAGES) != 0;
  }
  if (STREQ(collection, "mixie_moodboard_textboxes")) {
    return (kinds & MOODBOARD_DRAG_TEXTBOXES) != 0;
  }
  return (kinds & MOODBOARD_DRAG_NODES) != 0;
}

/* An image inherits its group's selection: the group handle is what the user
 * grabbed, and its members have to travel with it. Only images are grouped. */
static bool image_group_is_selected(PointerRNA *scene_ptr, PointerRNA *item)
{
  PropertyRNA *groups = RNA_struct_find_property(scene_ptr, "mixie_moodboard_groups");
  PropertyRNA *group_idx = RNA_struct_find_property(item, "group_index");
  if (!groups || !group_idx) {
    return false;
  }
  const int index = RNA_property_int_get(item, group_idx);
  if (index < 0) {
    return false;
  }
  PointerRNA group;
  if (!RNA_property_collection_lookup_int(scene_ptr, groups, index, &group)) {
    return false;
  }
  PropertyRNA *selected = RNA_struct_find_property(&group, "selected");
  return selected && RNA_property_boolean_get(&group, selected);
}

void moodboard_drag_set_capture(PointerRNA *scene_ptr,
                                const MoodboardDragKinds kinds,
                                MoodboardDragSet *drag)
{
  drag->items.clear();
  for (const char *collection_name : drag_collection_names) {
    if (!drag_kind_wanted(kinds, collection_name)) {
      continue;
    }
    PropertyRNA *collection = RNA_struct_find_property(scene_ptr, collection_name);
    if (!collection) {
      continue;
    }
    const int count = RNA_property_collection_length(scene_ptr, collection);
    for (int i = 0; i < count; i++) {
      PointerRNA item;
      if (!RNA_property_collection_lookup_int(scene_ptr, collection, i, &item)) {
        continue;
      }
      PropertyRNA *selected = RNA_struct_find_property(&item, "selected");
      const bool is_selected = selected && RNA_property_boolean_get(&item, selected);
      if (!is_selected && !image_group_is_selected(scene_ptr, &item)) {
        continue;
      }
      PropertyRNA *pos_x = RNA_struct_find_property(&item, "position_x");
      PropertyRNA *pos_y = RNA_struct_find_property(&item, "position_y");
      if (!pos_x || !pos_y) {
        continue;
      }
      MoodboardDragItem entry{};
      entry.collection = collection_name;
      entry.index = i;
      entry.initial_x = RNA_property_float_get(&item, pos_x);
      entry.initial_y = RNA_property_float_get(&item, pos_y);
      drag->items.append(entry);
    }
  }
}

/* Positions are always re-derived from the captured START plus the running
 * delta, never accumulated frame to frame: a dropped MOUSEMOVE would otherwise
 * leave the set permanently out of step with the cursor. */
static void drag_set_write(PointerRNA *scene_ptr,
                           const MoodboardDragSet &drag,
                           const float delta_x,
                           const float delta_y)
{
  for (const MoodboardDragItem &entry : drag.items) {
    PropertyRNA *collection = RNA_struct_find_property(scene_ptr, entry.collection);
    PointerRNA item;
    if (!collection ||
        !RNA_property_collection_lookup_int(scene_ptr, collection, entry.index, &item))
    {
      continue;
    }
    PropertyRNA *pos_x = RNA_struct_find_property(&item, "position_x");
    PropertyRNA *pos_y = RNA_struct_find_property(&item, "position_y");
    if (!pos_x || !pos_y) {
      continue;
    }
    RNA_property_float_set(&item, pos_x, entry.initial_x + delta_x);
    RNA_property_float_set(&item, pos_y, entry.initial_y + delta_y);
  }
}

void moodboard_drag_set_apply(PointerRNA *scene_ptr,
                              const MoodboardDragSet &drag,
                              const float delta_x,
                              const float delta_y)
{
  drag_set_write(scene_ptr, drag, delta_x, delta_y);
}

void moodboard_drag_set_restore(PointerRNA *scene_ptr, const MoodboardDragSet &drag)
{
  drag_set_write(scene_ptr, drag, 0.0f, 0.0f);
}

}  // namespace blender::ed::mixie
