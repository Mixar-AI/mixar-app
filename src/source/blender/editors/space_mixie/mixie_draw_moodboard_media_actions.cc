/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The action row floating above a selected reference image or movie.
 *
 * A finished inference node carries Edit / Preview / Export just above its
 * card (mixie_draw_moodboard_node_tile_controls.cc). A reference the user
 * dropped on the board is the same kind of thing to look at and take away --
 * but it has no settings to edit, so its first button is Rename: the one
 * thing about a reference that CAN be changed from the board, and the name is
 * what the selected-media label paints, so the two go together.
 *
 * Same geometry as the node row, from the same two header constants, so a
 * reference and a card selected side by side wear their rows on one line.
 * Laid out in CANVAS units from the media's own rect, inside the canvas block
 * the node controls already build, so the buttons scale and pan with the tile
 * and clicks land on them at every zoom.
 *
 * Rename is IN PLACE: while a tile is being renamed the row gives way to a
 * text field on that same line, bound straight to the Image datablock's name,
 * where the painted name normally sits. There is no dialog -- the first
 * version had one, and it exposed the internal media id as a field beside the
 * name over a stock OK/Cancel row, a form for something that is one word.
 */

#include "mixie_draw_moodboard_intern.hh"

#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include <optional>

#include "ED_screen.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

namespace blender::ed::mixie {

/* Three square icon buttons and the gaps between them. */
#define MOODBOARD_MEDIA_ACTION_COUNT 3
#define MOODBOARD_MEDIA_ACTION_GAP 8.0f

void moodboard_media_action_row_rect(const rctf &media_rect, rctf *r_row)
{
  /* ONE definition of where the row sits, shared with the selected-media label
   * painter: the name is left-aligned above the tile and this row is
   * right-aligned above it, so on a narrow tile the two would meet -- the label
   * reads this rect as taken and drops inside its picture instead. */
  const float height = MOODBOARD_NODE_HEADER_ROW_H * UI_SCALE_FAC;
  const float width = height * MOODBOARD_MEDIA_ACTION_COUNT +
                      MOODBOARD_MEDIA_ACTION_GAP * UI_SCALE_FAC *
                          (MOODBOARD_MEDIA_ACTION_COUNT - 1);
  r_row->ymin = media_rect.ymax + MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC;
  r_row->ymax = r_row->ymin + height;
  r_row->xmax = media_rect.xmax;
  r_row->xmin = r_row->xmax - width;
}

void moodboard_add_media_card_actions(uiBlock *block,
                                      const rctf &media_rect,
                                      const char *media_id)
{
  /* Floats OUTSIDE the tile, on the row just above its top edge, exactly like
   * the node card's row -- the picture is the whole point of the tile, so
   * nothing is laid over it. */
  const int height = int(MOODBOARD_NODE_HEADER_ROW_H * UI_SCALE_FAC);
  const int width = height;
  const int gap = int(MOODBOARD_MEDIA_ACTION_GAP * UI_SCALE_FAC);
  const int row_y = int(media_rect.ymax + MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC);

  /* Laid out from the right edge, in the node row's order: Export claims the
   * corner, Preview steps left of it, and the "change it" button takes the
   * left-most slot -- so the same glyph means the same thing in the same place
   * on a reference and on a card. */
  int x = int(media_rect.xmax) - width;

  /* ICON_IMPORT for the same reason as the node row: the arrow INTO the tray
   * is the download sign the user reads. InvokeDefault because the exporter
   * opens a file dialog. */
  uiBut *save = uiDefIconButO(block,
                              ButType::But,
                              "MIXIE_OT_moodboard_export_images",
                              blender::wm::OpCallContext::InvokeDefault,
                              ICON_IMPORT,
                              x,
                              row_y,
                              width,
                              height,
                              nullptr);
  /* Scoped to THIS reference, so the button on one tile saves that tile even
   * with several selected. */
  RNA_string_set(UI_but_operator_ptr_ensure(save), "media_id", media_id);
  moodboard_set_node_tooltip(save, "Export\n\nSave this image or video to disk.");
  x -= width + gap;

  uiBut *preview = uiDefIconButO(block,
                                 ButType::But,
                                 "MIXIE_OT_moodboard_preview_media",
                                 blender::wm::OpCallContext::ExecDefault,
                                 ICON_WINDOW,
                                 x,
                                 row_y,
                                 width,
                                 height,
                                 nullptr);
  RNA_string_set(UI_but_operator_ptr_ensure(preview), "media_id", media_id);
  moodboard_set_node_tooltip(
      preview,
      "Preview\n\nOpen this image or video in its own window. Several previews "
      "can be open at once.");
  x -= width + gap;

  /* The pencil sits where a card's Edit sits. A reference has no settings, so
   * what it edits is the name -- the label painted above the tile, which the
   * operator turns into a text field in place (see the file header). */
  uiBut *rename = uiDefIconButO(block,
                                ButType::But,
                                "MIXIE_OT_moodboard_rename_media",
                                blender::wm::OpCallContext::ExecDefault,
                                ICON_GREASEPENCIL,
                                x,
                                row_y,
                                width,
                                height,
                                nullptr);
  RNA_string_set(UI_but_operator_ptr_ensure(rename), "media_id", media_id);
  moodboard_set_node_tooltip(rename,
                             "Rename\n\nEdit this image or video's name in place, right "
                             "here above it. Enter applies, Escape keeps the old name.");
}

/* The in-place rename field, on the row's line and spanning the tile's
 * width. Returns false once the edit has ended, so the caller can put the
 * buttons back. */
static bool moodboard_add_media_rename_field(const bContext *C,
                                             uiBlock *block,
                                             ARegion *region,
                                             PointerRNA *image_ptr,
                                             const rctf &media_rect)
{
  const int height = int(MOODBOARD_NODE_HEADER_ROW_H * UI_SCALE_FAC);
  const int row_y = int(media_rect.ymax + MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC);
  /* Never narrower than a name needs: a user-shrunk tile still gets a usable
   * field, anchored on the tile's left edge like the painted name is. */
  const int width = std::max(int(BLI_rctf_size_x(&media_rect)),
                             int(MOODBOARD_MEDIA_RENAME_MIN_W * UI_SCALE_FAC));
  /* Bound straight to the datablock's `name`: applying the edit IS the rename
   * (RNA's ID-name setter uniquifies a clash the way Blender always does), so
   * there is no operator between the field and the result, and Esc restores
   * the old text through the ordinary text-edit cancel. */
  uiBut *field = uiDefButR(block,
                           ButType::Text,
                           0,
                           "",
                           int(media_rect.xmin),
                           row_y,
                           short(width),
                           short(height),
                           image_ptr,
                           "name",
                           -1,
                           0.0f,
                           0.0f,
                           std::nullopt);
  if (!field) {
    return false;
  }
  moodboard_set_node_tooltip(field, "Rename\n\nEnter applies, Escape keeps the old name.");
  /* The outliner's temporary-rename mechanism: the first call activates the
   * field (text editing, cursor in it, text selected); every later redraw must
   * re-create the button and call this again to keep the edit alive; and once
   * the edit has ended -- Enter, Escape, or a click elsewhere -- it removes
   * the button and returns false. */
  return UI_but_active_only(C, region, block, field);
}

void moodboard_add_selected_media_actions(const bContext *C,
                                          uiBlock *block,
                                          View2D *v2d,
                                          ARegion *region,
                                          PointerRNA *scene_ptr,
                                          const MoodboardGraphCache *cache)
{
  PropertyRNA *images = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (!images) {
    return;
  }
  const Scene *scene = CTX_data_scene(C);
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, images, &iter);
  while (iter.valid) {
    PointerRNA media = iter.ptr;
    /* Cheapest test first: this runs every redraw over the whole board. */
    if (!RNA_boolean_get(&media, "selected")) {
      RNA_property_collection_next(&iter);
      continue;
    }
    /* Node-owned media is a card's result and already has the card's row. */
    PropertyRNA *embedded = RNA_struct_find_property(&media, "embedded_node_id");
    const bool standalone = !embedded || RNA_property_string_length(&media, embedded) == 0;
    PointerRNA image_ptr = RNA_pointer_get(&media, "image");
    if (!standalone || !image_ptr.data) {
      RNA_property_collection_next(&iter);
      continue;
    }
    /* The rect comes from the shared per-frame cache, which is keyed by the
     * media's own graph id. Id-less media (a board saved before the id
     * migration) gets no row: every button here addresses the tile by that id,
     * so without one there is nothing for a click to act on. The id migration
     * runs from the poll tick and the next redraw picks it up. */
    char media_id[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(&media, "node_id", media_id, sizeof(media_id));
    const rctf *media_rect = media_id[0] ? cache->outputs.lookup_ptr(media_id) : nullptr;
    if (media_rect) {
      /* Cull on the ROW's footprint, not the tile's: the row hangs above the
       * tile, so a tile just below the bottom edge of the viewport still has
       * its buttons on screen. */
      rctf row_rect;
      moodboard_media_action_row_rect(*media_rect, &row_rect);
      rcti row_region;
      if (moodboard_view_rect_to_region(v2d, region, row_rect, &row_region)) {
        if (moodboard_media_rename_is_active(scene, media_id)) {
          /* The field takes the row's place: once the user is typing, the
           * three buttons have nothing to add, and the field wants the tile's
           * whole width for the name. */
          if (!moodboard_add_media_rename_field(C, block, region, &image_ptr, *media_rect)) {
            moodboard_media_rename_end();
            /* The buttons come back on the next redraw, not this one -- the
             * same one-frame notifier the outliner's rename needs. */
            ED_region_tag_redraw(region);
          }
        }
        else {
          moodboard_add_media_card_actions(block, *media_rect, media_id);
        }
      }
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
}

}  // namespace blender::ed::mixie
