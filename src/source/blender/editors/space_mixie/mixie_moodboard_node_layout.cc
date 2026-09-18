/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "BLI_string.h"

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
  rcti card_region;
  if (!moodboard_view_rect_to_region(v2d, CTX_wm_region(C), card, &card_region)) {
    return false;
  }
  /* The CARD's own on-screen size decides whether the controls fit, not the
   * slice of it a sidebar or the Zen drawer happens to leave uncovered. The
   * minimum used to be measured after clipping, so pushing a card a little
   * under the sidebar took its visible width below the threshold and removed
   * the prompt, Generate AND Settings in one step, leaving a selected node
   * that still reads "Click this block to type a prompt" and has nothing to
   * click. */
  if (BLI_rcti_size_x(&card_region) <
          std::max(MOODBOARD_GRAPH_CONTROLS_MIN_PX_X, int(180 * UI_SCALE_FAC)) ||
      BLI_rcti_size_y(&card_region) <
          std::max(MOODBOARD_GRAPH_CONTROLS_MIN_PX_Y, int(150 * UI_SCALE_FAC)))
  {
    return false;
  }
  const rcti canvas = moodboard_visible_canvas_rect(C);
  if (!BLI_rcti_isect(&card_region, &canvas, r_rect)) {
    return false;
  }
  /* A sliver has nowhere to put them, so that one does drop out. */
  return BLI_rcti_size_x(r_rect) >= int(160 * UI_SCALE_FAC) &&
         BLI_rcti_size_y(r_rect) >= int(120 * UI_SCALE_FAC);
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
  if (width > BLI_rcti_size_x(&canvas)) {
    return false;
  }
  /* A side is usable when the panel can sit inside the canvas without
   * covering the card. Clamping rather than rejecting is the point: the
   * panel used to be dropped outright the moment its preferred x fell
   * outside the canvas, so one node dragged across the board cycled
   * docked -> in-card Settings row -> docked -> nothing, re-deciding every
   * frame while the pointer was still down. */
  auto usable = [&](const int preferred, const int overlap_allowed, int *r_x) {
    const int x = std::clamp(preferred, canvas.xmin, canvas.xmax - width);
    const int overlap = std::min(x + width, int(card.xmax)) - std::max(x, int(card.xmin));
    if (overlap > overlap_allowed) {
      return false;
    }
    *r_x = x;
    return true;
  };
  const int left_preferred = card.xmin - left_separation - width;
  const int right_preferred = card.xmax + separation;
  int left_x = 0, right_x = 0;
  const bool fits_left = usable(left_preferred, 0, &left_x);
  const bool fits_right = usable(right_preferred, 0, &right_x);

  /* Only ONE node owns an inspector at a time, so one latch is the whole
   * state. It keeps the side already on screen for as long as that side
   * still works, so a drag cannot make the panel jump across the card. A
   * stale entry is harmless: a different node, or a side that stopped
   * fitting, falls straight through to a fresh choice. */
  static char latched_node[MIXIE_GRAPH_ID_BUF] = "";
  static int latched_side = 0; /* 0 unset, 1 left, 2 right. */
  char node_id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(node, "node_id", node_id, sizeof(node_id));
  if (!STREQ(latched_node, node_id)) {
    BLI_strncpy(latched_node, node_id, sizeof(latched_node));
    latched_side = 0;
  }

  /* The side already on screen gets first refusal, and is allowed to clip a
   * quarter of the card before giving way. Without that the panel hops across
   * the card the moment the other side becomes the roomier one, which is the
   * jump seen while dragging: a card near the middle of a narrow canvas
   * leaves neither side its full separation. A side chosen fresh (a different
   * node, or one whose latched side stopped working) still refuses to cover
   * the card at all. */
  const int tolerance = BLI_rcti_size_x(&card) / 4;
  int side = 0;
  if (latched_side == 1 && (fits_left || usable(left_preferred, tolerance, &left_x))) {
    side = 1;
  }
  else if (latched_side == 2 && (fits_right || usable(right_preferred, tolerance, &right_x))) {
    side = 2;
  }
  else if (fits_left) {
    side = 1;
  }
  else if (fits_right) {
    side = 2;
  }
  if (side == 0) {
    latched_side = 0;
    return false;
  }
  latched_side = side;
  const int x = (side == 1) ? left_x : right_x;
  const int y = std::clamp(card.ymax - height, canvas.ymin, canvas.ymax - height);
  *r_rect = {x, x + width, y, y + height};
  return true;
}

}  // namespace blender::ed::mixie
