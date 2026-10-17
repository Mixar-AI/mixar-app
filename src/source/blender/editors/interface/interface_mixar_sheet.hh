/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * The sheet dialogs (AI Provider settings, Connect MCP): the designer's
 * framed two-column card (title and subtitle over a header divider, a
 * sidebar of rows with a foot row, chips, the key field with its primary
 * docked inside, code snippets, switches and status lines) painted onto an
 * ordinary props dialog.
 *
 * The dialog stays a native block built from Python through the ordinary
 * layout API — Blender keeps events, text editing, RNA and the operator
 * flow — and every element is a native button tagged with a `Sheet*`
 * #MixarCardElement so widget dispatch hands it to these painters. The
 * backdrop (frame, dividers) is painted once per block from
 * #UI_mixar_sheet_draw_back when the block carries #BLOCK_MIXAR_SHEET.
 *
 * Geometry is written in the artboard's own units: the design is a 2x export
 * (1440 x 700 design px for a 720 x 350 UI-px dialog, taller when its content
 * needs it), so every token below is a design px and `mixar_sheet::px` turns
 * it into region pixels. Python lays the rows out in the same units
 * (`modules/common/sheet/kit.py`: WIDTH, HEIGHT, HEADER, SIDEBAR), so the
 * two sides never disagree about a measurement.
 */

#pragma once

#include <string>

#include "BLI_rect.h"
#include "BLI_sys_types.h"

#include "UI_mixar_types.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

struct Block;
struct Button;
struct Layout;

namespace mixar_sheet {

/** Design px (2x artboard) -> region px at the live UI scale. */
float px(float design_px);

/* Type follows Mixar's text roles (UI_mixar_text.hh), not the artboard's px:
 * every size below is a RATIO of the UI body size (the widget font's points
 * at the live scale, the same unit the Agent island measures in), drawn in
 * the island's face with its weights; captions use the monospace face the
 * island's model card uses. `font()` resolves a ratio to a BLF id. */
inline constexpr int weight_regular = 400;
inline constexpr int weight_medium = 500;
inline constexpr int weight_strong = 600;

/* -- Frame -------------------------------------------------------------- */
inline constexpr float frame_radius = 20.0f;
inline constexpr float frame_line = 1.0f;
inline constexpr uchar frame_fill[4] = {0x18, 0x19, 0x1B, 255};
inline constexpr uchar frame_border[4] = {0x33, 0x34, 0x37, 255};

/* -- Header: title and subtitle from the sheet's left margin ------------ */
inline constexpr float title_x = 66.0f;
inline constexpr float title_size = 1.5f;       /* x body */
inline constexpr float title_baseline = 70.0f;
inline constexpr float subtitle_size = 0.92f;   /* x body */
inline constexpr float subtitle_baseline = 108.0f;

/* -- Close: a quiet square that only fills under the pointer ------------- */
inline constexpr float close_size = 60.0f;
inline constexpr float close_top = 38.0f;
inline constexpr float close_right = 38.0f;
inline constexpr float close_radius = 14.0f;
inline constexpr float close_cross = 18.0f;
inline constexpr float close_stroke = 2.0f;
inline constexpr uchar close_fill[4] = {0x2A, 0x2B, 0x2D, 0};
inline constexpr uchar close_fill_hover[4] = {0x2E, 0x2F, 0x32, 255};
inline constexpr uchar close_cross_col[4] = {0xB4, 0xB4, 0xB8, 255};

/* -- Text (x body; Mixar roles: Caption 15/18, Body 18/18) -------------- */
inline constexpr float caption_size = 0.8f;     /* monospace caption */
inline constexpr float prompt_size = 1.0f;
inline constexpr float note_size = 0.86f;
inline constexpr float body_size = 1.0f;
inline constexpr float label_size = 1.0f;
inline constexpr uchar text_bright[4] = {0xF2, 0xF2, 0xF2, 255};
inline constexpr uchar text_body[4] = {0xDC, 0xDC, 0xDC, 255};
inline constexpr uchar text_dim[4] = {0x8A, 0x8A, 0x8C, 255};
inline constexpr uchar text_danger[4] = {0xF0, 0x86, 0x7E, 255};
/** `|`-free marker Python wraps the bright span of a caption in
 * ("ALL SUPPORTED \x1fANTHROPIC\x1f MODELS"); never drawn. */
inline constexpr char caption_bright_mark = '\x1f';

/* -- Provider row: 46 tall plate, text 20 in, dot 15.5 left of it ------- */
inline constexpr float row_h = 46.0f;
inline constexpr float row_radius = 14.0f;
inline constexpr float row_text_x = 20.0f;
/** A long provider name may run to the pill's edge before it is ellipsised. */
inline constexpr float row_text_right = 8.0f;
inline constexpr float row_dot_r = 4.5f;
inline constexpr float row_dot_gap = 15.5f;
inline constexpr uchar row_fill_a[4] = {0x2A, 0x2B, 0x2D, 255};
inline constexpr uchar row_fill_b[4] = {0x31, 0x32, 0x35, 255};
inline constexpr uchar row_text_off[4] = {0x9C, 0x9C, 0x9F, 255};
inline constexpr uchar row_dot[4] = {0x7D, 0xDB, 0x8E, 255};

/* -- Sidebar foot (Local model, Other app): a row with a glyph ---------- */
inline constexpr float footer_h = 64.0f;
inline constexpr float footer_icon = 18.0f;
inline constexpr float footer_icon_stroke = 1.5f;
inline constexpr float footer_icon_gap = 14.0f;
/** The foot's payload (`progress`) at or above this draws the terminal
 * glyph (a rounded screen holding `>_`) instead of the monitor. */
inline constexpr float footer_terminal = 1.0f;
inline constexpr float footer_terminal_h = 15.0f;

/* -- Model chip: 40 tall, 16 padding ------------------------------------ */
inline constexpr float chip_h = 40.0f;
inline constexpr float chip_radius = 14.0f;
inline constexpr float chip_pad = 16.0f;
inline constexpr uchar chip_fill[4] = {0x31, 0x32, 0x35, 255};
inline constexpr uchar chip_text_off[4] = {0x9C, 0x9C, 0x9F, 255};

/* -- Key field: 64 tall, 14 radius; the primary docks 6 inside it ------- */
inline constexpr float input_h = 64.0f;
inline constexpr float input_radius = 14.0f;
inline constexpr uchar input_fill[4] = {0x12, 0x12, 0x14, 255};
inline constexpr uchar input_border[4] = {0x33, 0x34, 0x37, 255};
inline constexpr uchar input_border_focus[4] = {0x5A, 0x5B, 0x60, 255};
inline constexpr float dropdown_h = 52.0f;
inline constexpr float dropdown_chevron = 12.0f;
/** The chevron's centre, from the dropdown's right edge. */
inline constexpr float dropdown_chevron_right = 30.0f;
/** Room the value text leaves free of the chevron, from the right edge. */
inline constexpr float dropdown_text_right = 48.0f;

/* -- Pills: 52 tall, 12 radius ------------------------------------------ */
inline constexpr float button_h = 52.0f;
inline constexpr float button_radius = 12.0f;
inline constexpr float button_dock_inset = 6.0f;
inline constexpr float button_pad = 32.0f;
inline constexpr uchar primary_fill[4] = {0x2B, 0x7C, 0x4B, 255};
inline constexpr uchar primary_fill_hover[4] = {0x35, 0x90, 0x5A, 255};
inline constexpr uchar secondary_fill[4] = {0x2E, 0x2F, 0x31, 255};
inline constexpr uchar secondary_fill_hover[4] = {0x3A, 0x3B, 0x3E, 255};
inline constexpr uchar danger_fill[4] = {0x3B, 0x22, 0x24, 255};
inline constexpr uchar danger_fill_hover[4] = {0x4C, 0x2A, 0x2D, 255};
/** A pill's payload (`progress`) at or above this docks it in the top-right
 * corner of a taller block (a snippet), #button_dock_inset in from the top
 * and right edges and #button_h tall; from 0.5 it docks full-height inside
 * the key field. */
inline constexpr float dock_corner = 2.0f;

/* -- Snippet: a monospace code block on the key field's backdrop -------- */
inline constexpr float snippet_size = 0.82f;  /* x body, monospace */
inline constexpr float snippet_line_h = 28.0f;
inline constexpr float snippet_pad_x = 22.0f;
inline constexpr float snippet_pad_y = 18.0f;

/* -- Switch: a 45 x 26 track, a 19 knob, the label 16 after it ---------- */
inline constexpr float switch_w = 45.0f;
inline constexpr float switch_h = 26.0f;
inline constexpr float switch_knob = 19.0f;
inline constexpr float switch_gap = 16.0f;
inline constexpr uchar switch_track_off[4] = {0x3A, 0x3B, 0x3E, 255};
inline constexpr uchar switch_track_off_hover[4] = {0x45, 0x46, 0x4A, 255};

/* -- Status dot: the disc leading a status line (green / danger / dim) -- */
inline constexpr float status_dot = 11.0f;

/* Private kit shared by the two painter files. */

/** The island's face (or the monospace caption face) at \a ratio x the UI
 * body size and \a weight; returns the BLF id ready to measure and draw.
 * `text_at` / `text_in` restore the widget weight on every exit (empty text
 * included); a measure-only caller restores it itself. */
int font(float ratio, int weight = weight_medium, bool mono = false);
float text_width(int font_id, const char *text);
/** Cap height of the face at its current size: the artboard centres labels
 * on their caps, not on the ascender/descender box. */
float cap_height(int font_id);
/** \a text shortened with a tail ellipsis to \a max_w px. */
std::string fit(int font_id, const char *text, float max_w);
/** Baseline-anchored, unclipped (callers fit first). */
void text_at(int font_id, float x, float baseline, const char *text, const uchar col[4]);
/** Cap-height centred on \a rect's middle, tail-ellipsised to its width. */
void text_in(int font_id, const rctf &rect, const char *text, const uchar col[4], bool centre);
/** Anti-aliased stroke of \a width px between two points. */
void stroke(float x0, float y0, float x1, float y1, float width, const uchar col[4], float alpha);

/** The button's block as a region-pixel rect (popups map 1:1). */
rctf block_rect(const Button *but);

/* Shared by the painter files (`interface_mixar_sheet_controls.cc`). */
const char *but_label(const Button *but);
bool but_disabled(const Button *but);
void lerp_col(uchar out[4], const uchar a[4], const uchar b[4], float t);
/** Hover and press as one 0..1 cue. */
float hover_cue(float hover, float press);
float line_px();

/* Painters (`interface_mixar_sheet_controls.cc`). */
void draw_title(Button *but, const rcti *rect);
void draw_caption(Button *but, const rcti *rect);
void draw_text(Button *but,
               const rcti *rect,
               float size_dp,
               const uchar col_in[4],
               int weight = weight_regular);
void draw_close(Button *but, const rcti *rect);
void draw_provider_row(Button *but, const rcti *rect);
void draw_footer_row(Button *but, const rcti *rect);
void draw_chip(Button *but, const rcti *rect);
void draw_pill(Button *but, const rcti *rect, MixarCardElement element);
/* `interface_mixar_sheet_blocks.cc`. */
void draw_snippet(Button *but, const rcti *rect);
void draw_switch(Button *but, const rcti *rect);
void draw_status_dot(Button *but, const rcti *rect);
void draw_footer_glyph(Button *but, float x, float cy, const uchar col[4]);

}  // namespace mixar_sheet

/** The #MixarCardElement for an RNA `mixar_sheet*` kind value; None if unknown. */
MixarCardElement UI_mixar_sheet_element_from_kind(int kind);

/** Whether \a element is one of the sheet kinds. */
bool UI_mixar_sheet_element_is(MixarCardElement element);

/**
 * Mark \a layout's block as a sheet and record its chrome: the header divider
 * \a header_dp below the top edge and a sidebar \a sidebar_dp wide (design px).
 * Python always passes `kit.HEADER` / `SIDEBAR` (140 / 400); the RNA
 * defaults of `layout.mixar_sheet_frame` (182 / 442) are the first artboard's
 * and are never used.
 */
void UI_layout_mixar_sheet_frame(Layout *layout, float header_dp, float sidebar_dp);

/**
 * Tag the most recently created button of \a layout's block as sheet
 * \a element. \a lit marks the current choice (provider row, chip);
 * \a extra is the kind's payload: for an input (or a snippet) the design-px
 * width of the control docked after it that its backdrop must run
 * underneath, for a pill 1.0 when it is docked inside the field (2.0 in a
 * snippet's corner), for the footer row 1.0 for the terminal glyph, for a
 * status dot 1.0 for danger.
 */
void UI_layout_mixar_sheet_tag_last(Layout *layout,
                                    MixarCardElement element,
                                    bool lit,
                                    float extra);

/** Width \a text takes in \a element's face, in 1x UI px (scale removed) so
 * Python can wrap chips with the same numbers the painter spends. */
float UI_mixar_sheet_text_width(MixarCardElement element, const char *text);

/** The framed backdrop: fill, hairline, header and sidebar dividers. */
void UI_mixar_sheet_draw_back(const Block *block, const rcti *rect);

/** Paint one tagged element; false when \a element is not a sheet kind. */
bool UI_mixar_sheet_draw_element(Button *but, const rcti *rect, MixarCardElement element);

/** Backdrop of a Text button tagged SheetInput (the stock text pass follows). */
void UI_mixar_sheet_input_draw(Button *but, const rcti *rect);

/** Backdrop and chevron of a Menu button tagged SheetDropdown. */
void UI_mixar_sheet_dropdown_draw(Button *but, const rcti *rect);

/** Region px the stock text pass must take off a SheetDropdown's right edge
 * so its value never runs under the chevron. */
int UI_mixar_sheet_dropdown_text_inset();

}  // namespace blender::ui
