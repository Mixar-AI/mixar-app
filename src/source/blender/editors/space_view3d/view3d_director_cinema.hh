/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode surface — the designed Director shell.
 *
 * Geometry and colour are measured from the design export (Frame
 * 1533210241.svg, a 1798x1079 window mock) and kept here in DESIGN UNITS:
 * every painter multiplies by #cinema_unit(), so one constant per token and
 * one scale rule for the whole surface.
 *
 * The contract from the old overlay still holds: this layer only READS
 * Director RNA and INVOKES the Python-owned `mixar.director_*` operators.
 * Nothing here decides behaviour.
 */

#pragma once

#include <string>
#include <vector>
#include "DNA_vec_types.h"

/* `ui::BlockCreateFunc` (below, #cinema_popup_button) is a type ALIAS, so it
 * cannot be forward-declared the way `ui::Block` and `ui::Button` are. This
 * header carried neither the include nor the alias and worked only because
 * every file that used it happened to include `UI_interface_c.hh` first; the
 * one that did not failed to compile with "'BlockCreateFunc': is not a member
 * of 'blender::ui'". A header pays for the names it uses. */
#include "UI_interface_c.hh"
/* Geometry and palette; see that file for why they are separate. */
#include "view3d_director_cinema_tokens.hh"
#include "UI_mixar_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct PointerRNA;
struct bContext;

namespace ui {
struct Block;
struct Button;
}
struct DirectorViewState;

/* -------------------------------------------------------------------- */
/** \name Shared painters (view3d_director_cinema_paint.cc)
 * \{ */

/**
 * Design px -> region px. One scale rule for the whole surface.
 *
 * Set per draw by #cinema_unit_begin from the VIEWPORT region: UI scale times
 * the fit that lets the whole design sit inside that region (never above 1).
 * The dock's draw passes the viewport region too, so both regions agree.
 */
float cinema_unit();

/** Resolve the unit for this draw. Call first, before any painter. */
void cinema_unit_begin(const ARegion *main_region);

/**
 * How much of the 1x design fits \a region: `min(1, width fit, height fit)`
 * over the columns-plus-gate width and the lowest content's height. The
 * panels never grow past 1x; on a big screen only the camera gate does.
 */
float cinema_fit_scale(const ARegion *region);

/**
 * Side margin in design px for \a region.
 *
 * The design is a full-bleed 1798px window; a viewport sharing the screen
 * with another editor is narrower, so the two columns keep their measured
 * width and give up margin down to a floor rather than overlapping the gate.
 */
float cinema_margin(const ARegion *region);

/** Whether the region can host the designed surface: its fit is at least #CINEMA_SCALE_MIN. */
bool cinema_surface_fits(const ARegion *region);

/** Design y (window coords) of the lowest content in either column. */
float cinema_content_bottom();

/**
 * The stage rect in region px: the design's rounded frame between the two
 * columns, top-aligned with them and ending at the lowest content. Resolves
 * the unit for \a region itself. False when the designed surface is not what
 * this region draws (Director inactive, or below the fit floor) — callers such
 * as the navigation gizmo then keep their stock placement.
 */
bool cinema_stage_rect(const bContext *C, const ARegion *region, rctf *r_rect);
/**
 * Whether a region-space point lands on one of the two COLUMNS of cards.
 *
 * The complement of #cinema_stage_rect over the columns' own band. The
 * surface paints and never hit-tests, so this is what lets a wheel over a
 * painted card be absorbed instead of reaching the viewport behind it.
 * False below #CINEMA_SCALE_MIN, where the compact rail is drawn instead.
 */
bool cinema_columns_contain(const bContext *C, const ARegion *region, int x, int y);

/** Height of one list row, in design px. Kept under #CINEMA_LIST_PITCH by
 * #CINEMA_LIST_GAP: rows advance by the pitch, and a taller row overlaps its
 * neighbour — the overlapping button is created LAST and
 * `ui_but_find_mouse_over_ex` walks a block backwards, so the bottom band of
 * every row would activate the entry BELOW it, and #cinema_qa_record would
 * publish that same wrong rect. */
float cinema_list_row_h();

/** First row to draw so \a active stays visible in a #CINEMA_LIST_MAX_ROWS window. */
int cinema_list_window_start(int count, int active);

/** Rect from the design's WINDOW coordinates, anchored to the region's top.
 * The design mock includes the app chrome, so #CINEMA_VIEWPORT_TOP is the
 * design y at which the viewport region begins. */
rctf cinema_design_rect(const ARegion *region, float x, float y, float w, float h);

/** Vertically graded rounded panel — rows, tracks and chips stay flat. */
void cinema_panel(const rctf &rect, float radius, const float top[4], const float bottom[4]);

/** Floating card / dock bed: the shared CARD pane, same on macOS and Windows. */
void cinema_glass_panel(const rctf &rect, float radius);

/** Flat rounded fill. */
void cinema_fill(const rctf &rect, float radius, const float color[4]);

/** Rounded outline only. */
void cinema_outline(const rctf &rect, float radius, const float color[4], float width);

void cinema_text_left(const char *text, float x, float center_y, float size, const float col[4]);
void cinema_text_center(const char *text, float cx, float center_y, float size, const float col[4]);
void cinema_text_right(const char *text, float right, float cy, float size, const float col[4]);
float cinema_text_width(const char *text, float size);

/** Same, ellipsised to \a max_width. The surface paints into fixed cards and
 * nothing else measures, so a long camera name or focus-object name ran out
 * of its row and off the card. */
void cinema_text_left_fitted(
    const char *text, float x, float center_y, float size, float max_width, const float col[4]);
void cinema_text_center_fitted(
    const char *text, float cx, float center_y, float size, float max_width, const float col[4]);

/** Down chevron used by every dropdown row. */
void cinema_chevron(float cx, float cy, float size, const float col[4]);

/**
 * Triangle with its flat edge at \a x and its apex at `x + dx`, so a negative
 * \a dx points left. Used for the transport glyphs.
 */
void cinema_triangle(float x, float cy, float dx, float half_h, const float col[4]);

/** Keycap glyph (19x21 rounded chip with a centred letter). */
/** Returns the width drawn: a square cap for one glyph, fitted for a word. */
float cinema_keycap(float x, float y, const char *letter);

/** The width #cinema_keycap would draw for \a label, without drawing it. */
float cinema_keycap_width(const char *label);

/**
 * Discrete tick meter, `filled` of `count` lit on the design's green ramp.
 * The bar is the Speed control's whole visual — the live slider sits over it.
 */
void cinema_tick_meter(const rctf &rect, int count, int filled);


/** Packed still preview, aspect-fitted and rounded. Silent when unavailable. */
void cinema_image_preview(struct Image *image, const rctf &rect, float radius);

/* -------------------------------------------------------------------- */
/** \name QA targets
 *
 * The surface's controls are uiButs, so the QA harness already sees their
 * rects — but several rows share one operator id and nothing distinguishes
 * them. Each row therefore records the SAME rect it lays its button over
 * (never a re-derived one) under a surface name and a value, which
 * `view3d_director_qa_targets.cc` publishes.
 * \{ */

struct CinemaQARecord {
  const ARegion *region = nullptr;
  rctf rect = {};
  std::string surface;
  std::string value;
  int index = -1;
};

/** Drop \a region's records; called once at the top of its draw. */
void cinema_qa_begin(const ARegion *region);

void cinema_qa_record(
    const ARegion *region, const rctf &rect, const char *surface, const char *value, int index);

const std::vector<CinemaQARecord> &cinema_qa_records();

/** \} */

/** Invisible hit area over painted chrome; every one drives an operator. */
ui::Button *cinema_op_button(ui::Block *block,
                        const char *operator_id,
                        const rctf &rect,
                        const char *tooltip);

/** Which bar a popup opens from: its rows take that bar's width
 * (#director_popup_width), and one slot per bar class keeps the pointer
 * handed to the popup stable. */
enum class CinemaPopupSlot : int { Row = 0, Strip = 1, Export = 2, Count };

/**
 * Same, but opening a native block popup (the existing Director popups). The
 * popup receives \a rect's width through its create arg, via \a slot.
 */
ui::Button *cinema_popup_button(ui::Block *block,
                           ui::BlockCreateFunc block_func,
                           const rctf &rect,
                           const char *tooltip,
                           CinemaPopupSlot slot);

/** Invisible click CATCHER, no operator. An opaque card the surface paints
 * has to swallow presses on its own background, or they reach whatever
 * keymap item is polling the pixels behind it. */
ui::Button *cinema_blocker(ui::Block *block, const rctf &rect, const char *tooltip);

/** Icon-only operator button over painted chrome (the icon is the label). */
ui::Button *cinema_icon_button(ui::Block *block,
                               const char *operator_id,
                               int icon,
                               const rctf &rect,
                               const char *tooltip);

/**
 * Icon-only RNA boolean over painted chrome: the button IS the property, so
 * any other button bound to it anywhere in Blender is the same switch (the
 * dock's Auto Key and the Timeline's record button). A plain Toggle, not an
 * IconToggle, so \a icon is drawn as given and the caller picks the glyph
 * from the state it paints.
 */
ui::Button *cinema_prop_toggle(ui::Block *block,
                               PointerRNA *ptr,
                               const char *prop_name,
                               int icon,
                               const rctf &rect,
                               const char *tooltip);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Surface sections
 * \{ */

/**
 * Fit the camera gate to the stage: while the designed surface draws in
 * camera view, the camera border spans the width between the columns with
 * its top on the columns' top; its foot is free down to the chat bar (the
 * gate IS the frame — nothing is drawn around it). Writes `rv3d->camzoom`
 * and `camdx/camdy` only when the region size, the stage rect or the camera
 * changed since the last fit, so a director's own zoom and pan survive
 * until the layout moves.
 */
void cinema_fit_camera_gate(const bContext *C, ARegion *region);

/**
 * Hand the resting Agent pill back its ordinary seat: called on every draw
 * that does not show the designed surface (Director off, compact rail).
 * Cheap when nothing changed.
 */
void cinema_release_chat_seat(const bContext *C);

/**
 * The camera border as currently drawn (region px), after the fit. False
 * outside camera view; callers then fall back to the stage's gate edge.
 */
bool cinema_camera_gate_rect(const bContext *C, const ARegion *region, rctf *r_rect);

/** Shortcut hints; tracking eyedropper, interpolation dropdown, phone button. */
void cinema_draw_top_strip(ui::Block *block,
                           const bContext *C,
                           const ARegion *region,
                           const DirectorViewState &state);

/** Settings card, template styles, speed. */
void cinema_draw_left_panel(ui::Block *block,
                            const bContext *C,
                            const ARegion *region,
                            const DirectorViewState &state);

/** Drop \a region's remembered gate fit. Keyed on the raw pointer, so a
 * record that outlives its region would answer for whatever is allocated at
 * that address next — and suppress the refit that region needs. */
void cinema_gate_release(const ARegion *region);

/** Timeline dock: the panel behind the control row and ruler. */
void cinema_draw_dock_panel(const ARegion *region);

/** The dock's Ruler title and unit switch; returns the next group's x. */
float cinema_draw_ruler_group(
    ui::Block *block, const bContext *C, const ARegion *region, float start_x, float cy);

/** Timeline dock, wide layout: the control row and the actions row. */
void cinema_draw_dock_controls(ui::Block *block,
                               const bContext *C,
                               const ARegion *region,
                               const DirectorViewState &state,
                               bool playing);

/** Timeline dock, compact layout: the transport alone. Drawn instead of
 * #cinema_draw_dock_controls below the wide-surface gate, where the old rail
 * owns the chrome. */
void cinema_draw_dock_compact(ui::Block *block,
                              const ARegion *region,
                              const DirectorViewState &state,
                              bool playing);

/** Timeline dock: the centred transport (`_dock_transport.cc`). Both dock
 * layouts draw it — it exists nowhere else — and the other groups keep clear
 * of it by asking for its right edge, since it is load-bearing. */
void cinema_draw_transport(ui::Block *block,
                           const ARegion *region,
                           const DirectorViewState &state,
                           float cy,
                           bool playing);

/** Right edge of the centred transport group, in region px. */
float cinema_transport_right_edge(const ARegion *region);

/** Timeline dock, actions row (`_dock_actions.cc`): Auto Key and Add
 * Keyframe, centred as a group under the transport on \a cy. */
void cinema_draw_dock_actions(ui::Block *block,
                              const bContext *C,
                              const ARegion *region,
                              const DirectorViewState &state,
                              float cy);

/** Height the dock's controls occupy, in region px. \a full is the wide
 * surface, which draws the actions row too; the compact dock has only the
 * control row, its rail already carrying the actions. */
float cinema_dock_control_height(bool full);

/**
 * "My Cameras" (view3d_director_cinema_cameras.cc): the SCENE's cameras, the
 * Add Camera chip, in-place rename and per-row delete. The list is read from
 * the scene each draw — a shot-based list could not show the scene's own
 * default camera, nor follow a camera added or deleted outside Director — and
 * the live row is `scene->camera`, so the highlight follows a change made
 * anywhere. \a card is the card rect the right column laid out.
 */
void cinema_draw_camera_list(ui::Block *block,
                             const bContext *C,
                             const ARegion *region,
                             const DirectorViewState &state,
                             const rctf &card);

/**
 * Whether region px (\a x, \a y) is over the camera rows the painter
 * published this frame AND the list actually overflows. The scroll operator's
 * poll is the card's only hit test — the surface itself never hit-tests.
 */
bool cinema_camera_list_contains(const ARegion *region, int x, int y);

/** Row pitch in REGION px as the card last drew it; 0 before any draw.
 * A trackpad gesture turns its pixels into rows with this rather than
 * re-deriving the card's layout. */
float cinema_camera_list_row_pitch();

/** Scroll the published camera list by \a delta rows; false when it cannot. */
bool cinema_camera_list_scroll(int delta);

/** Drop \a region's published camera-list rect (no rows drawn this frame). */
void cinema_camera_list_release(const ARegion *region);

/** Cameras, aerial map, fps/resolution, export. */
void cinema_draw_right_panel(ui::Block *block,
                             const bContext *C,
                             const ARegion *region,
                             const DirectorViewState &state);

/** \} */

}  // namespace blender
