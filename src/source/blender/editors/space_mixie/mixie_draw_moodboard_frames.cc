/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Canvas frames: the washed pastel box, and the name above it.
 *
 * This replaced the old group drawing, which was a blue 3px line-strip around
 * the bounding box of whichever images carried a matching `group_index` --
 * drawn ONLY while something inside it happened to be selected, so an
 * unselected group was invisible and the canvas showed no grouping at all.
 *
 * A frame now draws because it exists:
 *
 * - A translucent wash of its own pastel over the whole rect, and a border of
 *   the same pastel at a much higher alpha. The two states differ in ALPHA
 *   only, never in saturation: the canvas is pure black, so desaturating a
 *   pastel toward white (the instinct from a white canvas) turns it grey and
 *   costs the frame the one thing that identifies it.
 * - A THICKER top strip, because that strip is also the frame's drag handle
 *   and primary click target -- the same job a node card's header does, and
 *   for the same reason: the body belongs to a marquee and to the members, so
 *   without it there is nothing to grab a frame by.
 * - Its NAME, always, selected or not. A rect cannot say which frame it is,
 *   and a board of same-shaped rectangles is exactly where a name earns its
 *   keep. Sized WITH the canvas and fitted to the frame's own width, on the
 *   rules the selected-media label already established.
 *
 * Frames paint FIRST, underneath every other canvas pass (see
 * `mixie_draw_moodboard_mode`): a translucent wash drawn on top of a card
 * would tint the result the user is looking at. The NAME is painted late, in
 * the screen-space pass, so it is never covered by a member.
 */

#include "mixie_draw_moodboard_intern.hh"

#include "BLI_string.h"
#include "BLI_string_utf8.h"

#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include "UI_interface_c.hh"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Frame Boxes (canvas space)
 * \{ */

static void draw_frame_box(const rctf &rect,
                           const float color[3],
                           const bool selected,
                           const bool collapsed)
{
  const float fill[4] = {
      color[0],
      color[1],
      color[2],
      selected ? MOODBOARD_FRAME_FILL_ALPHA_SELECTED : MOODBOARD_FRAME_FILL_ALPHA,
  };
  const float border[4] = {
      color[0],
      color[1],
      color[2],
      selected ? MOODBOARD_FRAME_BORDER_ALPHA_SELECTED : MOODBOARD_FRAME_BORDER_ALPHA,
  };

  rctf strip;
  moodboard_frame_top_strip(rect, &strip);

  if (collapsed) {
    /* A collapsed frame IS its title bar: nothing below it is drawn, and the
     * hit-test agrees (`moodboard_frame_part_at`), so there is no invisible
     * body left behind to click on. */
    ui::draw_roundbox_corner_set(ui::CNR_ALL);
    ui::draw_roundbox_4fv(&strip, true, MOODBOARD_FRAME_RADIUS * 0.5f, border);
    return;
  }

  /* One call for the wash and its border, so the outline is exactly
   * MOODBOARD_FRAME_BORDER thick in CANVAS units and follows the same rounded
   * path as the fill. */
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv_ex(
      &rect, fill, fill, 0.0f, border, MOODBOARD_FRAME_BORDER, MOODBOARD_FRAME_RADIUS);

  /* The thicker top. Only the top corners are rounded, so the strip sits
   * flush inside the border it continues rather than reading as a separate
   * floating bar. */
  ui::draw_roundbox_corner_set(ui::CNR_TOP_LEFT | ui::CNR_TOP_RIGHT);
  ui::draw_roundbox_4fv(&strip, true, MOODBOARD_FRAME_RADIUS, border);
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
}

void mixie_draw_moodboard_frames(const bContext *C, View2D *v2d)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *frames = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_frames");
  if (!frames) {
    return;
  }

  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, frames, &iter);
  while (iter.valid) {
    rctf rect;
    moodboard_frame_rect(&iter.ptr, &rect);
    if (is_rect_in_view(v2d, rect.xmin, rect.ymin, BLI_rctf_size_x(&rect),
                        BLI_rctf_size_y(&rect)))
    {
      float color[3];
      moodboard_frame_color(&iter.ptr, color);
      const bool selected = RNA_boolean_get(&iter.ptr, "selected");
      const bool collapsed = RNA_boolean_get(&iter.ptr, "collapsed");
      /* No resize grip: a frame has no manual resize. Its rect follows what
       * it holds -- it grows to keep a member dragged outwards, and "Fit to
       * Contents" wraps it back to them. */
      draw_frame_box(rect, color, selected, collapsed);
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Frame Names (screen space)
 * \{ */

static void frame_label_text(const char *name, char *out, const size_t out_size)
{
  /* Folded in the MIDDLE, never at the end, for the same reason a media name
   * is: what tells two frames apart is as often their tail as their head. */
  size_t byte_length = 0;
  const size_t char_length = BLI_strlen_utf8_ex(name, &byte_length);
  if (char_length <= MOODBOARD_FRAME_LABEL_MAX_CHARS) {
    BLI_strncpy_utf8(out, name, out_size);
    return;
  }
  /* UTF-8 offsets, never raw byte counts, so a multi-byte character is never
   * cut in half into a replacement glyph. */
  const int head_bytes = BLI_str_utf8_offset_from_index(
      name, byte_length, MOODBOARD_FRAME_LABEL_HEAD_CHARS);
  const int tail_bytes = BLI_str_utf8_offset_from_index(
      name, byte_length, int(char_length) - MOODBOARD_FRAME_LABEL_TAIL_CHARS);
  char head[MOODBOARD_FRAME_LABEL_MAX_CHARS * 4 + 1];
  BLI_strncpy(head, name, std::min(size_t(head_bytes) + 1, sizeof(head)));
  BLI_snprintf(out, out_size, "%s...%s", head, name + tail_bytes);
}

void mixie_draw_moodboard_frame_labels(View2D *v2d, ARegion *region, PointerRNA *scene_ptr)
{
  PropertyRNA *frames = RNA_struct_find_property(scene_ptr, "mixie_moodboard_frames");
  if (!frames || RNA_property_collection_length(scene_ptr, frames) == 0) {
    return;
  }
  /* `scene_ptr` is the ID pointer the caller made from the scene, so its data
   * IS the scene; needed to ask whether a frame's in-place rename is up. */
  const Scene *scene = static_cast<const Scene *>(scene_ptr->data);
  const int font_id = BLF_default();
  const float view_scale = ui::view2d_scale_get_x(v2d);

  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, frames, &iter);
  while (iter.valid) {
    char frame_id[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(&iter.ptr, "frame_id", frame_id, sizeof(frame_id));
    /* While the in-place rename field is up it stands exactly where this name
     * goes; painting the name too would draw it twice. */
    if (moodboard_frame_rename_is_active(scene, frame_id)) {
      RNA_property_collection_next(&iter);
      continue;
    }

    rctf rect;
    moodboard_frame_rect(&iter.ptr, &rect);
    rcti region_rect;
    if (!moodboard_view_rect_to_region(v2d, region, rect, &region_rect)) {
      RNA_property_collection_next(&iter);
      continue;
    }

    char name[MIXIE_FRAME_NAME_BUF];
    mixie_rna_string_get_clamped(&iter.ptr, "name", name, sizeof(name));
    if (name[0] == '\0') {
      RNA_property_collection_next(&iter);
      continue;
    }
    char label[MOODBOARD_FRAME_LABEL_MAX_CHARS * 4 + 8];
    frame_label_text(name, label, sizeof(label));
    const size_t label_length = strlen(label);

    /* Sized with the canvas, clamped for legibility, then FITTED to the width
     * actually available -- in that order. Clamping after the fit would let a
     * name come back wider than the frame it labels. */
    float font_px = std::clamp(MOODBOARD_FRAME_LABEL_SIZE_PX * UI_SCALE_FAC * view_scale,
                               MOODBOARD_FRAME_LABEL_MIN_PX * UI_SCALE_FAC,
                               MOODBOARD_FRAME_LABEL_MAX_PX * UI_SCALE_FAC);
    BLF_size(font_id, font_px);
    float text_width = BLF_width(font_id, label, label_length);
    /* A SELECTED frame wears its Rename / More row on this same line, at the
     * frame's right edge, so the name only gets what is left of the width.
     * Read from the row's ONE rect definition, or on a narrow frame the name
     * would run under the buttons -- a name the user cannot read and buttons
     * they cannot see. */
    float frame_width = float(BLI_rcti_size_x(&region_rect));
    if (RNA_boolean_get(&iter.ptr, "selected")) {
      rctf row_rect;
      moodboard_frame_action_row_rect(rect, &row_rect);
      rcti row_region;
      if (moodboard_view_rect_to_region(v2d, region, row_rect, &row_region)) {
        const float gap_px = 6.0f * UI_SCALE_FAC;
        frame_width = std::max(
            float(row_region.xmin - region_rect.xmin) - gap_px, 0.0f);
      }
    }
    if (text_width > frame_width && text_width > 0.0f) {
      /* Glyph advance is linear in the point size, so one correction lands it. */
      font_px *= frame_width / text_width;
      BLF_size(font_id, font_px);
      text_width = BLF_width(font_id, label, label_length);
    }
    /* Only reachable through the fit above: a frame too narrow to carry a
     * readable name carries none, rather than an unreadable smear. */
    if (font_px < MOODBOARD_FRAME_LABEL_MIN_PX * UI_SCALE_FAC) {
      RNA_property_collection_next(&iter);
      continue;
    }

    const float gap = font_px * 0.45f;
    /* Above the top-left corner, left-aligned to the frame's own left edge:
     * the shared edge is what reads as "this name belongs to that frame", the
     * same reason a media name is left-aligned to its tile. */
    float text_x = float(region_rect.xmin);
    float text_y = float(region_rect.ymax) + gap;
    text_x = std::clamp(
        text_x, 4.0f, std::max(4.0f, float(region->winx) - text_width - 4.0f));
    text_y = std::clamp(
        text_y, 4.0f, std::max(4.0f, float(region->winy) - font_px - 4.0f));

    /* Painted in the frame's OWN pastel: on a board of several frames the
     * colour is how a name is matched to its box at a glance, which is the
     * whole argument for giving frames colours in the first place. */
    float color[3];
    moodboard_frame_color(&iter.ptr, color);
    const bool selected = RNA_boolean_get(&iter.ptr, "selected");
    BLF_color4f(font_id, color[0], color[1], color[2], selected ? 1.0f : 0.82f);
    BLF_position(font_id, text_x, text_y, 0.0f);
    BLF_draw(font_id, label, label_length);

    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
}

/** \} */

}  // namespace blender::ed::mixie
