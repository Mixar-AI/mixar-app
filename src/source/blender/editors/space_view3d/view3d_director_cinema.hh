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


/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct bContext;

namespace ui {
struct Block;
struct Button;
}
struct DirectorViewState;

/* -------------------------------------------------------------------- */
/** \name Design tokens (design px @1x)
 * \{ */

/** Design y of the viewport's top edge in the export's window mock. */
#define CINEMA_VIEWPORT_TOP 85.0f

/* Panels. */
#define CINEMA_PANEL_W 245.0f
#define CINEMA_PANEL_RADIUS 19.0f
#define CINEMA_MARGIN 70.0f     /* Window edge -> panel edge, at design width. */
#define CINEMA_MARGIN_MIN 20.0f /* Floor when the viewport is narrower. */
#define CINEMA_GATE_MIN_W 180.0f /* Clear width kept between the two columns. */
/**
 * Smallest fit the designed surface is allowed to shrink to before the compact
 * rail takes over. The design is fitted to the region (see #cinema_fit_scale):
 * a laptop viewport that cannot hold it at 1x shows it at, say, 0.8x — the
 * mock itself is a 0.8x render — rather than a different UI.
 */
#define CINEMA_SCALE_MIN 0.6f

/* Rows inside a panel. */
/* ONE row class for every rounded control — dropdown rows, list rows,
 * segment tracks, the strip's chips and dropdown, the dock's chips and fields
 * — so the design reads as one system: same height, same radius, same
 * gradient. Cards keep CINEMA_PANEL_RADIUS. */
#define CINEMA_ROW_W 216.0f
#define CINEMA_ROW_H 32.0f
#define CINEMA_ROW_RADIUS 14.0f
#define CINEMA_ROW_PITCH 68.0f  /* Labelled dropdown to the next one. */
#define CINEMA_LIST_PITCH 32.0f /* Template / camera list rows. */
/** Rows a list can show before it has to window around the live one. */
#define CINEMA_LIST_MAX_ROWS 4

/* Top strip. */
#define CINEMA_KEYCAP_W 17.0f
#define CINEMA_KEYCAP_H 19.0f
#define CINEMA_KEYCAP_RADIUS 4.0f
/** Hint groups start at the camera gate's left edge and pack at this gap. */
#define CINEMA_HINT_GAP 26.0f
#define CINEMA_PHONE_W 260.0f
#define CINEMA_PHONE_H 32.0f
/* The strip's controls flow right-to-left from the stage's right edge: phone,
 * interpolation dropdown, tracking eyedropper. The phone collapses to an
 * icon chip (CINEMA_PHONE_H square) when the hints would otherwise run into
 * the controls. */
#define CINEMA_INTERP_W 150.0f
#define CINEMA_STRIP_GAP 10.0f
/* The Mixar banner chip above the left column: a CINEMA_PANEL_W pill on the
 * strip band (row class height and radius), inert. */
#define CINEMA_BRAND_PAD 10.0f         /* Pill edge -> logo chip. */
#define CINEMA_BRAND_LOGO 22.0f        /* Round logo chip diameter. */
#define CINEMA_BRAND_MARK 14.0f        /* Mixar mark edge inside the logo chip. */
#define CINEMA_BRAND_GAP 8.0f          /* Logo -> wordmark -> mode name. */
#define CINEMA_BRAND_VERSION_PAD 12.0f /* Pill's right edge -> "V1". */

/* Right panel. Cards stack from CINEMA_COLUMN_TOP at CINEMA_CARD_GAP so the
 * column's foot lands on the same design y as the left column's. */
#define CINEMA_CARD_GAP 11.0f
#define CINEMA_CAMERAS_H 200.0f
#define CINEMA_PREVIEW_H 178.0f
#define CINEMA_SEGMENT_H 32.0f
#define CINEMA_EXPORT_H 48.0f

/* The columns' top edge and the stage's inset from them. The stage (the
 * working area between the columns that the camera gate is fitted to) spans
 * exactly the columns' vertical extent: from here down to
 * #cinema_content_bottom(). */
#define CINEMA_COLUMN_TOP 206.0f
#define CINEMA_STAGE_INSET 18.0f
/** Gap between the camera gate's foot and the chat bar (the resting pill),
 * and between the chat bar's foot and the timeline's top border. */
#define CINEMA_CHAT_GAP 10.0f
/** Inset of the fitted camera border inside the stage. */
#define CINEMA_GATE_PAD 6.0f

/* Lowest content in either column. The height gate is DERIVED from these, so
 * moving a card down moves the gate with it instead of silently laying the
 * Speed slider and the Export button out below the region. */
#define CINEMA_SPEED_CARD_Y 670.0f
#define CINEMA_SPEED_CARD_H 70.0f
#define CINEMA_EXPORT_Y 692.0f

/* Speed bounds. These MIRROR SPEED_MIN / SPEED_MAX in `director/constants.py`,
 * the `shot.speed` RNA property's own limits and therefore the slider's
 * travel; keep the two in step. The slider rests in the middle at 0 (the
 * timing as captured); right contracts the shot, left expands it. */
#define CINEMA_SPEED_MIN -1.0f
#define CINEMA_SPEED_MAX 1.0f

/* Type sizes. */
#define CINEMA_FONT_LABEL 12.0f /* "Aspect Ratio", "My Cameras", hints. */
#define CINEMA_FONT_VALUE 13.0f /* Dropdown values, list rows. */
#define CINEMA_FONT_TITLE 15.0f /* Dock "Duration". */

/* Palette. */
#define CINEMA_COL_CARD_TOP {0.133f, 0.137f, 0.137f, 0.96f}    /* #222323 */
#define CINEMA_COL_CARD_BOTTOM {0.043f, 0.043f, 0.043f, 0.96f} /* #0B0B0B */
#define CINEMA_COL_ROW_TOP {0.345f, 0.345f, 0.345f, 1.0f}      /* #585858 */
#define CINEMA_COL_ROW_BOTTOM {0.141f, 0.141f, 0.141f, 1.0f}   /* #242424 */
#define CINEMA_COL_LABEL {0.502f, 0.502f, 0.502f, 1.0f}        /* #808080 */
/** Dropdown captions and card titles: darker and a little translucent. */
#define CINEMA_COL_CAPTION {0.40f, 0.40f, 0.40f, 0.85f}
#define CINEMA_COL_VALUE {1.0f, 1.0f, 1.0f, 1.0f}
#define CINEMA_COL_DIM {0.388f, 0.388f, 0.388f, 1.0f}    /* #636363 */
#define CINEMA_COL_DIMMER {0.216f, 0.216f, 0.216f, 1.0f} /* #373737 */
#define CINEMA_COL_KEYCAP {0.392f, 0.392f, 0.392f, 1.0f} /* #646464 */
#define CINEMA_COL_PHONE {0.220f, 0.220f, 0.220f, 1.0f}  /* #383838 */
#define CINEMA_COL_CHIP {0.314f, 0.314f, 0.314f, 1.0f}   /* #505050 */
#define CINEMA_COL_EXPORT {0.102f, 0.251f, 0.149f, 1.0f} /* #1A4026 */
#define CINEMA_COL_BRAND_TOP {0.043f, 0.192f, 0.102f, 1.0f}    /* #0B311A */
#define CINEMA_COL_BRAND_BOTTOM {0.059f, 0.059f, 0.059f, 1.0f} /* #0F0F0F */
/** The banner's logo chip: the Agent island's own chip ramp. */
#define CINEMA_COL_LOGO_TOP {0.125f, 0.345f, 0.212f, 1.0f}    /* #205836 */
#define CINEMA_COL_LOGO_BOTTOM {0.227f, 0.518f, 0.341f, 1.0f} /* #3A8457 */
#define CINEMA_COL_GATE_FILL {0.851f, 0.851f, 0.851f, 0.07f}
#define CINEMA_COL_GATE_LINE {0.247f, 0.247f, 0.247f, 1.0f} /* #3F3F3F */
#define CINEMA_COL_SPEED_ON {0.165f, 0.475f, 0.286f, 1.0f}  /* #2A7949 */
#define CINEMA_COL_SPEED_OFF {0.259f, 0.259f, 0.259f, 1.0f} /* #424242 */

/** \} */

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
 * Height of one list row, in design px.
 *
 * Clamped to #CINEMA_LIST_PITCH: rows advance by the pitch, and a taller row
 * overlaps its neighbour. The overlapping button is created LAST and
 * `ui_but_find_mouse_over_ex` walks a block backwards, so the bottom band of
 * every row would activate the entry BELOW it — and #cinema_qa_record would
 * publish that same wrong rect.
 */
float cinema_list_row_h();

/** First row to draw so \a active stays visible in a #CINEMA_LIST_MAX_ROWS window. */
int cinema_list_window_start(int count, int active);

/**
 * Rect from the design's WINDOW coordinates, anchored to the region's top.
 * The design mock includes the app chrome, so #CINEMA_VIEWPORT_TOP is the
 * design y at which the viewport region begins.
 */
rctf cinema_design_rect(const ARegion *region, float x, float y, float w, float h);

/** Vertically graded rounded panel. */
void cinema_panel(const rctf &rect, float radius, const float top[4], const float bottom[4]);

/** Flat rounded fill. */
void cinema_fill(const rctf &rect, float radius, const float color[4]);

/** Rounded outline only. */
void cinema_outline(const rctf &rect, float radius, const float color[4], float width);

void cinema_text_left(const char *text, float x, float center_y, float size, const float col[4]);
void cinema_text_center(const char *text, float cx, float center_y, float size, const float col[4]);
void cinema_text_right(const char *text, float right, float cy, float size, const float col[4]);
float cinema_text_width(const char *text, float size);

/** Down chevron used by every dropdown row. */
void cinema_chevron(float cx, float cy, float size, const float col[4]);

/**
 * Triangle with its flat edge at \a x and its apex at `x + dx`, so a negative
 * \a dx points left. Used for the transport glyphs.
 */
void cinema_triangle(float x, float cy, float dx, float half_h, const float col[4]);

/** Keycap glyph (19x21 rounded chip with a centred letter). */
void cinema_keycap(float x, float y, const char *letter);

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

/**
 * Which bar a popup opens from. The popup's rows take the bar's width
 * (#director_popup_width) so a list never runs past the block it hangs
 * from; one slot per bar class keeps the pointer handed to the popup stable.
 */
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

/** Icon-only operator button over painted chrome (the icon is the label). */
ui::Button *cinema_icon_button(ui::Block *block,
                               const char *operator_id,
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

/** Timeline dock: the panel behind the control row and ruler. */
void cinema_draw_dock_panel(const ARegion *region);

/** Timeline dock: Duration units, transport, frame range, mode tools. */
void cinema_draw_dock_controls(ui::Block *block,
                               const bContext *C,
                               const ARegion *region,
                               const DirectorViewState &state,
                               bool playing);

/**
 * Timeline dock, compact layout: transport plus the mode tools that have no
 * other home. Drawn instead of #cinema_draw_dock_controls when the viewport
 * is below the wide-surface gate, where the old rail owns the chrome.
 */
void cinema_draw_dock_compact(ui::Block *block,
                              const ARegion *region,
                              const DirectorViewState &state,
                              bool playing);

/** Height the dock's control row occupies, in region px. */
float cinema_dock_control_height();

/** Cameras, preview, fps/resolution, export. */
void cinema_draw_right_panel(ui::Block *block,
                             const bContext *C,
                             const ARegion *region,
                             const DirectorViewState &state);

/** \} */

}  // namespace blender
