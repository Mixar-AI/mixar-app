/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The row floating above a selected frame: Rename and More.
 *
 * Same geometry and the same two header constants as a node card's Edit /
 * Preview / Export row, so the same glyph in the same place relative to the
 * thing it belongs to means the same thing on a card and on a frame. The
 * buttons carry the shared Mixar component styling for the same reason.
 *
 * One deliberate difference: this row is LEFT-aligned, beside the frame's
 * name, where a card's is right-aligned. The name is what the pencil edits,
 * and a frame's name lives at its top-LEFT corner -- putting the button that
 * changes it at the opposite end of a wide frame would separate the control
 * from its subject.
 *
 * Rename is IN PLACE. While it runs, the row gives way to a text field
 * standing exactly where the painted name goes, bound straight to the frame's
 * `name`: applying the edit IS the rename, and Esc restores the old text
 * through the ordinary text-edit cancel. Kept alive by #ui::button_active_only,
 * the outliner's temporary-rename mechanism -- the button must be re-created
 * on every redraw while it is active, and the draw learns the edit has ended
 * when that call returns false.
 */

#include "mixie_draw_moodboard_intern.hh"

#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include <optional>

#include "ED_screen.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "UI_resources.hh"

namespace blender::ed::mixie {

/* Two square icon buttons and the gap between them. */
#define MOODBOARD_FRAME_ACTION_COUNT 2
#define MOODBOARD_FRAME_ACTION_GAP 8.0f

void moodboard_frame_action_row_rect(const rctf &frame_rect, rctf *r_row)
{
  /* ONE definition of where the row sits. The frame's painted name shares this
   * line, to the row's left, and reads this rect so the two cannot overlap on
   * a narrow frame. */
  const float height = MOODBOARD_NODE_HEADER_ROW_H * UI_SCALE_FAC;
  const float width = height * MOODBOARD_FRAME_ACTION_COUNT +
                      MOODBOARD_FRAME_ACTION_GAP * UI_SCALE_FAC *
                          (MOODBOARD_FRAME_ACTION_COUNT - 1);
  r_row->ymin = frame_rect.ymax + MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC;
  r_row->ymax = r_row->ymin + height;
  r_row->xmax = frame_rect.xmax;
  r_row->xmin = r_row->xmax - width;
}

static void add_frame_card_actions(ui::Block *block,
                                   const rcti &frame_region,
                                   const char *frame_id)
{
  /* REGION pixels, not canvas units: this block is opened after
   * `view2d_view_restore` (mixie_draw_moodboard_node_ui.cc), so everything
   * handed to a button is a region pixel. The sizes below are already pixels
   * (UI_SCALE_FAC), and mixing the two put the row somewhere else entirely at
   * any zoom or pan but 1:1 at the origin. */
  const int height = int(MOODBOARD_NODE_HEADER_ROW_H * UI_SCALE_FAC);
  const int width = height;
  const int gap = int(MOODBOARD_FRAME_ACTION_GAP * UI_SCALE_FAC);
  const int row_y = frame_region.ymax + int(MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC);

  /* Laid out from the frame's RIGHT edge, like a card's row, so the buttons
   * line up with a card's when several things are selected at once. The name
   * keeps the left end of the same line. */
  int x = frame_region.xmax - width;

  /* More: everything a frame can do that is not its name -- select contents,
   * add the selection, fit, colour, lock, collapse, ungroup, delete. A menu
   * rather than a row of glyphs because those are words, not icons. */
  ui::Button *more = ui::uiDefIconButO(block,
                                       ui::ButtonType::But,
                                       "WM_OT_call_menu",
                                       blender::wm::OpCallContext::InvokeDefault,
                                       ICON_DOWNARROW_HLT,
                                       x,
                                       row_y,
                                       width,
                                       height,
                                       nullptr);
  ui::mixar_style_button(
      more, ui::MixarComponent::Action, ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
  RNA_string_set(ui::button_operator_ptr_ensure(more), "name", "MIXIE_MT_moodboard_frame");
  moodboard_set_node_tooltip(more,
                             "Frame options\n\nSelect contents, add the selection, "
                             "fit to contents, colour, lock, collapse, ungroup or delete.");
  x -= width + gap;

  /* The pencil sits where a card's Edit sits. A frame has no settings, so what
   * it edits is the name -- the label painted above it, which this turns into
   * a text field in place. */
  ui::Button *rename = ui::uiDefIconButO(block,
                                         ui::ButtonType::But,
                                         "MIXIE_OT_moodboard_rename_frame",
                                         blender::wm::OpCallContext::ExecDefault,
                                         ICON_GREASEPENCIL,
                                         x,
                                         row_y,
                                         width,
                                         height,
                                         nullptr);
  ui::mixar_style_button(
      rename, ui::MixarComponent::Action, ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
  /* Scoped to THIS frame, so the pencil on one frame renames that frame even
   * with several selected. */
  RNA_string_set(ui::button_operator_ptr_ensure(rename), "frame_id", frame_id);
  moodboard_set_node_tooltip(rename,
                             "Rename\n\nEdit this frame's name in place, right here "
                             "above it. Enter applies, Escape keeps the old name.");
}

/* The in-place rename field, on the row's line and spanning the frame's
 * width. Returns false once the edit has ended, so the caller can put the
 * buttons back. */
static bool add_frame_rename_field(const bContext *C,
                                   ui::Block *block,
                                   ARegion *region,
                                   PointerRNA *frame,
                                   const rcti &frame_region)
{
  /* REGION pixels -- see `add_frame_card_actions`. The width matters most
   * here: taken in canvas units it is the frame's width in BOARD space, which
   * at any zoom is not the number of pixels the field should span. */
  const int height = int(MOODBOARD_NODE_HEADER_ROW_H * UI_SCALE_FAC);
  const int row_y = frame_region.ymax + int(MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC);
  /* Never narrower than a name needs: a small frame still gets a usable
   * field, anchored on its left edge where the painted name sits. */
  const int width = std::max(BLI_rcti_size_x(&frame_region),
                             int(MOODBOARD_FRAME_RENAME_MIN_W * UI_SCALE_FAC));
  /* Bound straight to the frame's own `name`, so applying the edit IS the
   * rename and there is no operator between the field and the result. */
  ui::Button *field = ui::uiDefButR(block,
                                    ui::ButtonType::Text,
                                    "",
                                    frame_region.xmin,
                                    row_y,
                                    short(width),
                                    short(height),
                                    frame,
                                    "name",
                                    -1,
                                    0.0f,
                                    0.0f,
                                    std::nullopt);
  if (!field) {
    return false;
  }
  moodboard_set_node_tooltip(field, "Rename\n\nEnter applies, Escape keeps the old name.");
  return ui::button_active_only(C, region, block, field);
}

void moodboard_add_selected_frame_actions(const bContext *C,
                                          ui::Block *block,
                                          View2D *v2d,
                                          ARegion *region,
                                          PointerRNA *scene_ptr)
{
  PropertyRNA *frames = RNA_struct_find_property(scene_ptr, "mixie_moodboard_frames");
  if (!frames) {
    return;
  }
  const Scene *scene = CTX_data_scene(C);
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, frames, &iter);
  while (iter.valid) {
    PointerRNA frame = iter.ptr;
    char frame_id[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(&frame, "frame_id", frame_id, sizeof(frame_id));
    const bool renaming = moodboard_frame_rename_is_active(scene, frame_id);
    /* Cheapest test first: this runs on every redraw over the whole board. A
     * frame being renamed keeps its field even if the selection moved on, or
     * an in-flight edit would vanish mid-keystroke. */
    if (!renaming && !RNA_boolean_get(&frame, "selected")) {
      RNA_property_collection_next(&iter);
      continue;
    }
    /* Every button here addresses the frame by its id; without one there is
     * nothing for a click to act on. */
    if (frame_id[0] == '\0') {
      RNA_property_collection_next(&iter);
      continue;
    }

    rctf frame_rect;
    moodboard_frame_rect(&frame, &frame_rect);
    /* Cull on the ROW's footprint, not the frame's: the row hangs above the
     * frame, so a frame just below the bottom edge of the viewport still has
     * its buttons on screen. */
    rctf row_rect;
    moodboard_frame_action_row_rect(frame_rect, &row_rect);
    rcti row_region;
    if (moodboard_view_rect_to_region(v2d, region, row_rect, &row_region)) {
      /* The buttons live in the block's REGION space, so the frame rect has to
       * cross over too -- `row_region` above only answers "any of it on
       * screen?". */
      rcti frame_region;
      moodboard_view_rect_to_region(v2d, region, frame_rect, &frame_region);
      if (renaming) {
        if (!add_frame_rename_field(C, block, region, &frame, frame_region)) {
          moodboard_frame_rename_end();
          /* The buttons come back on the NEXT redraw, not this one -- the same
           * one-frame notifier the outliner's rename needs. */
          ED_region_tag_redraw(region);
        }
      }
      else {
        add_frame_card_actions(block, frame_region, frame_id);
      }
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
}

}  // namespace blender::ed::mixie
