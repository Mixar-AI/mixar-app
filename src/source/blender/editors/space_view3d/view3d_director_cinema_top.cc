/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the top strip — the Mixar banner chip above the left column,
 * keyboard hints from the camera border's left edge; on the right, flowing
 * leftwards from the stage's edge, the phone hand-off button, the keyframe
 * interpolation dropdown, the object-tracking eyedropper and the grid-lines
 * toggle chip.
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
#include "view3d_director_overlay_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/** Design y of the strip's control row (the phone button's top). */
constexpr float STRIP_Y = 159.0f;

/**
 * Mixar banner chip: the brand gradient pill with the round logo chip, the
 * "mixar" wordmark, the mode name and the version. INERT — no button, no QA
 * record, no tooltip; it only names what the surface is.
 */
void brand_chip(const rctf &pill)
{
  const float u = cinema_unit();
  const float brand_top[4] = CINEMA_COL_BRAND_TOP;
  const float brand_bottom[4] = CINEMA_COL_BRAND_BOTTOM;
  cinema_panel(pill, CINEMA_ROW_RADIUS * u, brand_top, brand_bottom);

  const float cy = BLI_rctf_cent_y(&pill);
  const float logo_d = CINEMA_BRAND_LOGO * u;
  const rctf logo = {pill.xmin + CINEMA_BRAND_PAD * u,
                     pill.xmin + (CINEMA_BRAND_PAD + CINEMA_BRAND_LOGO) * u,
                     cy - logo_d * 0.5f,
                     cy + logo_d * 0.5f};
  const float logo_top[4] = CINEMA_COL_LOGO_TOP;
  const float logo_bottom[4] = CINEMA_COL_LOGO_BOTTOM;
  cinema_panel(logo, logo_d * 0.5f, logo_top, logo_bottom);

  const float value_col[4] = CINEMA_COL_VALUE;
  const float label_col[4] = CINEMA_COL_LABEL;
  const float wordmark_x = logo.xmax + CINEMA_BRAND_GAP * u;
  cinema_text_left("mixar", wordmark_x, cy, CINEMA_FONT_VALUE * u, value_col);
  const float mode_x = wordmark_x + cinema_text_width("mixar", CINEMA_FONT_VALUE * u) +
                       CINEMA_BRAND_GAP * u;
  cinema_text_left("Cinema Mode", mode_x, cy, CINEMA_FONT_VALUE * u, label_col);
  cinema_text_right(
      "V1", pill.xmax - CINEMA_BRAND_VERSION_PAD * u, cy, CINEMA_FONT_LABEL * u, label_col);

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

/** Phone glyph + label, centred as a pair; glyph only when \a compact. */
void phone_button(const rctf &rect, const bool compact)
{
  const float u = cinema_unit();
  const float phone_bg[4] = CINEMA_COL_PHONE;
  const float phone_text[4] = {0.957f, 0.957f, 0.957f, 0.9f};
  cinema_fill(rect, CINEMA_ROW_RADIUS * u, phone_bg);
  const char *label = "Drive camera from your phone";
  const float glyph_w = 11.0f * u;
  const float glyph_gap = 9.0f * u;
  const float label_w = compact ? 0.0f : cinema_text_width(label, CINEMA_FONT_VALUE * u);
  const float pair_w = compact ? glyph_w : glyph_w + glyph_gap + label_w;
  const float x0 = BLI_rctf_cent_x(&rect) - pair_w * 0.5f;
  const float cy = BLI_rctf_cent_y(&rect);
  /* A phone outline: rounded body with a short speaker line. */
  const rctf body = {x0, x0 + glyph_w, cy - 8.0f * u, cy + 8.0f * u};
  cinema_outline(body, 3.0f * u, phone_text, std::max(1.0f, 1.2f * u));
  const rctf speaker = {x0 + glyph_w * 0.3f, x0 + glyph_w * 0.7f, cy + 4.5f * u, cy + 5.5f * u};
  cinema_fill(speaker, 0.5f * u, phone_text);
  if (!compact) {
    cinema_text_left(label, x0 + glyph_w + glyph_gap, cy, CINEMA_FONT_VALUE * u, phone_text);
  }
}

/** Interpolation dropdown: graded row, the current type's name, chevron. */
void interpolation_dropdown(ui::Block *block,
                            const bContext *C,
                            const ARegion *region,
                            const rctf &row,
                            PointerRNA *shot_ptr,
                            const bool enabled)
{
  const float u = cinema_unit();
  const float top[4] = CINEMA_COL_ROW_TOP;
  const float bottom[4] = CINEMA_COL_ROW_BOTTOM;
  const float value_col[4] = CINEMA_COL_VALUE;
  const float chevron[4] = {0.851f, 0.851f, 0.851f, 1.0f};
  cinema_panel(row, CINEMA_ROW_RADIUS * u, top, bottom);

  const char *name = "Bezier";
  const char *identifier = "BEZIER";
  PropertyRNA *prop = shot_ptr->data ? RNA_struct_find_property(shot_ptr, "interpolation") :
                                       nullptr;
  if (prop != nullptr) {
    const int value = RNA_property_enum_get(shot_ptr, prop);
    const char *found = nullptr;
    if (RNA_property_enum_name(const_cast<bContext *>(C), shot_ptr, prop, value, &found) &&
        found != nullptr)
    {
      name = found;
    }
    if (RNA_property_enum_identifier(const_cast<bContext *>(C), shot_ptr, prop, value, &found) &&
        found != nullptr)
    {
      identifier = found;
    }
  }
  cinema_text_left(name, row.xmin + 12.0f * u, BLI_rctf_cent_y(&row), CINEMA_FONT_VALUE * u, value_col);
  cinema_chevron(row.xmax - 18.0f * u, BLI_rctf_cent_y(&row), 9.0f * u, chevron);

  ui::Button *but = cinema_popup_button(block,
                                        view3d_director_interpolation_popup_create,
                                        row,
                                        "Interpolation: how the camera eases between keyframes",
                                        CinemaPopupSlot::Strip);
  director_overlay_disable_button(but, !enabled);
  cinema_qa_record(region, row, "director_interpolation", identifier, -1);
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
    const float on[4] = CINEMA_COL_EXPORT;
    cinema_fill(chip, CINEMA_ROW_RADIUS * cinema_unit(), on);
  }
  else {
    const float top[4] = CINEMA_COL_ROW_TOP;
    const float bottom[4] = CINEMA_COL_ROW_BOTTOM;
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
    const float top[4] = CINEMA_COL_ROW_TOP;
    const float bottom[4] = CINEMA_COL_ROW_BOTTOM;
    cinema_panel(chip, CINEMA_ROW_RADIUS * u, top, bottom);
  }
  else {
    const float off[4] = CINEMA_COL_PHONE;
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

  /* Shortcut hints. The keys are what the Director keymap actually binds
   * (`director/ui/keymap.py`): O -> `mixar.director_navigate`, F -> capture
   * (a design label of "I" would be a lie about a live binding), WASD/QE ->
   * `mixar.director_nudge_camera`. A hint here is a promise — never paint one
   * without the matching keymap item. */
  struct Hint {
    float x;
    const char *keys[4];
    int key_count;
    const char *label;
    bool stacked; /* WASD draws W above ASD. */
  };
  /* Groups pack at CINEMA_HINT_GAP from the camera gate's left edge (the
   * stage inset by the gate's pad), so the hints line up with the frame and
   * clear the banner chip above the left column. `x` is resolved here from
   * the measured label widths. */
  Hint hints[] = {
      {0.0f, {"O"}, 1, "Navigate", false},
      {0.0f, {"F"}, 1, "Insert keyframe", false},
      {0.0f, {"W", "A", "S", "D"}, 4, "Move around", true},
      {0.0f, {"Q", "E"}, 2, "Z-axis", false},
  };
  const float margin = cinema_margin(region);
  /* The fitted camera border's left edge, in design px. The border can be
   * height-limited and sit inside the stage, so read the real one; the
   * stage's own gate edge is only the fallback outside camera view. */
  float gate_left = margin + CINEMA_PANEL_W + CINEMA_STAGE_INSET + CINEMA_GATE_PAD;
  float gate_right = float(region->winx) / u - (margin + CINEMA_PANEL_W + CINEMA_STAGE_INSET +
                                                 CINEMA_GATE_PAD);
  rctf border;
  if (cinema_camera_gate_rect(C, region, &border)) {
    gate_left = border.xmin / u;
    gate_right = border.xmax / u;
  }
  /* Design x where each hint ends; the controls decide what fits from it. */
  float hint_end[4];
  float next_x = gate_left;
  for (int index = 0; index < 4; index++) {
    Hint &hint = hints[index];
    hint.x = next_x;
    hint_end[index] = hint.x +
                      float(hint.stacked ? 3 : hint.key_count) * (CINEMA_KEYCAP_W + 2.0f) + 8.0f +
                      cinema_text_width(hint.label, CINEMA_FONT_LABEL * u) / u;
    next_x = hint_end[index] + CINEMA_HINT_GAP;
  }

  const rctf band = cinema_design_rect(region, 0.0f, STRIP_Y, 0.0f, CINEMA_PHONE_H);

  /* Mixar banner chip above the left column, the column's full width, on
   * the same band as the strip's controls. Only the wide surface calls this
   * painter, so the compact rail never shows it. */
  brand_chip(cinema_design_rect(region, margin, STRIP_Y, CINEMA_PANEL_W, CINEMA_PHONE_H));

  /* Phone hand-off above the right column, the column's full width; the
   * label gives way to the glyph only if the column cannot hold it. */
  const rctf phone = {float(region->winx) - (margin + CINEMA_PANEL_W) * u,
                      float(region->winx) - margin * u,
                      band.ymin,
                      band.ymax};
  const float phone_need = cinema_text_width("Drive camera from your phone", CINEMA_FONT_VALUE * u) +
                           (11.0f + 9.0f + 32.0f) * u;
  const bool phone_full = phone_need <= BLI_rctf_size_x(&phone);

  /* Grid chip, eyedropper and interpolation dropdown, right-to-left from
   * the camera frame's right edge, so the dropdown's edge lines up with the
   * frame. */
  const float strip_right = gate_right * u;
  rctf interp = {strip_right - CINEMA_INTERP_W * u, strip_right, band.ymin, band.ymax};
  rctf eyedrop = {interp.xmin - (CINEMA_STRIP_GAP + CINEMA_PHONE_H) * u,
                  interp.xmin - CINEMA_STRIP_GAP * u,
                  band.ymin,
                  band.ymax};
  rctf grid = {eyedrop.xmin - (CINEMA_STRIP_GAP + CINEMA_PHONE_H) * u,
               eyedrop.xmin - CINEMA_STRIP_GAP * u,
               band.ymin,
               band.ymax};
  const float controls_left = grid.xmin;

  const float hint_col[4] = CINEMA_COL_LABEL;
  for (int index = 0; index < 4; index++) {
    const Hint &hint = hints[index];
    /* A hint clipped in half, or run under a control, reads as a rendering
     * bug; drop the whole group. */
    if (hint_end[index] * u + 12.0f * u > std::min(controls_left, float(region->winx))) {
      continue;
    }
    float x = hint.x * u;
    /* Keycaps centre on the control band; W stacks one cap above. */
    const float row_y = cinema_design_rect(region, 0.0f, STRIP_Y + (CINEMA_PHONE_H - CINEMA_KEYCAP_H) * 0.5f, 0.0f, CINEMA_KEYCAP_H).ymin;
    if (hint.stacked) {
      /* W sits above the middle of A S D, as in the design. */
      cinema_keycap(x + (CINEMA_KEYCAP_W + 2.0f) * u,
                    row_y + (CINEMA_KEYCAP_H + 2.0f) * u,
                    "W");
      for (int key = 1; key < hint.key_count; key++) {
        cinema_keycap(x, row_y, hint.keys[key]);
        x += (CINEMA_KEYCAP_W + 2.0f) * u;
      }
    }
    else {
      for (int key = 0; key < hint.key_count; key++) {
        cinema_keycap(x, row_y, hint.keys[key]);
        x += (CINEMA_KEYCAP_W + 2.0f) * u;
      }
    }
    cinema_text_left(hint.label,
                     x + 8.0f * u,
                     row_y + CINEMA_KEYCAP_H * u * 0.5f,
                     CINEMA_FONT_LABEL * u,
                     hint_col);
  }

  PointerRNA shot_ptr = {};
  view3d_director_active_shot_pointer(CTX_data_scene(const_cast<bContext *>(C)), &shot_ptr);

  if (grid.xmin > 0.0f) {
    grid_chip(block, C, region, grid);
    track_eyedropper(block, region, eyedrop, &shot_ptr, editable);
    interpolation_dropdown(block, C, region, interp, &shot_ptr, editable);
  }
  /* Phone hand-off. Painted per the design but INERT: nothing on the backend
   * (checked `origin/develop`) drives a camera from a phone, and a button
   * that silently does nothing is worse than one that says so. */
  phone_button(phone, !phone_full);
  UNUSED_VARS(block);
}

/** \} */

}  // namespace blender
