/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Cinema Mode popup rows: the hover-expanding segmented group
 * (#MixarCinemaRowKind::Segment).
 *
 * A group is N equal cells on one baseline (the lens popup's Perspective /
 * Orthographic / Panoramic). The cells are too narrow for their labels, so
 * while one is hovered it is PAINTED wide enough for its whole label and
 * the others share what is left, in order.
 *
 * Why the painter and not a re-layout: a native block popup opened from a
 * dropdown (`uiDefIconBlockBut`) is never refreshed — `can_refresh` is
 * false for it (`interface_handlers.cc`, the `popup_menu_create` call in
 * `button_activate_init`'s menu branch) — so the block cannot re-lay its
 * buttons on hover. The HIT rects therefore stay the original equal cells;
 * only the painted cells move. The hovered cell grows OUTWARD from its own
 * cell (leftmost grows right, middle both ways, rightmost left) and always
 * contains its hit rect, so the pointer never leaves the cell it is
 * revealing.
 *
 * Each cell paints ONLY its own computed rect, so the result is the same
 * whatever order the block draws its buttons in.
 */

#include <algorithm>
#include <cmath>

#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "UI_interface_c.hh"
#include "UI_mixar_motion.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_cinema_row.hh"
#include "interface_mixar_profile_card.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui::mixar_cinema_row {

namespace {

constexpr int MAX_CELLS = 8;

struct SegmentGroup {
  /** Members left to right (block coordinates, `Button::rect`). */
  Button *members[MAX_CELLS] = {};
  int count = 0;
  /** Index of the button being painted, and of the hovered member (-1 if none). */
  int self = -1;
  int hovered = -1;
  /** Union of the members' rects, block coordinates. */
  rctf bounds = {};
};

bool same_baseline(const Button &a, const Button &b)
{
  return std::fabs(a.rect.ymin - b.rect.ymin) < 0.5f &&
         std::fabs(a.rect.ymax - b.rect.ymax) < 0.5f;
}

bool is_segment(const Button &but)
{
  return UI_mixar_card_element_get(&but) == MixarCardElement::CinemaRow &&
         UI_mixar_cinema_row_kind_get(&but) == MixarCinemaRowKind::Segment;
}

/** Collect the Segment buttons sharing \a but's baseline, ordered by `rect.xmin`. */
void group_collect(Button *but, SegmentGroup *group)
{
  for (Button &other : but->block->buttons()) {
    if (!is_segment(other) || !same_baseline(other, *but)) {
      continue;
    }
    if (group->count == MAX_CELLS) {
      break;
    }
    int index = group->count;
    while (index > 0 && group->members[index - 1]->rect.xmin > other.rect.xmin) {
      group->members[index] = group->members[index - 1];
      index--;
    }
    group->members[index] = &other;
    group->count++;
  }
  for (int index = 0; index < group->count; index++) {
    const Button *member = group->members[index];
    if (member == but) {
      group->self = index;
    }
    if ((member->flag & UI_HOVER) != 0 && (member->flag & BUT_DISABLED) == 0) {
      group->hovered = index;
    }
    if (index == 0) {
      group->bounds = member->rect;
    }
    else {
      BLI_rctf_union(&group->bounds, &member->rect);
    }
  }
}

/**
 * The painted cell of member \a index, in block coordinates. Without a
 * hovered member every cell is its own rect; with one, the hovered cell is
 * as wide as its label plus the row padding (never narrower than its own
 * cell, never so wide that another cell drops under #SEGMENT_MIN_W) and the
 * rest share the remainder equally, laid out in order from the group's left
 * edge — which is exactly what keeps the hovered cell over its hit rect.
 */
rctf cell_rect(const SegmentGroup &group,
               const uiFontStyle &fs,
               const int index,
               const float px_per_unit)
{
  const Button *self = group.members[index];
  if (group.hovered < 0 || group.count < 2) {
    return self->rect;
  }
  const Button *hot = group.members[group.hovered];
  const float total = BLI_rctf_size_x(&group.bounds);
  const float own = BLI_rctf_size_x(&hot->rect);
  /* Label width is measured in pixels; the block may be scaled. */
  const float need = (fontstyle_string_width(&fs, row_label(hot)) +
                      2.0f * TEXT_PAD * UI_SCALE_FAC) /
                     px_per_unit;
  const float others_min = SEGMENT_MIN_W * UI_SCALE_FAC / px_per_unit * float(group.count - 1);
  const float hot_w = std::clamp(need, own, std::max(own, total - others_min));
  const float rest_w = (total - hot_w) / float(group.count - 1);

  rctf cell = group.bounds;
  float x = group.bounds.xmin;
  for (int i = 0; i <= index; i++) {
    const float w = (i == group.hovered) ? hot_w : rest_w;
    cell.xmin = x;
    cell.xmax = x + w;
    x += w;
  }
  return cell;
}

}  // namespace

void draw_segment(Button *but, const rcti *rect)
{
  SegmentGroup group;
  group_collect(but, &group);
  const uiFontStyle fs = row_font();

  /* `rect` is the button's pixel rect; the group is laid out in block
   * coordinates, so map the computed cell through the same affine
   * transform (uniform scale, x offset) the widget rect went through. */
  const float block_w = std::max(BLI_rctf_size_x(&but->rect), 1e-3f);
  const float px_per_unit = float(BLI_rcti_size_x(rect)) / block_w;
  rctf cell;
  if (group.self < 0) {
    mixar_card_rect_to_rctf(rect, &cell);
  }
  else {
    const rctf block_cell = cell_rect(group, fs, group.self, px_per_unit);
    cell.xmin = float(rect->xmin) + (block_cell.xmin - but->rect.xmin) * px_per_unit;
    cell.xmax = float(rect->xmin) + (block_cell.xmax - but->rect.xmin) * px_per_unit;
    cell.ymin = float(rect->ymin);
    cell.ymax = float(rect->ymax);
  }

  /* The shared sampler keeps BUT_ACTIVE_DEFAULT selection separate from
   * operator press. Existing label-reveal geometry and hit cells stay native. */
  const MixarInteraction motion = mixar_button_motion(*but);
  const bool disabled = (but->flag & (BUT_DISABLED | BUT_INACTIVE)) != 0;
  rctf row = cell;
  const float inset = 1.0f * UI_SCALE_FAC;
  BLI_rctf_pad(&row, -inset, -inset);
  const float rad = row_radius(row);
  const float hover = 0.9f * motion.hover + (1.0f - 0.9f * motion.hover) * motion.press;
  draw_hover(row, rad, hover * (1.0f - motion.selected));
  if (motion.selected > 0.0f) {
    draw_chip(row, rad, motion.selected);
  }

  rcti text;
  BLI_rcti_rctf_copy(&text, &cell);
  text.xmin += int(TEXT_PAD * UI_SCALE_FAC);
  text.xmax -= int(TEXT_PAD * UI_SCALE_FAC);
  uchar col[4];
  for (int i = 0; i < 4; i++) {
    col[i] = disabled ?
                 TEXT_DISABLED[i] :
                 uchar(float(TEXT_OFF[i]) + (float(TEXT_ON[i]) - TEXT_OFF[i]) * motion.selected);
  }
  draw_label(fs, &text, row_label(but), col, UI_STYLE_TEXT_CENTER, pad_slack(), pad_slack());
}

}  // namespace blender::ui::mixar_cinema_row
