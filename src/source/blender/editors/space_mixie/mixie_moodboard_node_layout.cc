/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "mixie_moodboard_node_layout.hh"
#include "ED_moodboard_drawer.hh"
#include "ED_screen.hh"

namespace blender::ed::mixie {

rcti moodboard_visible_canvas_rect(const bContext *C)
{
  ARegion *region = CTX_wm_region(C);
  const ScrArea *area = CTX_wm_area(C);
  rcti canvas = {0, region->winx, 0, region->winy};
  if (area->spacetype == SPACE_MIXIE && region->regiontype == RGN_TYPE_WINDOW) {
    /* The standalone editor can have overlapping tool/sidebar regions. */
    canvas = *ED_region_visible_rect(region);
  }
  if (area->spacetype == SPACE_VIEW3D && region->regiontype == RGN_TYPE_TOOL_PROPS) {
    rcti panel;
    if (view3d_moodboard_drawer_panel_rect_for(
            area, region, view3d_moodboard_drawer_runtime_amount(region), &panel))
    {
      canvas = panel;
      BLI_rcti_translate(&canvas, -region->winrct.xmin, -region->winrct.ymin);
    }
  }
  const int margin = int(8 * UI_SCALE_FAC);
  BLI_rcti_pad(&canvas, -margin, -margin);
  return canvas;
}

bool moodboard_node_controls_rect(const bContext *C, View2D *v2d, PointerRNA *node, rcti *r_rect)
{
  if (!RNA_boolean_get(node, "selected")) {
    return false;
  }
  PointerRNA scene = RNA_id_pointer_create(&CTX_data_scene(C)->id);
  char active[MIXIE_GRAPH_ID_BUF], id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(&scene, "mixie_moodboard_active_node_id", active, sizeof(active));
  mixie_rna_string_get_clamped(node, "node_id", id, sizeof(id));
  /* Shift-select keeps a single active owner; box-select has no inspector. */
  if (active[0] == '\0' || !STREQ(active, id)) {
    return false;
  }
  rctf card;
  card.xmin = RNA_float_get(node, "position_x");
  card.ymin = RNA_float_get(node, "position_y");
  card.xmax = card.xmin + RNA_float_get(node, "width");
  card.ymax = card.ymin + RNA_float_get(node, "height");
  const rcti canvas = moodboard_visible_canvas_rect(C);
  return moodboard_view_rect_to_region(v2d, CTX_wm_region(C), card, r_rect) &&
         BLI_rcti_isect(r_rect, &canvas, r_rect) &&
         BLI_rcti_size_x(r_rect) >=
             std::max(MOODBOARD_GRAPH_CONTROLS_MIN_PX_X, int(180 * UI_SCALE_FAC)) &&
         BLI_rcti_size_y(r_rect) >=
             std::max(MOODBOARD_GRAPH_CONTROLS_MIN_PX_Y, int(150 * UI_SCALE_FAC));
}

bool moodboard_node_settings_rect(const bContext *C,
                                  PointerRNA *node,
                                  const rcti &card,
                                  rcti *r_rect)
{
  int controls = 1 + int(RNA_boolean_get(node, "show_mode"));
  PropertyRNA *parameters = RNA_struct_find_property(node, "parameters");
  if (parameters) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(node, parameters, &iter);
    while (iter.valid) {
      controls += int(RNA_boolean_get(&iter.ptr, "visible"));
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }
  const int state = RNA_enum_get(node, "state");
  const bool has_result = RNA_pointer_get(node, "preview_image").data ||
                          RNA_pointer_get(node, "preview_object").data;
  const bool rerun = has_result && ELEM(state, 3, 4, 5);
  const float scale = UI_SCALE_FAC;
  const int width = int(244 * scale);
  const int inset = int(14 * scale), row = int(32 * scale);
  const int caption = int(18 * scale), gap = int(6 * scale);
  const int height = 2 * inset + controls * (row + caption) + (controls - 1) * gap +
                     int(12 * scale) + row + (rerun ? row + gap : 0);
  const rcti canvas = moodboard_visible_canvas_rect(C);
  if (height > BLI_rcti_size_y(&canvas)) {
    return false;
  }
  /* Reserve room for input labels and output handles, not just the card rim. */
  const int separation = int(28 * scale);
  int left_separation = separation;
  View2D *v2d = &CTX_wm_region(C)->v2d;
  const float zoom = ui::view2d_scale_get_x(v2d);
  PropertyRNA *sockets = RNA_struct_find_property(node, "input_sockets");
  if (sockets && BLI_rcti_size_x(&card) >= 80 * scale) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(node, sockets, &iter);
    while (iter.valid) {
      if (RNA_boolean_get(&iter.ptr, "visible")) {
        char label[MIXIE_GRAPH_LABEL_BUF];
        mixie_rna_string_get_clamped(&iter.ptr, "label", label, sizeof(label));
        const float extent = (MOODBOARD_GRAPH_SOCKET_OFFSET +
                              moodboard_socket_label_width(v2d, label)) * zoom +
                             moodboard_socket_radius_px(v2d) + 18 * scale;
        left_separation = std::max(left_separation, int(std::ceil(extent)));
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }
  int x = card.xmin - left_separation - width;
  if (x < canvas.xmin) {
    x = card.xmax + separation;
  }
  if (x < canvas.xmin || x + width > canvas.xmax) {
    return false;
  }
  const int y = std::clamp(card.ymax - height, canvas.ymin, canvas.ymax - height);
  *r_rect = {x, x + width, y, y + height};
  return true;
}

}  // namespace blender::ed::mixie
