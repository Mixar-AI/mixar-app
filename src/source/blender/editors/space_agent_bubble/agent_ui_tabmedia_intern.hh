/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Internals shared between the Media pane's two translation units
 * (agent_ui_tabmedia.cc draws; agent_ui_tabmedia_util.cc holds the paint
 * helpers, RNA plumbing and chip model). Split under the 500-line rule.
 */

#pragma once

#include "BLI_rect.h"
#include "RNA_access.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct Image;
struct Scene;
struct bContext;

/* -------------------------------------------------------------------- */
/** \name Metrics (island units) and local palette
 * \{ */

/* Metrics/colours come from the pane kit (agent_ui_pane_kit.hh). */
#define MEDIA_MAX_CHIPS 10


/* -------------------------------------------------------------------- */
/* Paint helpers (BLF/GPU idioms shared with the queue pane's statics). */

/* Painter primitives live in the pane kit (agent_ui_pane_kit.hh). */

/* -------------------------------------------------------------------- */
/* RNA plumbing. */

/** engine.py's `_sanitize`: every non-word char becomes '_'. */
void media_sanitize_key(const char *in, char *out, int out_len);
/** Resolve `scene.mixie_moodboard_sidebar.<tab_prop>`; false when missing. */
bool media_sidebar_tab_ptr(Scene *scene, const char *tab_prop, PointerRNA *r_ptr);
/** Current enum identifier + display label of `prop_name` on *ptr*. */
bool media_read_enum(const bContext *C, PointerRNA *ptr, const char *prop_name, char r_ident[64], char r_label[64]);
bool media_ident_is_placeholder(const char *ident);

/* -------------------------------------------------------------------- */
/* Param chip model. */

enum class MediaChipKind { Enum, Bool, Int };

struct MediaParamChip {
  MediaChipKind kind;
  char prop_id[64];   /* RNA identifier on its owner ("model", "p_style"). */
  char label[64];     /* Property display name. */
  char value[64];     /* Current value text (enum label / int). */
  bool bool_value;
  /* true = the catalog group on WindowManager (data_path targets it);
   * false = the tab group on Scene. */
  bool on_wm_group;
  rctf rect;          /* Laid-out rect (region px), filled by the layout pass. */
};

/** All `p_*` params of the catalog group into chips (enums/bools/ints;
 * floats/strings skipped — the N-panel stays the full-fidelity surface).
 * `visible_if` lives only in the Python schema and is not evaluated here. */
int media_gather_param_chips(const bContext *C,
                             PointerRNA *group,
                             MediaParamChip *chips,
                             int max_chips,
                             int *r_total);
float media_chip_width(const MediaParamChip &chip, float u, float font, float font_sub);

/** Paint \a count already-laid-out chips (enum value + chevron, ON/OFF pill,
 * -/+ stepper). Art only — the pane file lays them out and wires the buttons. */
void media_param_chips_paint(
    const MediaParamChip *chips, int count, float u, float font, float font_sub);

/**
 * The images this half will actually SUBMIT, for the bottom row's preview.
 *
 * Image half: `use_reference_images` ON means the board selection is the
 * source, OFF means the tab's own uploads are (imagegen_ops.py reads it
 * exactly this way, and the uploader flips it off when it adds one). Video
 * half: Video Gen has no reference property of its own — its references ARE
 * the selected board media — so it always previews those, as does an
 * unresolved tab (\a tab null).
 */
int media_collect_reference_images(
    const bContext *C, PointerRNA *tab_ptr, bool video, Image **r_images, int max_images);

}  // namespace blender
