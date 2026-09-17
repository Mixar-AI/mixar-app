/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The ONE definition of a canvas frame's geometry.
 *
 * Draw, the floating action row and the hit-test all resolve a frame's rect,
 * its thick top strip and its resize grip through here. Every one of those
 * metrics is in CANVAS units, so they zoom with the frame -- and because the
 * same function answers "where is it" and "what did I just click", the pixels
 * the user aims at cannot drift away from the region that responds at some
 * zoom. (The socket radii and the node card's grip are shared for exactly the
 * same reason.)
 *
 * The palette lives here too, as the painter's copy of `FRAME_PALETTE` in
 * `moodboard/constants.py`. The two are duplicated across languages by
 * necessity and pinned together by `tests/moodboard/test_frame_ui.py`.
 */

#include "mixie_draw_moodboard_intern.hh"

namespace blender::ed::mixie {

/* Eight pastels, cycled by `palette_index`. Must equal FRAME_PALETTE in
 * moodboard/constants.py -- the Python side only needs them for the colour
 * menu's labels, but a drift there would name one pastel and paint another. */
static const float FRAME_PALETTE[8][3] = {
    {0.96f, 0.64f, 0.64f}, /* Rose */
    {0.97f, 0.79f, 0.61f}, /* Apricot */
    {0.95f, 0.91f, 0.63f}, /* Butter */
    {0.72f, 0.89f, 0.66f}, /* Mint */
    {0.64f, 0.86f, 0.85f}, /* Aqua */
    {0.65f, 0.77f, 0.94f}, /* Sky */
    {0.76f, 0.69f, 0.93f}, /* Lilac */
    {0.94f, 0.69f, 0.84f}, /* Orchid */
};
#define MOODBOARD_FRAME_PALETTE_SIZE 8

const float *moodboard_frame_palette_color(const int index)
{
  /* Wrapped rather than clamped: `palette_index` is bounded by RNA, but a
   * .blend written against a larger palette must still resolve to a colour. */
  const int slot = ((index % MOODBOARD_FRAME_PALETTE_SIZE) + MOODBOARD_FRAME_PALETTE_SIZE) %
                   MOODBOARD_FRAME_PALETTE_SIZE;
  return FRAME_PALETTE[slot];
}

void moodboard_frame_color(PointerRNA *frame, float r_color[3])
{
  /* The palette index is the norm and a custom colour an explicit opt-in, so
   * clearing the flag restores the pastel instead of losing it. */
  PropertyRNA *use_custom = RNA_struct_find_property(frame, "use_custom_color");
  if (use_custom && RNA_property_boolean_get(frame, use_custom)) {
    PropertyRNA *custom = RNA_struct_find_property(frame, "custom_color");
    if (custom) {
      RNA_property_float_get_array(frame, custom, r_color);
      return;
    }
  }
  PropertyRNA *palette = RNA_struct_find_property(frame, "palette_index");
  const int index = palette ? RNA_property_int_get(frame, palette) : 0;
  copy_v3_v3(r_color, moodboard_frame_palette_color(index));
}

void moodboard_frame_rect(PointerRNA *frame, rctf *r_rect)
{
  r_rect->xmin = RNA_float_get(frame, "position_x");
  r_rect->ymin = RNA_float_get(frame, "position_y");
  r_rect->xmax = r_rect->xmin + RNA_float_get(frame, "width");
  r_rect->ymax = r_rect->ymin + RNA_float_get(frame, "height");
}

void moodboard_frame_top_strip(const rctf &frame_rect, rctf *r_strip)
{
  /* Inside the top edge, spanning the full width. This is the frame's drag
   * handle: its interior belongs to a marquee and its members, so without a
   * strip wide enough to aim at there would be nothing to grab a frame BY --
   * the same problem a node card's body had before it grew a header. */
  const float height = std::min(MOODBOARD_FRAME_TOP_BORDER,
                                BLI_rctf_size_y(&frame_rect) * 0.5f);
  r_strip->xmin = frame_rect.xmin;
  r_strip->xmax = frame_rect.xmax;
  r_strip->ymax = frame_rect.ymax;
  r_strip->ymin = frame_rect.ymax - height;
}

MoodboardFramePart moodboard_frame_part_at(const rctf &frame_rect,
                                           const float mouse_x,
                                           const float mouse_y,
                                           const float view_scale,
                                           const bool collapsed)
{
  /* A collapsed frame IS its top strip -- nothing below it is drawn, so
   * nothing below it can be hit either. */
  if (collapsed) {
    rctf strip;
    moodboard_frame_top_strip(frame_rect, &strip);
    return BLI_rctf_isect_pt(&strip, mouse_x, mouse_y) ? MOODBOARD_FRAME_PART_TOP :
                                                         MOODBOARD_FRAME_PART_NONE;
  }

  if (!BLI_rctf_isect_pt(&frame_rect, mouse_x, mouse_y)) {
    return MOODBOARD_FRAME_PART_NONE;
  }

  /* The grab zone is wider than the paint, and never narrower than a few
   * pixels: even a 7-canvas-unit border is sub-pixel when zoomed out, and an
   * edge the user can see but cannot grab is worse than no edge at all. */
  const float scale = std::max(view_scale, 0.001f);
  const float slop = std::max(MOODBOARD_FRAME_BORDER * MOODBOARD_FRAME_HIT_SLOP,
                              MOODBOARD_FRAME_HIT_MIN_PX / scale);

  /* No grip: a frame has no manual resize. Its rect follows what it holds --
   * it grows to keep a member the user drags outwards, "Fit to Contents"
   * wraps it back to them, and that is the whole of it. A hand-sized frame
   * was a second, competing way to say where its edges go, and it fought the
   * automatic grow on every drag. */
  rctf strip;
  moodboard_frame_top_strip(frame_rect, &strip);
  /* Padded DOWNWARD only on the inside edge; the frame's own rect already
   * bounds the other three sides. */
  if (mouse_y >= strip.ymin - slop && mouse_y <= strip.ymax) {
    return MOODBOARD_FRAME_PART_TOP;
  }

  if (mouse_x <= frame_rect.xmin + slop || mouse_x >= frame_rect.xmax - slop ||
      mouse_y <= frame_rect.ymin + slop)
  {
    return MOODBOARD_FRAME_PART_BORDER;
  }

  return MOODBOARD_FRAME_PART_INTERIOR;
}

int moodboard_find_frame_at(PointerRNA *scene_ptr,
                            const float mouse_x,
                            const float mouse_y,
                            const float view_scale,
                            MoodboardFramePart *r_part,
                            rctf *r_rect)
{
  if (r_part) {
    *r_part = MOODBOARD_FRAME_PART_NONE;
  }
  PropertyRNA *frames = RNA_struct_find_property(scene_ptr, "mixie_moodboard_frames");
  if (!frames) {
    return -1;
  }

  int best_index = -1;
  float best_area = 0.0f;
  MoodboardFramePart best_part = MOODBOARD_FRAME_PART_NONE;
  rctf best_rect{};

  const int count = RNA_property_collection_length(scene_ptr, frames);
  for (int i = 0; i < count; i++) {
    PointerRNA frame;
    if (!RNA_property_collection_lookup_int(scene_ptr, frames, i, &frame)) {
      continue;
    }
    /* A locked frame is transparent to the pointer -- that is the whole
     * meaning of the lock: leave the frame alone, reach its members. */
    PropertyRNA *locked = RNA_struct_find_property(&frame, "locked");
    if (locked && RNA_property_boolean_get(&frame, locked)) {
      continue;
    }
    PropertyRNA *collapsed_prop = RNA_struct_find_property(&frame, "collapsed");
    const bool collapsed = collapsed_prop &&
                           RNA_property_boolean_get(&frame, collapsed_prop);

    rctf rect;
    moodboard_frame_rect(&frame, &rect);
    const MoodboardFramePart part = moodboard_frame_part_at(
        rect, mouse_x, mouse_y, view_scale, collapsed);
    if (part == MOODBOARD_FRAME_PART_NONE) {
      continue;
    }
    /* Smallest area wins, so a frame drawn inside another one takes the click
     * -- the same rule `frame_for_point` applies to membership, which is what
     * keeps "what did I click" and "what is this inside" in agreement. */
    const float area = BLI_rctf_size_x(&rect) * BLI_rctf_size_y(&rect);
    if (best_index == -1 || area < best_area) {
      best_index = i;
      best_area = area;
      best_part = part;
      best_rect = rect;
    }
  }

  if (best_index != -1) {
    if (r_part) {
      *r_part = best_part;
    }
    if (r_rect) {
      *r_rect = best_rect;
    }
  }
  return best_index;
}

bool moodboard_frame_select_at_point(PointerRNA *scene_ptr,
                                     const float mouse_x,
                                     const float mouse_y,
                                     const float view_scale)
{
  /* A plain CLICK anywhere on a frame -- its chrome or its empty interior --
   * selects that frame. Selecting only from the title strip read as arbitrary:
   * the rect is visibly one object, so every part of it that is not covered by
   * something else should answer to a click.
   *
   * This is deliberately NOT in `frame_select_invoke`. That operator installs
   * a modal, so claiming the interior there would take the press away from the
   * two gestures that own it: a member's own drag, and the marquee over open
   * space inside the frame. The press therefore still passes through, and the
   * CLICK is resolved here -- from the one branch that already knows the
   * gesture ended as a click rather than a drag (box select's tiny-box case)
   * -- so a frame is selected by clicking it and MOVED only by its border.
   *
   * Callers have already cleared the selection; this only adds the frame. */
  MoodboardFramePart part = MOODBOARD_FRAME_PART_NONE;
  const int index = moodboard_find_frame_at(
      scene_ptr, mouse_x, mouse_y, view_scale, &part, nullptr);
  if (index < 0 || part == MOODBOARD_FRAME_PART_NONE) {
    return false;
  }
  PropertyRNA *frames = RNA_struct_find_property(scene_ptr, "mixie_moodboard_frames");
  PointerRNA frame;
  if (!frames || !RNA_property_collection_lookup_int(scene_ptr, frames, index, &frame)) {
    return false;
  }
  RNA_boolean_set(&frame, "selected", true);
  return true;
}

}  // namespace blender::ed::mixie
