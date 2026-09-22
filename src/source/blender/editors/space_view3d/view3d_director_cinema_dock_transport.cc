/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the timeline dock's centred transport — previous keyframe,
 * preview, next keyframe — and the media glyphs it paints.
 *
 * Split from `view3d_director_cinema_dock.cc` for the 500-line rule. The
 * glyphs are hand-drawn primitives rather than stock icons because the design
 * asks for a step pair (`◂●  ▶  ●▸`) Blender does not ship.
 *
 * Painting only; every slot is a real ui::Button over the painted pixels.
 */

#include <algorithm>

#include "BLI_rect.h"

#include "DNA_screen_types.h"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_overlay_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/** Transport hit box (square) and the clear space between neighbours: the
 * glyph centres sit `TRANSPORT_SIZE + TRANSPORT_GAP` = 44 apart. */
constexpr float TRANSPORT_SIZE = 26.0f;
constexpr float TRANSPORT_GAP = 18.0f;
/* Transport glyph sizes, measured off the design mock (see #transport_glyph).
 * They are explicit so the hit box no longer decides how big a glyph is. */
constexpr float PLAY_H = 18.0f;
constexpr float STEP_H = 12.0f;
constexpr float DOT_D = 5.5f;
constexpr float STEP_GAP = 3.0f;
/** Triangle width over height: the mock's play is 16 x 15, a step's 8.5 x 9.5. */
constexpr float GLYPH_ASPECT = 0.95f;
/** One muted grey for every transport glyph (mock: RGB 135, pause included). */
constexpr float TRANSPORT_COL[4] = {0.53f, 0.53f, 0.53f, 1.0f};

/**
 * Media glyphs per the design: the preview (play) is a filled triangle; a
 * step is a smaller triangle pointing outward with a dot on its INNER side
 * (`◂●  ▶  ●▸`), not the stock bar-on-the-outside.
 *
 * Proportions measured off the 1x design mock (glyph pixel bounding boxes):
 * play 16 wide x 15 tall (a squat, near-equilateral triangle, NOT tall and
 * narrow); a step pair 15 x 10 overall — triangle ~8.5 x 9.5, dot ~4.5 in
 * diameter, ~2.5 between the triangle's flat inner edge and the dot; glyph
 * centres 36 apart, i.e. ~2.4x the play height; every glyph the same muted
 * grey. The tokens above (`PLAY_H`, `STEP_H`, `DOT_D`, `STEP_GAP`,
 * `GLYPH_ASPECT`, `TRANSPORT_COL`) are those numbers rounded to the design's
 * unit; only `box` centre is used — the hit box never sizes the glyph.
 */
void transport_glyph(const rctf &box, const bool forward, const bool step, const bool pause)
{
  const float u = cinema_unit();
  const float *col = TRANSPORT_COL;
  const float cx = BLI_rctf_cent_x(&box);
  const float cy = BLI_rctf_cent_y(&box);
  if (pause) {
    /* Two bars as tall as the play glyph, each ~0.3 of that wide and as far
     * apart. */
    const float half = PLAY_H * 0.5f * u;
    const float bar = PLAY_H * 0.3f * u;
    const float gap = PLAY_H * 0.3f * u;
    rctf left = {cx - gap * 0.5f - bar, cx - gap * 0.5f, cy - half, cy + half};
    rctf right = {cx + gap * 0.5f, cx + gap * 0.5f + bar, cy - half, cy + half};
    cinema_fill(left, bar * 0.3f, col);
    cinema_fill(right, bar * 0.3f, col);
    return;
  }
  const float dir = forward ? 1.0f : -1.0f;
  if (!step) {
    /* Flat edge left, apex right, the bounding box centred on the slot. */
    const float half = PLAY_H * 0.5f * u;
    const float w = PLAY_H * GLYPH_ASPECT * u;
    cinema_triangle(cx - dir * w * 0.5f, cy, dir * w, half, col);
    return;
  }
  /* Step: a smaller triangle plus a dot, the pair centred on the slot. The
   * dot sits on the side facing the play button. */
  const float sh = STEP_H * 0.5f * u; /* half height */
  const float sw = STEP_H * GLYPH_ASPECT * u;
  const float dot = DOT_D * u;
  const float gap = STEP_GAP * u;
  const float total = sw + gap + dot;
  const float outer = cx + dir * total * 0.5f; /* outer end of the pair */
  /* Triangle: flat edge on the inner side, apex at the outer end. */
  cinema_triangle(outer - dir * sw, cy, dir * sw, sh, col);
  const float dot_x0 = outer - dir * (sw + gap);
  const float dot_x1 = dot_x0 - dir * dot;
  rctf disc = {std::min(dot_x0, dot_x1), std::max(dot_x0, dot_x1), cy - dot * 0.5f, cy + dot * 0.5f};
  cinema_fill(disc, dot * 0.5f, col);
}

/** Right edge of the centred transport group, in region px. */
float transport_right_edge(const ARegion *region)
{
  const float u = cinema_unit();
  const float group_w = TRANSPORT_SIZE * 3.0f * u + TRANSPORT_GAP * 2.0f * u;
  return (float(region->winx) + group_w) * 0.5f;
}

/** Transport triple (previous / preview / next), centred on the dock. */
void draw_transport(ui::Block *block,
                    const ARegion *region,
                    const DirectorViewState &state,
                    const float cy,
                    const bool playing)
{
  const float u = cinema_unit();
  const float group_w = TRANSPORT_SIZE * 3.0f * u + TRANSPORT_GAP * 2.0f * u;
  float tx = (float(region->winx) - group_w) * 0.5f;
  const struct {
    const char *op;
    bool forward;
    bool step;
    const char *tip;
  } transport[3] = {
      {"MIXAR_OT_director_previous_beat", false, true, "Previous keyframe"},
      {"MIXAR_OT_director_preview", true, false, "Preview this shot"},
      {"MIXAR_OT_director_next_beat", true, true, "Next keyframe"},
  };
  const bool no_beats = state.beats.is_empty();
  for (int index = 0; index < 3; index++) {
    /* Every slot is the same TRANSPORT_SIZE hit box; the glyphs size
     * themselves (#transport_glyph) and only borrow the box's centre. */
    const float size = TRANSPORT_SIZE * u;
    const float slot_cx = tx + TRANSPORT_SIZE * u * 0.5f;
    const rctf box = {slot_cx - size * 0.5f, slot_cx + size * 0.5f, cy - size * 0.5f, cy + size * 0.5f};
    transport_glyph(box, transport[index].forward, transport[index].step, index == 1 && playing);
    cinema_qa_record(region, box, "director_transport", transport[index].tip, index);
    ui::Button *but = cinema_op_button(block, transport[index].op, box, transport[index].tip);
    const bool can_record = state.auto_key && state.has_camera && !state.locked;
    const bool enabled = index == 1 ? (playing ||
                                      ((can_record || state.beats.size() >= 2) &&
                                       state.frame_end > state.frame_start))
                                    : !no_beats;
    director_overlay_disable_button(but, !enabled);
    tx += (TRANSPORT_SIZE + TRANSPORT_GAP) * u;
  }
}


}  // namespace

float cinema_transport_right_edge(const ARegion *region)
{
  return transport_right_edge(region);
}

void cinema_draw_transport(ui::Block *block,
                           const ARegion *region,
                           const DirectorViewState &state,
                           const float cy,
                           const bool playing)
{
  draw_transport(block, region, state, cy, playing);
}

}  // namespace blender
