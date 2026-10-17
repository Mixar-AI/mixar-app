/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * The AI Provider settings sheet: the designer's framed two-column card
 * (title and subtitle over a header divider, a provider sidebar with its
 * Local Model foot, model chips, the key field with Save & Activate docked
 * inside it) painted onto an ordinary props dialog.
 *
 * The dialog stays a native block built from Python through the ordinary
 * layout API — Blender keeps events, text editing, RNA and the operator
 * flow — and every element is a native button tagged with a `Sheet*`
 * #MixarCardElement so widget dispatch hands it to these painters. The
 * backdrop (frame, dividers) is painted once per block from
 * #UI_mixar_sheet_draw_back when the block carries #BLOCK_MIXAR_SHEET.
 *
 * Geometry is written in the artboard's own units: the design is a 2x export
 * (1502 x 969 design px for a 751 x 484.5 UI-px dialog), so every token below
 * is a design px and `mixar_sheet::px` turns it into region pixels. Python
 * lays the rows out in the same units (`byok/ui/operators/byok_sheet.py`), so
 * the two sides never disagree about a measurement.
 */

#pragma once

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

/** The artboard's type renders about 7% larger than Clash Grotesk at the
 * same nominal size (measured on the title, rows, chips and captions of a
 * 1:1 capture), so every face is sized up by this before `px`. */
inline constexpr float text_scale = 1.07f;

/* -- Frame -------------------------------------------------------------- */
inline constexpr float frame_radius = 16.0f;
inline constexpr float frame_line = 1.0f;
inline constexpr uchar frame_fill[4] = {0x18, 0x19, 0x1C, 255};
inline constexpr uchar frame_border[4] = {0x45, 0x44, 0x47, 255};

/* -- Header: title at 66 / baseline 88, subtitle baseline 133 ----------- */
inline constexpr float title_x = 66.0f;
inline constexpr float title_size = 46.0f;
inline constexpr float title_baseline = 88.0f;
inline constexpr float subtitle_size = 22.0f;
inline constexpr float subtitle_baseline = 133.0f;

/* -- Close: 100 square, 40 from the top, 42 from the right -------------- */
inline constexpr float close_size = 100.0f;
inline constexpr float close_top = 40.0f;
inline constexpr float close_right = 42.0f;
inline constexpr float close_radius = 16.0f;
inline constexpr float close_cross = 31.0f;
inline constexpr float close_stroke = 2.0f;
inline constexpr uchar close_fill[4] = {0x27, 0x28, 0x29, 255};
inline constexpr uchar close_fill_hover[4] = {0x36, 0x37, 0x39, 255};
inline constexpr uchar close_cross_col[4] = {0xFF, 0x85, 0x85, 255};

/* -- Text --------------------------------------------------------------- */
inline constexpr float caption_size = 22.0f;
inline constexpr float prompt_size = 24.0f;
inline constexpr float note_size = 16.0f;
inline constexpr float body_size = 24.0f;
inline constexpr float label_size = 26.0f;
inline constexpr uchar text_bright[4] = {0xFF, 0xFF, 0xFF, 255};
inline constexpr uchar text_body[4] = {0xE2, 0xE2, 0xE2, 255};
inline constexpr uchar text_dim[4] = {0x6B, 0x6B, 0x6B, 255};
inline constexpr uchar text_danger[4] = {0xFF, 0x85, 0x85, 255};
/** `|`-free marker Python wraps the bright span of a caption in
 * ("ALL SUPPORTED \x1fANTHROPIC\x1f MODELS"); never drawn. */
inline constexpr char caption_bright_mark = '\x1f';

/* -- Provider row: 59 tall pill, text 28 in, dot 15.5 left of it -------- */
inline constexpr float row_h = 59.0f;
inline constexpr float row_radius = 24.0f;
inline constexpr float row_text_x = 28.0f;
/** A long provider name may run to the pill's edge before it is ellipsised. */
inline constexpr float row_text_right = 8.0f;
inline constexpr float row_dot_r = 5.5f;
inline constexpr float row_dot_gap = 15.5f;
inline constexpr uchar row_fill_a[4] = {0x37, 0x37, 0x37, 255};
inline constexpr uchar row_fill_b[4] = {0x48, 0x48, 0x48, 255};
inline constexpr uchar row_text_off[4] = {0x70, 0x70, 0x70, 255};
inline constexpr uchar row_dot[4] = {0xD9, 0xD9, 0xD9, 255};

/* -- Sidebar foot: 76 tall bar, monitor glyph at 108, text at 144 ------- */
inline constexpr float footer_h = 76.0f;
inline constexpr float footer_icon_x = 108.0f;
inline constexpr float footer_icon = 20.0f;
inline constexpr float footer_icon_stroke = 1.5f;
inline constexpr float footer_text_x = 144.0f;
inline constexpr uchar footer_fill[4] = {0x45, 0x44, 0x47, 255};
inline constexpr uchar footer_fill_hover[4] = {0x52, 0x51, 0x55, 255};

/* -- Model chip: 49 tall, 19 padding, 22 radius ------------------------- */
inline constexpr float chip_h = 49.0f;
inline constexpr float chip_radius = 22.0f;
inline constexpr float chip_pad = 19.0f;
inline constexpr uchar chip_fill[4] = {0x32, 0x32, 0x32, 255};
inline constexpr uchar chip_text_off[4] = {0x72, 0x72, 0x72, 255};

/* -- Key field: 81 tall, 21.5 radius; the primary docks 8 inside it ----- */
inline constexpr float input_h = 81.0f;
inline constexpr float input_radius = 21.5f;
inline constexpr uchar input_fill[4] = {0x13, 0x13, 0x13, 255};
inline constexpr uchar input_border[4] = {0x45, 0x44, 0x47, 255};
inline constexpr uchar input_border_focus[4] = {0x6A, 0x69, 0x6E, 255};
inline constexpr float dropdown_h = 60.0f;
inline constexpr float dropdown_chevron = 12.0f;

/* -- Pills: 66 tall, 16 radius ------------------------------------------ */
inline constexpr float button_h = 66.0f;
inline constexpr float button_radius = 16.0f;
inline constexpr float button_dock_inset = 8.0f;
inline constexpr float button_pad = 36.0f;
inline constexpr uchar primary_fill[4] = {0x2B, 0x7C, 0x4B, 255};
inline constexpr uchar primary_fill_hover[4] = {0x35, 0x90, 0x5A, 255};
inline constexpr uchar secondary_fill[4] = {0x2E, 0x2F, 0x31, 255};
inline constexpr uchar secondary_fill_hover[4] = {0x3A, 0x3B, 0x3E, 255};
inline constexpr uchar danger_fill[4] = {0x3B, 0x22, 0x24, 255};
inline constexpr uchar danger_fill_hover[4] = {0x4C, 0x2A, 0x2D, 255};

/* Private kit shared by the two painter files. */

/** The sheet face (Clash Grotesk, the widget font when it is missing) sized
 * to \a size_dp design px; returns the BLF id ready to measure and draw. */
int font(float size_dp);
float text_width(int font_id, const char *text);
/** Baseline-anchored, unclipped. */
void text_at(int font_id, float x, float baseline, const char *text, const uchar col[4]);
/** Cap-height centred on \a rect's middle, tail-ellipsised to its width. */
void text_in(int font_id, const rctf &rect, const char *text, const uchar col[4], bool centre);
/** Anti-aliased stroke of \a width px between two points. */
void stroke(float x0, float y0, float x1, float y1, float width, const uchar col[4], float alpha);

/** The button's block as a region-pixel rect (popups map 1:1). */
rctf block_rect(const Button *but);

/* Controls (`interface_mixar_sheet_controls.cc`). */
void draw_close(Button *but, const rcti *rect);
void draw_provider_row(Button *but, const rcti *rect);
void draw_footer_row(Button *but, const rcti *rect);
void draw_chip(Button *but, const rcti *rect);
void draw_pill(Button *but, const rcti *rect, MixarCardElement element);

}  // namespace mixar_sheet

/** The #MixarCardElement for an RNA `mixar_sheet*` kind value; None if unknown. */
MixarCardElement UI_mixar_sheet_element_from_kind(int kind);

/** Whether \a element is one of the sheet kinds. */
bool UI_mixar_sheet_element_is(MixarCardElement element);

/**
 * Mark \a layout's block as a sheet and record its chrome: the header divider
 * \a header_dp below the top edge and a sidebar \a sidebar_dp wide (design px).
 */
void UI_layout_mixar_sheet_frame(Layout *layout, float header_dp, float sidebar_dp);

/**
 * Tag the most recently created button of \a layout's block as sheet
 * \a element. \a lit marks the current choice (provider row, chip);
 * \a extra is the kind's payload: for an input the design-px width of the
 * control docked after it that its field must run underneath, for a pill
 * 1.0 when it is docked inside the field.
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

}  // namespace blender::ui
