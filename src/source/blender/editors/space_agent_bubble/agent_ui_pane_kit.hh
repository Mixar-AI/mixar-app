/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The island pane kit — the ONE visual vocabulary every category pane (3D,
 * Media, Gaussian Splat, Queue) draws with, so the four tabs read as the same
 * product. Every token below is measured from the Figma frames (`3d.svg`,
 * `media.svg`, `gaussian splats.svg`, `just agent.svg`; island origin at
 * artboard 267,340) and is stated once HERE — a pane that needs a chip, a
 * segmented control, an ON/OFF pill, the prompt box, or the bottom
 * Upload/Generate row calls the kit instead of painting its own.
 *
 * Where the frames disagree the majority convention wins; the choices and
 * their sources:
 *  - params chips #313131 h44 rx14, label #E2E2E2 @18u  (all three frames)
 *  - value pill/segment thumb #484848 (3d + splat; media's dark #1A1A1A
 *    sub-tab thumb was the odd one out and is overridden)
 *  - bottom action chips #1D1D1D, Generate #1A4026 114x44 (all four frames)
 *  - prompt box #121212 rx28, 4-unit side/bottom inset (all frames)
 *  - bottom row INSIDE the box foot: 16 up, Upload 17 in, Generate 16 in
 *    from the right (identical rects in all four frames)
 *
 * Layout contract (prompt visibility): the PROMPT BOX IS RESERVED FIRST and
 * the params strip gets whatever height is left. A pane lays its strip out
 * from the panel top down, but clamps the strip bottom it hands to
 * `pane_prompt_box_rect` at `pane_params_floor` — so the box is never smaller
 * than #PANE_BOX_MIN_H and its text field is always created. Params that do
 * not fit wrap or elide inside their own strip. The box still grows with a
 * taller window and shrinks under a wrapping strip; what it may not do is
 * vanish while Generate stays armed, because Generate is a paid action and
 * must never submit a prompt the user cannot see or edit.
 *
 * Functional invariants the kit deliberately does NOT touch (they live with
 * the callers): catalog enum reads pass the real bContext; painted chips
 * draw AFTER any overlapping embossed field block; uiBlocks are built
 * outside GPU matrix translations; RNA string reads use the alloc form.
 */

#pragma once

#include "BLI_rect.h"

struct Image;
struct bContext;
struct uiBut;

/* -------------------------------------------------------------------- */
/** \name Tokens (island units unless noted; colours state alpha ALWAYS)
 * \{ */

/* Strip grid. */
#define PANE_INSET_X 21      /* Panel left/right -> first/last strip element. */
#define PANE_STRIP_TOP 25    /* Panel top -> first row top. */
#define PANE_ROW_H 44
#define PANE_ROW_PITCH 62    /* Row top -> next row top (44 + 18 gap). */
#define PANE_RADIUS 14
#define PANE_CHIP_GAP 12
#define PANE_CHIP_PAD_X 20
#define PANE_FONT 18
#define PANE_FONT_SUB 15
#define PANE_PILL_H 38       /* Value pill / segment thumb height. */
#define PANE_SEG_INSET 3     /* Track edge -> thumb edge. */

/* Prompt box. */
#define PANE_BOX_RADIUS 28
#define PANE_BOX_INSET 4     /* Panel edge -> box edge (sides + bottom). */
#define PANE_BOX_GAP 28      /* Strip bottom -> box top. */
#define PANE_BOX_MIN_H 40    /* Below this the box still paints, just short. */
#define PANE_PROMPT_FONT 24
#define PANE_FIELD_H 56      /* The typing strip at the box TOP (its ghost
                              * text and caret are text-height; the box below
                              * is presentation, not the editable widget). */

/* Bottom row (inside the box foot — rects identical in all four frames). */
#define PANE_BOTTOM_UP 16    /* Box bottom -> row bottom. */
#define PANE_BOTTOM_IN_L 17  /* Box left -> first action chip. */
#define PANE_BOTTOM_IN_R 16  /* Box right -> Generate right edge. */
#define PANE_GENERATE_W 114

/* Reference thumbnails in the bottom row. The Agent tab previews its pending
 * attachments this way, so every pane that takes a reference does too — a
 * chip-height square with a rounded backplate, then a dim "+N". */
#define PANE_REF_THUMB_MAX 4
#define PANE_REF_THUMB_GAP 6
#define PANE_REF_THUMB_RADIUS 6

/* Palette. */
#define PANE_COL_WASH_TOP {0.176f, 0.176f, 0.176f, 1.0f}    /* #2D2D2D */
#define PANE_COL_WASH_BOTTOM {0.075f, 0.078f, 0.075f, 1.0f} /* #131413 */
#define PANE_COL_CHIP {0.192f, 0.192f, 0.192f, 1.0f}        /* #313131 params chip / track */
#define PANE_COL_PILL {0.282f, 0.282f, 0.282f, 1.0f}        /* #484848 value pill / thumb */
#define PANE_COL_PILL_DIM {0.235f, 0.235f, 0.235f, 1.0f}    /* #3C3C3C recessed value */
#define PANE_COL_PILL_ON {0.278f, 0.278f, 0.278f, 1.0f}     /* #474747 ON pill */
#define PANE_COL_ACTION {0.114f, 0.114f, 0.114f, 1.0f}      /* #1D1D1D bottom chips */
#define PANE_COL_GENERATE {0.102f, 0.251f, 0.149f, 1.0f}    /* #1A4026 */
#define PANE_COL_BOX {0.071f, 0.071f, 0.071f, 1.0f}         /* #121212 prompt box */

/** \} */

/* -------------------------------------------------------------------- */
/** \name Primitives (BLF/GPU — the one implementation of the pane idioms)
 * \{ */

void pane_fill_round(const rctf *rect, float radius, const float col[4]);
float pane_text_width(const char *text, float size);
void pane_label_left(const char *text, float x, float cy, float size, const float col[4]);
void pane_label_centre(const char *text, float cx, float cy, float size, const float col[4]);
void pane_label_right(const char *text, float x, float cy, float size, const float col[4]);
/**
 * Truncate \a text in place (UTF-8-safe) until it fits \a max_w, appending an
 * ellipsis when anything was actually removed — a bare chop reads as a
 * different string ("ReproCone" -> "ReproCon"), not a shortened one. Only ever
 * shrinks the caller's buffer.
 */
void pane_fit_text(char *text, float max_w, float size);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Composites
 * \{ */

/** The #2D2D2D -> #131413 wash every category frame lays over the panel. */
void pane_wash_paint(const rctf &panel, float u);

/** Prompt-box rect per the layout contract (see file header). Defensively
 * clamped a hair above region y=0 — the panel may underhang the region by a
 * few px (its bottom inset extends into the TOOLS card-foot band), and a box
 * drawn below the region edge is what "clipped bottom row" looks like. */
rctf pane_prompt_box_rect(const rctf &panel, float strip_bottom_y, float u);
void pane_prompt_box_paint(const rctf &box, float u);

/**
 * The lowest y a params strip may reach.
 *
 * The prompt box is RESERVED FIRST and the params get what is left, not the
 * other way round: Generate is a paid action, so a schema that wraps past the
 * room available must never be able to squeeze the prompt box below
 * #PANE_BOX_MIN_H — that stopped the text field being created at all while
 * Generate stayed armed, and the button then submitted whatever stale prompt
 * string was on the tab group. Params that do not fit wrap or elide within
 * their own strip; every pane clamps its strip bottom to this floor.
 */
float pane_params_floor(const rctf &panel, float u);

/** True when \a box can host the prompt field (see #pane_params_floor). A
 * pane whose box fails this must also disable its Generate button. */
bool pane_prompt_fits(const rctf &box, float u);

/** The embossed field's rect: a PANE_FIELD_H strip at the box TOP. A field
 * spanning the whole box centres its ghost text vertically and draws a caret
 * the full box height — the strip keeps both at text scale. */
rctf pane_prompt_field_rect(const rctf &box, float u);

/** Bottom row inside the box foot, clamped so a short box can never push the
 * row out through its own top over the params strip (the OPS block wins
 * overlapping clicks, so a floating row makes the params unreachable). */
float pane_bottom_row_ymin(const rctf &box, float u);
rctf pane_generate_rect(const rctf &box, float u);
/** Generate button: #1A4026 pill, strong label when enabled, dim otherwise. */
void pane_generate_paint(const rctf &rect, const char *label, bool enabled, float u);

/** Bottom action chip (#1D1D1D): optional leading image icon. Width helper +
 * painter share one metrics definition so hit rects can never drift. */
float pane_action_chip_w(const char *label, bool with_icon, float u);
void pane_action_chip_paint(const rctf &rect, const char *label, bool with_icon, bool dim, float u);

/** Dropdown chip (#313131 + label + chevron). */
float pane_dropdown_chip_w(const char *label, float u);
void pane_dropdown_chip_paint(const rctf &rect, const char *label, float u);

/** Segmented control: track #313131, active thumb #484848 inset 3. Segment
 * widths come from the MEASURED labels (catalog labels outgrow design stubs).
 * Returns the track rect; fills r_segs[count]. */
rctf pane_segmented_layout(
    float x, float y_top, const char *const *labels, int count, float u, rctf *r_segs);
void pane_segmented_paint(
    const rctf *segs, const char *const *labels, const int active_index, int count, float u);

/** ON/OFF chip: label + #474747 pill behind the live side. */
float pane_onoff_chip_w(const char *label, float u);
void pane_onoff_chip_paint(const rctf &rect, const char *label, bool on, float u);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Reference thumbnails
 *
 * Every pane previews the images it will actually SUBMIT, the way the Agent
 * tab previews its pending attachments. Which images those are is per-tab
 * (each generation tab has a toggle choosing between the moodboard selection
 * and its own upload), so the pane collects them and the kit draws them.
 * \{ */

/** Still images currently selected on the moodboard, oldest first. */
int pane_board_selected_images(const bContext *C, Image **r_images, int max_images);

/** Aspect-fit \a image inside \a box. The caller paints the backplate. */
void pane_image_thumb_draw(Image *image, const rctf &box);

/**
 * Paint a run of reference thumbnails from \a x, each `row_h` square, and a
 * dim "+N" for whatever did not fit (#PANE_REF_THUMB_MAX or \a max_x, first
 * limit reached). Returns the x just past everything drawn, so a caller can
 * keep laying out. Null entries are skipped, never drawn as empty plates.
 */
float pane_ref_thumbs_paint(Image *const *images,
                            int count,
                            float x,
                            float row_ymin,
                            float row_h,
                            float max_x,
                            float u);

/**
 * Give \a but a tooltip it OWNS.
 *
 * `uiBut::tip` is a non-owning `StringRef` and `ui_def_but` stores it by
 * reference, so passing a catalog label, a local buffer, or an entry of an
 * `EnumPropertyItem` array the caller is about to `MEM_freeN` leaves the
 * button pointing at dead memory — an undefined tooltip on hover, and freed
 * bytes in the QA introspection dump (which broke the harness outright).
 * A string LITERAL is fine and needs no help; anything computed goes through
 * here, which copies it and hands ownership to the button.
 */
void pane_but_tooltip_owned(uiBut *but, const char *text);

/** \} */
