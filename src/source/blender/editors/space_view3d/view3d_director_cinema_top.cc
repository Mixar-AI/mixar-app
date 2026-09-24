/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the top strip — the Mixar banner chip above the left column,
 * keyboard hints from the camera border's left edge; on the right, flowing
 * leftwards from the stage's edge, the phone hand-off button, the
 * object-tracking eyedropper and the grid-lines toggle chip.
 *
 * Painting only; see `view3d_director_cinema_paint.cc` for the primitives.
 * The controls read the active shot's RNA and invoke Python-owned operators.
 */

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_view3d_types.h"

#include "RNA_access.hh"

#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_cinema_phone.hh"
#include "view3d_director_overlay_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/** Design y of the strip's control row (the phone button's top). */
constexpr float STRIP_Y = 159.0f;

/* Alt is Option on a Mac keyboard: name the key the user can see, as the
 * Sketch talk hint does (`scribble_mark/constants.py`). A macro rather than a
 * constant so the Walk chip's tooltip stays one string literal
 * (`ui::Button::tip` is non-owning). */
#ifdef __APPLE__
#  define WALK_SLOW_KEY "Option"
#else
#  define WALK_SLOW_KEY "Alt"
#endif

/**
 * Mixar banner chip: the brand gradient pill with the round logo chip, the
 * "mixar" wordmark, the mode name and the version. INERT — no button, no QA
 * record, no tooltip; it only names what the surface is.
 */
void brand_chip(const rctf &pill)
{
  const float u = cinema_unit();
  MIXAR_THEME_LOAD(brand_top, CinemaBrandTop);
  MIXAR_THEME_LOAD(brand_bottom, CinemaBrandBottom);
  cinema_panel(pill, CINEMA_ROW_RADIUS * u, brand_top, brand_bottom);

  const float cy = BLI_rctf_cent_y(&pill);
  const float logo_d = CINEMA_BRAND_LOGO * u;
  const rctf logo = {pill.xmin + CINEMA_BRAND_PAD * u,
                     pill.xmin + (CINEMA_BRAND_PAD + CINEMA_BRAND_LOGO) * u,
                     cy - logo_d * 0.5f,
                     cy + logo_d * 0.5f};
  MIXAR_THEME_LOAD(logo_top, CinemaPillOnA);
  MIXAR_THEME_LOAD(logo_bottom, CinemaPillOnB);
  cinema_panel(logo, logo_d * 0.5f, logo_top, logo_bottom);

  MIXAR_THEME_LOAD(value_col, CinemaRowTextOn);
  MIXAR_THEME_LOAD(label_col, CinemaLabel);
  const float wordmark_x = logo.xmax + CINEMA_BRAND_GAP * u;
  cinema_text_left("mixar", wordmark_x, cy, CINEMA_FONT_VALUE * u, value_col);
  const float mode_x = wordmark_x + cinema_text_width("mixar", CINEMA_FONT_VALUE * u) +
                       CINEMA_BRAND_GAP * u;
  /* The version is right-aligned, so the mode name is measured against where
   * it starts: at the smallest fit the two used to meet in the middle. */
  const float version_w = cinema_text_width("V1", CINEMA_FONT_LABEL * u);
  const float version_x = pill.xmax - CINEMA_BRAND_VERSION_PAD * u - version_w;
  cinema_text_left_fitted("Cinema Mode",
                          mode_x,
                          cy,
                          CINEMA_FONT_VALUE * u,
                          version_x - CINEMA_BRAND_GAP * u - mode_x,
                          label_col);
  cinema_text_left("V1", version_x, cy, CINEMA_FONT_LABEL * u, label_col);

  /* The mark last: the icon pass leaves its own blend state behind, which
   * the primitives above would otherwise inherit. Same call as the Agent
   * island's chip (`agent_ui_draw.cc`): icons draw at 16/aspect px. */
  const float mark_edge = CINEMA_BRAND_MARK * u;
  ui::icon_draw_ex(BLI_rctf_cent_x(&logo) - mark_edge * 0.5f,
                   cy - mark_edge * 0.5f,
                   ICON_MIXAR_ICON,
                   /*aspect=*/16.0f / mark_edge, /* icons draw at 16/aspect px */
                   /*alpha=*/1.0f,
                   /*desaturate=*/0.0f,
                   /*mono_color=*/nullptr,
                   /*mono_border=*/false,
                   /*text_overlay=*/nullptr);
  GPU_blend(GPU_BLEND_ALPHA);
}

/** Tracking eyedropper chip: green while a target is live. */
void track_eyedropper(ui::Block *block,
                      const ARegion *region,
                      const rctf &chip,
                      PointerRNA *shot_ptr,
                      const bool enabled)
{
  bool tracking = false;
  if (shot_ptr->data != nullptr) {
    PropertyRNA *prop = RNA_struct_find_property(shot_ptr, "track_target");
    if (prop != nullptr) {
      tracking = RNA_property_pointer_get(shot_ptr, prop).data != nullptr;
    }
  }
  if (tracking) {
    MIXAR_THEME_LOAD(on, Primary);
    cinema_fill(chip, CINEMA_ROW_RADIUS * cinema_unit(), on);
  }
  else {
    MIXAR_THEME_LOAD(top, CinemaRowTop);
    MIXAR_THEME_LOAD(bottom, CinemaRowBottom);
    cinema_panel(chip, CINEMA_ROW_RADIUS * cinema_unit(), top, bottom);
  }
  /* Both tooltips are literals: `ui::Button::tip` is non-owning. */
  ui::Button *but = cinema_icon_button(
      block,
      "MIXAR_OT_director_pick_track_target",
      ICON_EYEDROPPER,
      chip,
      tracking ? "Stop tracking the picked object" :
                 "Eyedropper: pick an object for the camera to keep pointing at");
  if (but != nullptr) {
    RNA_boolean_set(ui::button_operator_ptr_ensure(but), "clear", tracking);
    director_overlay_disable_button(but, !enabled);
  }
  cinema_qa_record(region, chip, "director_track", tracking ? "clear" : "pick", -1);
}

/**
 * Grid-lines chip: the row ramp while the grid shows, flat "off" fill while
 * hidden. Reads the region's View3D (`gridflag & V3D_SHOW_FLOOR`, a positive
 * flag — RNA `show_floor`); the operator flips floor + X/Y axes together.
 * View state, so it is never gated on the shot: it works before one exists.
 */
void grid_chip(ui::Block *block, const bContext *C, const ARegion *region, const rctf &chip)
{
  const float u = cinema_unit();
  const View3D *v3d = CTX_wm_view3d(const_cast<bContext *>(C));
  const bool shown = v3d != nullptr && (v3d->gridflag & V3D_SHOW_FLOOR) != 0;
  if (shown) {
    MIXAR_THEME_LOAD(top, CinemaRowTop);
    MIXAR_THEME_LOAD(bottom, CinemaRowBottom);
    cinema_panel(chip, CINEMA_ROW_RADIUS * u, top, bottom);
  }
  else {
    MIXAR_THEME_LOAD(off, CinemaPhone);
    cinema_fill(chip, CINEMA_ROW_RADIUS * u, off);
  }
  /* Both tooltips are literals: `ui::Button::tip` is non-owning. */
  cinema_icon_button(block,
                     "MIXAR_OT_director_toggle_grid",
                     ICON_GRID,
                     chip,
                     shown ? "Hide grid lines" : "Show grid lines");
  cinema_qa_record(region, chip, "director_grid", shown ? "hide" : "show", -1);
}

/**
 * Walk chip: starts and stops the Cinema walk, lit while one is running.
 *
 * The ONLY way in, and on purpose: both keys that fitted were already
 * somebody else's (`director/ui/keymap.py` records which). And the only way
 * OUT: Esc and the right button used to stop the walk too, so the chip was
 * one of three switches for one state. Now its lit state is the whole truth.
 *
 * It is a TOGGLE. It always looked like one — lit while walking, publishing
 * "stop" to the harness — and for a while it was not one: the walk owned
 * every event in the window, so the chip could not be clicked while lit and
 * nobody found out. Once the walk stopped swallowing events
 * (`director_pointer_on_stage`), a second click started a SECOND walk on top
 * of the first. `MIXAR_OT_director_navigate` now asks the running walk to
 * finish instead (`walk_stop_requested`).
 *
 * The glyph is Blender's camera-view camera (`ICON_VIEW_CAMERA`): what the
 * chip drives is the shot camera, seen through. It was the pan hand, which
 * names the viewport's own Move, and then a walking figure, which read as
 * the armature it is. The compact rail's Camera button carries the same
 * glyph, but the rail only draws when this strip does not, so the two never
 * share a screen.
 */
void walk_chip(ui::Block *block,
               const ARegion *region,
               const rctf &chip,
               const bool walking)
{
  const float u = cinema_unit();
  if (walking) {
    MIXAR_THEME_LOAD(on, Primary);
    cinema_fill(chip, CINEMA_ROW_RADIUS * u, on);
  }
  else {
    MIXAR_THEME_LOAD(top, CinemaRowTop);
    MIXAR_THEME_LOAD(bottom, CinemaRowBottom);
    cinema_panel(chip, CINEMA_ROW_RADIUS * u, top, bottom);
  }
  /* Both tooltips are literals: `ui::Button::tip` is non-owning. */
  cinema_icon_button(block,
                     "MIXAR_OT_director_navigate",
                     ICON_VIEW_CAMERA,
                     chip,
                     walking ? "Stop walking" :
                               "Walk the camera: W A S D, Q E, Shift to sprint, " WALK_SLOW_KEY
                               " to creep, hold the left button to look. Click again to stop");
  cinema_qa_record(region, chip, "director_walk", walking ? "stop" : "start", -1);
}

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Top strip
 * \{ */

void cinema_draw_top_strip(ui::Block *block,
                           const bContext *C,
                           const ARegion *region,
                           const DirectorViewState &state)
{
  const float u = cinema_unit();
  const bool editable = state.has_shot && !state.locked;

  /* Shortcut hints, and the surface has TWO sets because Cinema Mode has two
   * states. At rest the camera keys do nothing — W/A/S/D/Q/E are absorbed,
   * not bound to a nudge — so the strip advertises only what is live:
   * O -> `mixar.director_aerial` (the top-down view; its label lights while
   * the mode is on) and I -> `mixar.director_capture_beat`. Walking has no
   * shortcut at all — it is the Walk chip below, because both keys that
   * fitted were already somebody else's (see `director/ui/keymap.py`) — so
   * at rest there is nothing else to promise. While a walk runs, the keys
   * are the Cinema walk's and the strip says so, down to the left button
   * that aims and Shift / Alt for the sprint and the creep. There is no key
   * that stops it: the Walk chip, lit beside these hints, is the way out.
   *
   * A hint here is a promise — never paint one without the matching keymap
   * item, in whichever state paints it. */
  struct Hint {
    float x;
    const char *keys[4];
    int key_count;
    const char *label;
    bool stacked; /* WASD draws W above ASD. */
  };
  constexpr int RESTING_HINTS = 2;
  constexpr int WALKING_HINTS = 4;
  const Hint resting_hints[RESTING_HINTS] = {
      {0.0f, {"O"}, 1, "Aerial view", false},
      {0.0f, {"I"}, 1, "Insert keyframe", false},
  };
  /* Most useful first: a row too narrow for all of them drops from the END,
   * so the speed modifiers — refinements — are what give way first. */
  const Hint walking_hints[WALKING_HINTS] = {
      {0.0f, {"W", "A", "S", "D"}, 4, "Move around", true},
      {0.0f, {"Q", "E"}, 2, "Up / down", false},
      {0.0f, {"LMB"}, 1, "Hold to look", false},
      {0.0f, {"Shift", WALK_SLOW_KEY}, 2, "Faster / slower", false},
  };
  /* Groups pack at CINEMA_HINT_GAP from the row's left edge. `x` is resolved
   * here from the measured label widths, once the row's span is known. */
  const Hint *source = state.walking ? walking_hints : resting_hints;
  const int hint_count = state.walking ? WALKING_HINTS : RESTING_HINTS;
  Hint hints[WALKING_HINTS] = {};
  for (int index = 0; index < hint_count; index++) {
    hints[index] = source[index];
  }

  /* One group's caps, in DESIGN px. A cap sizes itself to its label, so a
   * word ("Shift") is wider than a glyph and the packing has to ask. */
  auto caps_design_w = [&](const Hint &hint) {
    float width = 0.0f;
    /* W sits ABOVE A S D, so a stacked group is only as wide as its bottom
     * row. The gap goes BETWEEN caps, never after the last one — trailing it
     * made every group measure 2 design px wider than it draws. */
    const int first = hint.stacked ? 1 : 0;
    for (int key = first; key < hint.key_count; key++) {
      if (key > first) {
        width += 2.0f;
      }
      width += cinema_keycap_width(hint.keys[key]) / u;
    }
    return width;
  };
  const float margin = cinema_margin(region);
  /* Each group's width, and what the whole row needs: the hints, the 12 px
   * they keep clear of the chips, and the three chips (walk, grid, eyedropper)
   * with the two gaps between them. Design px. */
  float hint_w[WALKING_HINTS];
  float row_need = 12.0f + CINEMA_PHONE_H * 3.0f + CINEMA_STRIP_GAP * 2.0f;
  for (int index = 0; index < hint_count; index++) {
    hint_w[index] = caps_design_w(hints[index]) + 8.0f +
                    cinema_text_width(hints[index].label, CINEMA_FONT_LABEL * u) / u;
    row_need += hint_w[index] + (index > 0 ? CINEMA_HINT_GAP : 0.0f);
  }
  /* The row's span, in design px. Hints start on its left edge and the chips
   * end on its right, so on a wide frame they line up with the camera border.
   *
   * It used to BE the border, and the border is the ASPECT's width: a 9:16
   * frame is far narrower than the row, so every hint group was dropped and
   * the strip went blank. So the border is where the row starts from, not
   * what bounds it — when the frame is too narrow, the row widens evenly
   * about the frame's centre. It never runs past the STAGE (the space between
   * the columns: the banner chip and the phone button sit beyond it), which
   * is also the whole span outside camera view. */
  const float stage_inset = margin + CINEMA_PANEL_W + CINEMA_STAGE_INSET + CINEMA_GATE_PAD;
  const float stage_left = stage_inset;
  const float stage_right = float(region->winx) / u - stage_inset;
  float row_left = stage_left;
  float row_right = stage_right;
  rctf border;
  if (cinema_camera_gate_rect(C, region, &border)) {
    row_left = border.xmin / u;
    row_right = border.xmax / u;
    const float missing = row_need - (row_right - row_left);
    if (missing > 0.0f) {
      row_left -= missing * 0.5f;
      row_right += missing * 0.5f;
    }
    row_left = std::max(row_left, stage_left);
    row_right = std::min(row_right, stage_right);
  }
  /* Design x where each hint ends; the controls decide what fits from it. */
  float hint_end[WALKING_HINTS];
  float next_x = row_left;
  for (int index = 0; index < hint_count; index++) {
    Hint &hint = hints[index];
    hint.x = next_x;
    hint_end[index] = hint.x + hint_w[index];
    next_x = hint_end[index] + CINEMA_HINT_GAP;
  }

  const rctf band = cinema_design_rect(region, 0.0f, STRIP_Y, 0.0f, CINEMA_PHONE_H);

  /* Mixar banner chip above the left column, the column's full width, on
   * the same band as the strip's controls. Only the wide surface calls this
   * painter, so the compact rail never shows it. */
  brand_chip(cinema_design_rect(region, margin, STRIP_Y, CINEMA_PANEL_W, CINEMA_PHONE_H));

  /* Phone hand-off above the right column, the column's full width. The
   * button itself decides its label, its state colour and whether the label
   * still fits (`view3d_director_cinema_phone.cc`). */
  const rctf phone = {float(region->winx) - (margin + CINEMA_PANEL_W) * u,
                      float(region->winx) - margin * u,
                      band.ymin,
                      band.ymax};
  /* Walk chip, grid chip and eyedropper, right-to-left from the row's right
   * edge, so on a wide frame the last chip's edge lines up with the frame.
   *
   * The Interpolation dropdown used to sit out here too. It is how the camera
   * eases BETWEEN KEYFRAMES, and it now lives in the timeline dock beside the
   * keyframes it describes (`view3d_director_cinema_dock.cc`). */
  const float strip_right = row_right * u;
  rctf eyedrop = {strip_right - CINEMA_PHONE_H * u, strip_right, band.ymin, band.ymax};
  rctf grid = {eyedrop.xmin - (CINEMA_STRIP_GAP + CINEMA_PHONE_H) * u,
               eyedrop.xmin - CINEMA_STRIP_GAP * u,
               band.ymin,
               band.ymax};
  rctf walk = {grid.xmin - (CINEMA_STRIP_GAP + CINEMA_PHONE_H) * u,
               grid.xmin - CINEMA_STRIP_GAP * u,
               band.ymin,
               band.ymax};
  const float controls_left = walk.xmin;

  MIXAR_THEME_LOAD(hint_col, CinemaLabel);
  MIXAR_THEME_LOAD(hint_lit, CinemaRowTextOn);
  for (int index = 0; index < hint_count; index++) {
    const Hint &hint = hints[index];
    /* The Aerial hint (resting index 0) reads as a state: lit while the mode
     * is on. There is no Aerial hint while walking. */
    const bool lit = !state.walking && index == 0 && state.aerial_mode;
    /* A hint clipped in half, or run under a control, reads as a rendering
     * bug; drop the whole group — and every group after it, since they are
     * laid out left to right and none of them can fit either. */
    if (hint_end[index] * u + 12.0f * u > std::min(controls_left, float(region->winx))) {
      break;
    }
    float x = hint.x * u;
    /* Keycaps centre on the control band; W stacks one cap above. */
    const float row_y = cinema_design_rect(region, 0.0f, STRIP_Y + (CINEMA_PHONE_H - CINEMA_KEYCAP_H) * 0.5f, 0.0f, CINEMA_KEYCAP_H).ymin;
    if (hint.stacked) {
      /* W sits above the middle of A S D, as in the design — but never above
       * the region: the stacked cap clears the band by more than the band's
       * own top margin, so on a short viewport it would be drawn off screen
       * and the group would read as "ASD". */
      const float stacked_y = row_y + (CINEMA_KEYCAP_H + 2.0f) * u;
      if (stacked_y + CINEMA_KEYCAP_H * u <= float(region->winy)) {
        cinema_keycap(x + (CINEMA_KEYCAP_W + 2.0f) * u, stacked_y, hint.keys[0]);
      }
    }
    for (int key = hint.stacked ? 1 : 0; key < hint.key_count; key++) {
      x += cinema_keycap(x, row_y, hint.keys[key]) + 2.0f * u;
    }
    cinema_text_left(hint.label,
                     x + 8.0f * u,
                     row_y + CINEMA_KEYCAP_H * u * 0.5f,
                     CINEMA_FONT_LABEL * u,
                     lit ? hint_lit : hint_col);
  }

  PointerRNA shot_ptr = {};
  view3d_director_active_shot_pointer(CTX_data_scene(const_cast<bContext *>(C)), &shot_ptr);

  /* Each chip is dropped on its OWN edge, not on the leftmost one's: they
   * were gated together, so a stage too narrow for the walk chip took the
   * grid chip and the eyedropper with it even though both still fitted. */
  if (eyedrop.xmin > 0.0f) {
    track_eyedropper(block, region, eyedrop, &shot_ptr, editable);
  }
  if (grid.xmin > 0.0f) {
    grid_chip(block, C, region, grid);
  }
  if (walk.xmin > 0.0f) {
    walk_chip(block, region, walk, state.walking);
  }
  /* Phone hand-off. Live: it starts the Virtual Camera's pairing server and
   * hands the camera back when one is already driving. */
  cinema_draw_phone_button(block, C, region, phone);
}

/** \} */

}  // namespace blender
