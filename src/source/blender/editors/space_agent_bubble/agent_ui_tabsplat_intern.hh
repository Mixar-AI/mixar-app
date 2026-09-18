/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Shared internals of the Gaussian Splat tab, split across
 * agent_ui_tabsplat.cc (controls), agent_ui_tabsplat_state.cc (catalog state),
 * and agent_ui_tabsplat_paint.cc (geometry + painting) under the 500-line rule.
 */

#pragma once
#include <string>
#include "BLI_rect.h"
#include "RNA_access.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct Image;

struct bContext;

/* Artboard-unit metrics measured from the "gaussian splats" frame (island
 * origin 267,340; deltas relative to the card panel's top-left at island
 * (2,201)).
 *
 * The params row's X positions are NOT design constants any more: the mode
 * and LOD labels come from the live catalog (`p_mode` / `p_lod`), so both
 * tracks use measured widths and bounded row flow. Oversized tracks become
 * dropdowns. The model chip is capped to one third of the available strip. */
#define SPLAT_THUMB_EDGE 45

#define SPLAT_ENUM_MAX 6

/* The job identity this pane submits under — `world_labs_queue.py`'s
 * `_SERVICE_KEY` / `FEATURE_WORLD_LABS`, which are the same string. Used for
 * queue feedback and the active model's Settings popup. */
#define SPLAT_SERVICE_KEY "world_labs"

struct SplatEnumItem {
  std::string ident;
  std::string label;
  bool active;
};

/** Resolved live state; valid only when splat_state_resolve returned true. */
struct SplatTabState {
  PointerRNA tab;    /* scene.mixie_moodboard_sidebar.tab_world_labs */
  PointerRNA params; /* wm.mixar_genparams_world_labs__<slug> */
  PropertyRNA *mode_prop;
  PropertyRNA *lod_prop;
  char model_slug[128];
  std::string model_label;
  char group_attr[192];
  char mode_ident[32];
  bool image_mode;
  bool use_selected;
  /* Live unified-queue work for this pane's service, from
   * `pane_active_job_count(C, SPLAT_SERVICE_KEY)`. This pane had NO busy
   * state at all: World Labs enqueues pass no `scene_flag`, so there is not
   * even a legacy flag to read, and Generate never acknowledged a click. */
  int active_jobs;
  /* The tab's OWN uploaded/captured input (tab_world_labs.reference_image).
   * Submitted when `use_selected` is off — see world_labs_ops _resolve_image. */
  Image *reference_image;
};

/**
 * Region-space rects for every element, built from the panel rect.
 *
 * Any rect in the bottom row may come back EMPTY (zero width): that run is
 * laid out left-to-right against the Generate button's left edge, and an
 * element that would cross it is dropped rather than drawn — and clicked —
 * over Generate. `splat_rect_is_live` is the one test; the painter and the
 * control layout must both use it.
 */
struct SplatPaneRects {
  rctf mode_track;
  rctf mode_seg[SPLAT_ENUM_MAX];
  int mode_count;
  bool mode_dropdown;
  rctf model_chip;
  rctf lod_track;
  rctf lod_seg[SPLAT_ENUM_MAX];
  int lod_count;
  bool lod_dropdown;
  rctf prompt_box;
  rctf prompt_field;
  /* False when the box left no room above the bottom row for a field. The
   * pane then offers neither the field nor Generate — a paid action must
   * never submit a prompt the user cannot see or edit. */
  bool prompt_ok;
  rctf chip_upload, chip_capture;
  rctf moodboard_switch;
  rctf thumbs; /* Left edge of the thumbnail run. */
  rctf btn_generate;
};

inline bool splat_rect_is_live(const rctf &r)
{
  return (r.xmax - r.xmin) > 1.0f;
}

bool splat_state_resolve(const bContext *C, SplatTabState *r_state);
/** Return the full choice count; copy only the first max_items for segment layout. */
int splat_enum_items_get(
    const bContext *C, PointerRNA *ptr, PropertyRNA *prop, SplatEnumItem *r_items, int max_items);

/* Board-selection collection and thumbnail drawing now live in the pane kit
 * (`pane_board_selected_images` / `pane_image_thumb_draw`) — every pane
 * previews its references the same way, so the Media pane no longer reaches
 * into this header for them. */

void splat_pane_rects_build(const rctf &panel,
                            float u,
                            const char *model_label,
                            const SplatEnumItem *mode_items,
                            int mode_count,
                            const SplatEnumItem *lod_items,
                            int lod_count,
                            SplatPaneRects *r_rects);
void splat_pane_paint(const bContext *C,
                      const SplatTabState &state,
                      const SplatPaneRects &rects,
                      float u);
/* Painter primitives live in the pane kit (agent_ui_pane_kit.hh). */

}  // namespace blender
