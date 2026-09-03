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

/* Rows inside a panel. */
#define CINEMA_ROW_W 216.0f
#define CINEMA_ROW_H 38.0f
#define CINEMA_ROW_RADIUS 15.0f
#define CINEMA_ROW_PITCH 79.0f  /* Labelled dropdown to the next one. */
#define CINEMA_LIST_PITCH 34.0f /* Template / camera list rows. */
/** Rows a list can show before it has to window around the live one. */
#define CINEMA_LIST_MAX_ROWS 4

/* Top strip. */
#define CINEMA_CHIP_H 41.0f
#define CINEMA_KEYCAP_W 19.0f
#define CINEMA_KEYCAP_H 21.0f
#define CINEMA_KEYCAP_RADIUS 4.0f
#define CINEMA_PHONE_W 292.0f
#define CINEMA_PHONE_H 37.0f

/* Right panel. */
#define CINEMA_SEGMENT_H 41.0f
#define CINEMA_SEGMENT_CHIP_W 81.0f
#define CINEMA_SEGMENT_CHIP_H 37.0f
#define CINEMA_EXPORT_H 59.0f
#define CINEMA_PREVIEW_H 170.0f

/* Lowest content in either column. The height gate is DERIVED from these, so
 * moving a card down moves the gate with it instead of silently laying the
 * Speed slider and the Export button out below the region. */
#define CINEMA_SPEED_CARD_Y 732.0f
#define CINEMA_SPEED_CARD_H 81.0f
#define CINEMA_EXPORT_Y 754.0f

/* Keyframe spacing bounds. These MIRROR MIN_BEAT_SECONDS / MAX_BEAT_SECONDS
 * in `director/constants.py`, which are the `beat_seconds` RNA property's own
 * limits and therefore the slider's travel; keep the two in step. */
#define CINEMA_BEAT_SECONDS_MIN 0.1f
#define CINEMA_BEAT_SECONDS_MAX 10.0f

/* Type sizes. */
#define CINEMA_FONT_LABEL 13.0f /* "Aspect Ratio", "My Cameras". */
#define CINEMA_FONT_VALUE 15.0f /* Dropdown values, list rows. */
#define CINEMA_FONT_TITLE 17.0f /* "Cinema Mode". */

/* Palette. */
#define CINEMA_COL_CARD_TOP {0.133f, 0.137f, 0.137f, 0.96f}    /* #222323 */
#define CINEMA_COL_CARD_BOTTOM {0.043f, 0.043f, 0.043f, 0.96f} /* #0B0B0B */
#define CINEMA_COL_ROW_TOP {0.345f, 0.345f, 0.345f, 1.0f}      /* #585858 */
#define CINEMA_COL_ROW_BOTTOM {0.141f, 0.141f, 0.141f, 1.0f}   /* #242424 */
#define CINEMA_COL_LABEL {0.502f, 0.502f, 0.502f, 1.0f}        /* #808080 */
#define CINEMA_COL_VALUE {1.0f, 1.0f, 1.0f, 1.0f}
#define CINEMA_COL_DIM {0.388f, 0.388f, 0.388f, 1.0f}    /* #636363 */
#define CINEMA_COL_DIMMER {0.216f, 0.216f, 0.216f, 1.0f} /* #373737 */
#define CINEMA_COL_KEYCAP {0.392f, 0.392f, 0.392f, 1.0f} /* #646464 */
#define CINEMA_COL_PHONE {0.220f, 0.220f, 0.220f, 1.0f}  /* #383838 */
#define CINEMA_COL_CHIP {0.314f, 0.314f, 0.314f, 1.0f}   /* #505050 */
#define CINEMA_COL_EXPORT {0.102f, 0.251f, 0.149f, 1.0f} /* #1A4026 */
#define CINEMA_COL_BRAND_TOP {0.043f, 0.192f, 0.102f, 1.0f}    /* #0B311A */
#define CINEMA_COL_BRAND_BOTTOM {0.059f, 0.059f, 0.059f, 1.0f} /* #0F0F0F */
#define CINEMA_COL_GATE_FILL {0.851f, 0.851f, 0.851f, 0.07f}
#define CINEMA_COL_GATE_LINE {0.247f, 0.247f, 0.247f, 1.0f} /* #3F3F3F */
#define CINEMA_COL_SPEED_ON {0.165f, 0.475f, 0.286f, 1.0f}  /* #2A7949 */
#define CINEMA_COL_SPEED_OFF {0.259f, 0.259f, 0.259f, 1.0f} /* #424242 */

/** \} */

/* -------------------------------------------------------------------- */
/** \name Shared painters (view3d_director_cinema_paint.cc)
 * \{ */

/** Design px -> region px. One scale rule for the whole surface. */
float cinema_unit();

/**
 * Side margin in design px for \a region.
 *
 * The design is a full-bleed 1798px window; a viewport sharing the screen
 * with another editor is narrower, so the two columns keep their measured
 * width and give up margin down to a floor rather than overlapping the gate.
 */
float cinema_margin(const ARegion *region);

/** Whether the region can host the designed surface at all. */
bool cinema_surface_fits(const ARegion *region);

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

/** Same, but opening a native block popup (the existing Director popups). */
ui::Button *cinema_popup_button(ui::Block *block,
                           ui::BlockCreateFunc block_func,
                           const rctf &rect,
                           const char *tooltip);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Surface sections
 * \{ */

/**
 * The stage: the design's rounded frame around the working viewport, inset
 * between the two columns. Decorative chrome, not the camera gate.
 */
void cinema_draw_stage(const ARegion *region);

/** Branding chip, shortcut hints, phone button. */
void cinema_draw_top_strip(ui::Block *block, const ARegion *region, const DirectorViewState &state);

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
