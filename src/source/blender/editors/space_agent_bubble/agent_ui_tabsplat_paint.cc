/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Gaussian Splat tab — geometry and painting. Everything is painted; the
 * uiBlocks laid by agent_ui_tabsplat.cc are invisible hit targets over this
 * art (the queue tab's pattern). Selected-moodboard thumbnails use the raw
 * ImBuf upload idiom from mixie_chat_footer_thumbnails.cc — NOT
 * BKE_image_get_gpu_texture, whose sRGB->Linear conversion washes the
 * preview out.
 */

#include <algorithm>
#include <cstring>

#include "BLF_api.hh"

#include "BKE_context.hh"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "DNA_image_types.h"
#include "DNA_scene_types.h"

#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"

#include "agent_ui_pane_kit.hh"
#include "agent_ui_tabsplat_intern.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* Painter primitives, the board-selection scan and the raw-ImBuf thumbnail
 * draw all come from the pane kit (`agent_ui_pane_kit.cc`) — the Media and 3D
 * panes preview their references the same way, and one definition keeps the
 * plate metrics from drifting between tabs. */

/* -------------------------------------------------------------------- */
/** \name Geometry
 * \{ */

void splat_pane_rects_build(const rctf &panel,
                            const float u,
                            const SplatEnumItem *mode_items,
                            const int mode_count,
                            const SplatEnumItem *lod_items,
                            const int lod_count,
                            SplatPaneRects *r)
{
  *r = {};

  /* One params row on the kit grid: mode toggle, model dropdown, LOD
   * segments — all metrics from the pane kit so this strip is pixel-equal
   * to the 3D and Media strips. */
  const float row_top = panel.ymax - PANE_STRIP_TOP * u;
  const float strip_x = panel.xmin + PANE_INSET_X * u;
  const float strip_max_x = panel.xmax - PANE_INSET_X * u;
  /* This pane's field stops ABOVE the bottom row (it paints monolithically,
   * so a full-box field would cover the chips), which costs the row's own
   * height on top of the kit's minimum before a field can exist at all. Never
   * lifted above the first row's own bottom: the box would then climb over
   * the strip it is supposed to sit under. A panel too short even for that
   * simply gets no field and no Generate (prompt_ok). */
  const float box_floor = std::min(
      pane_params_floor(panel, u) + (PANE_BOTTOM_UP + PANE_ROW_H + 8.0f) * u,
      row_top - PANE_ROW_H * u);

  /* Mode toggle from MEASURED labels. The design's fixed Text/Image split was
   * a stub: `p_mode`'s labels come from the live catalog and a longer one
   * spilled straight into the model chip (pane_label_centre never clips).
   * Same lesson the LOD track below already learned. */
  r->mode_count = std::min(mode_count, SPLAT_ENUM_MAX);
  float next_x = strip_x;
  if (r->mode_count > 0) {
    const char *labels[SPLAT_ENUM_MAX];
    for (int i = 0; i < r->mode_count; i++) {
      labels[i] = mode_items ? mode_items[i].label : "";
    }
    r->mode_track = pane_segmented_layout(
        strip_x, row_top, labels, r->mode_count, u, r->mode_seg);
    next_x = r->mode_track.xmax;
  }
  else {
    r->mode_track = {strip_x, strip_x, row_top - PANE_ROW_H * u, row_top};
  }

  const float model_x = next_x + PANE_CHIP_GAP * u;
  r->model_chip = {
      model_x, model_x + SPLAT_MODEL_W * u, row_top - PANE_ROW_H * u, row_top};

  /* Prompt box: strip bottom -> panel bottom (kit contract). The LOD track
   * may wrap the strip to a second row below, which shifts this. */
  float strip_bottom = row_top - PANE_ROW_H * u;

  /* LOD segments sized from their MEASURED labels — the catalog's labels
   * ("Balanced (500k)") are far longer than the design's Fast/Balanced/Max,
   * and an even split overlapped them. The track grows to fit, and is then
   * CLAMPED: with six catalog LODs it ran clean off the region. It wraps to
   * its own row where the prompt box can spare the height, and only drops
   * trailing segments when even a full row cannot hold them — a segment
   * painted past the panel edge is unclickable art. */
  r->lod_count = std::min(lod_count, SPLAT_ENUM_MAX);
  if (r->lod_count > 0) {
    const char *labels[SPLAT_ENUM_MAX];
    for (int i = 0; i < r->lod_count; i++) {
      labels[i] = lod_items ? lod_items[i].label : "";
    }
    const float lod_x = r->model_chip.xmax + PANE_CHIP_GAP * u;
    r->lod_track = pane_segmented_layout(lod_x, row_top, labels, r->lod_count, u, r->lod_seg);

    if (r->lod_track.xmax > strip_max_x) {
      const float row2_top = row_top - PANE_ROW_PITCH * u;
      if (row2_top - PANE_ROW_H * u >= box_floor) {
        r->lod_track = pane_segmented_layout(
            strip_x, row2_top, labels, r->lod_count, u, r->lod_seg);
        strip_bottom = row2_top - PANE_ROW_H * u;
      }
    }
    while (r->lod_count > 1 && r->lod_track.xmax > strip_max_x) {
      r->lod_count--;
      r->lod_track = pane_segmented_layout(
          r->lod_track.xmin, r->lod_track.ymax, labels, r->lod_count, u, r->lod_seg);
    }
  }
  else {
    r->lod_track = {strip_max_x, strip_max_x, row_top - PANE_ROW_H * u, row_top};
  }

  strip_bottom = std::max(strip_bottom, box_floor);
  r->prompt_box = pane_prompt_box_rect(panel, strip_bottom, u);
  /* Bottom row inside the box foot — the kit's shared rects. */
  const float chip_row_ymin = pane_bottom_row_ymin(r->prompt_box, u);
  r->btn_generate = pane_generate_rect(r->prompt_box, u);

  /* Field: the box above the chip row. This pane paints its bottom row in
   * the same monolithic pass as the box (before the field block is drawn),
   * so a full-box field chrome would cover the chips — unlike the other
   * panes, which paint their chips after the field draw. Multiline (top-left
   * text, text-height caret) engages regardless of the exact height.
   *
   * When there is no room above the row the field is simply NOT OFFERED. The
   * old fallback dropped it to `prompt_box.ymin`, i.e. straight over Upload /
   * Capture / the Moodboard switch — invisible chrome that still ate their
   * clicks. Generate is disabled with it (see prompt_ok). */
  r->prompt_field = r->prompt_box;
  r->prompt_field.ymin = chip_row_ymin + (PANE_ROW_H + 8.0f) * u;
  r->prompt_ok = (r->prompt_field.ymax - r->prompt_field.ymin) >= PANE_BOX_MIN_H * u;
  if (!r->prompt_ok) {
    r->prompt_field.ymin = r->prompt_field.ymax;
  }

  auto bottom_chip = [&](float x_px, float w_px) {
    rctf out;
    out.xmin = x_px;
    out.xmax = x_px + w_px;
    out.ymin = chip_row_ymin;
    out.ymax = chip_row_ymin + PANE_ROW_H * u;
    return out;
  };
  /* Chips sized from their MEASURED labels (the kit width), and the
   * label -> switch -> thumbs run flows left-to-right with measured gaps —
   * fixed artboard x's truncated "Upload Reference" mid-word and drove the
   * switch into the "Moodboard" label.
   *
   * The run is also CLAMPED against Generate's left edge: unclamped it just
   * accumulated rightward, and at a narrow island the switch and thumbs were
   * laid out UNDER the Generate button (only pane_ref_thumbs_paint honoured
   * a max_x). An element that will not fit is dropped, and everything after
   * it with it. */
  const float row_max_x = r->btn_generate.xmin - PANE_CHIP_GAP * u;
  float run_x = r->prompt_box.xmin + PANE_BOTTOM_IN_L * u;
  bool room = true;
  auto place = [&](float w_px, float gap_after) {
    rctf out = {0.0f, 0.0f, 0.0f, 0.0f};
    if (!room || run_x + w_px > row_max_x) {
      room = false;
      return out;
    }
    out = bottom_chip(run_x, w_px);
    run_x = out.xmax + gap_after;
    return out;
  };

  r->chip_upload = place(pane_action_chip_w("Upload Reference", true, u), PANE_CHIP_GAP * u);
  r->chip_capture = place(pane_action_chip_w("Capture Viewport", false, u), 18.0f * u);

  /* Label + switch travel together: a switch with no label beside it says
   * nothing, so both are dropped unless both fit. */
  const float switch_w = SPLAT_SWITCH_W * u;
  const float label_gap = 10.0f * u;
  const float label_avail = row_max_x - run_x - label_gap - switch_w;
  const float label_full = pane_text_width("Allow selected from Moodboard", PANE_FONT * u);
  if (room && label_avail > 0.0f) {
    const float label_x = run_x;
    const float label_w = std::min(label_full, label_avail);
    run_x += label_w + label_gap;
    r->moodboard_switch = place(switch_w, 12.0f * u);
    if (splat_rect_is_live(r->moodboard_switch)) {
      r->mood_label_x = label_x;
      r->mood_label_w = label_w;
      const float inset = (PANE_ROW_H - SPLAT_SWITCH_H) * 0.5f * u;
      r->moodboard_switch.ymin += inset;
      r->moodboard_switch.ymax -= inset;
    }
  }
  else {
    room = false;
  }

  r->thumbs = place(SPLAT_THUMB_EDGE * u, 0.0f);
  if (splat_rect_is_live(r->thumbs)) {
    r->thumbs.ymax = r->thumbs.ymin + SPLAT_THUMB_EDGE * u;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Painting
 * \{ */

void splat_pane_paint(const bContext *C,
                      const SplatTabState &state,
                      const SplatPaneRects &rects,
                      const SplatEnumItem *mode_items,
                      const int mode_count,
                      const SplatEnumItem *lod_items,
                      const int lod_count,
                      const float u)
{
  const float track[4] = PANE_COL_CHIP;
  const float thumb[4] = PANE_COL_PILL;
  const float text[4] = AGENT_COL_TEXT;
  const float dim[4] = AGENT_COL_TEXT_DIM;
  const float accent[4] = AGENT_COL_ACCENT;

  const float radius = PANE_RADIUS * u;
  const float font = PANE_FONT * u;

  /* Prompt box (pane kit; the wash is painted by the caller, which owns the
   * true panel rect). */
  pane_prompt_box_paint(rects.prompt_box, u);

  /* Mode toggle — segments sized from the catalog's own labels (see
   * splat_pane_rects_build), thumb over the active one. */
  pane_fill_round(&rects.mode_track, radius, track);
  for (int i = 0; i < mode_count && i < rects.mode_count; i++) {
    if (mode_items[i].active) {
      rctf th = rects.mode_seg[i];
      th.xmin += SPLAT_SEG_INSET * u;
      th.xmax -= SPLAT_SEG_INSET * u;
      th.ymin += SPLAT_SEG_INSET * u;
      th.ymax -= SPLAT_SEG_INSET * u;
      pane_fill_round(&th, radius, thumb);
    }
  }
  for (int i = 0; i < mode_count && i < rects.mode_count; i++) {
    pane_label_centre(mode_items[i].label,
                       BLI_rctf_cent_x(&rects.mode_seg[i]),
                       BLI_rctf_cent_y(&rects.mode_seg[i]),
                       font,
                       mode_items[i].active ? text : dim);
  }

  /* Model dropdown chip — the kit's, same as every pane's dropdowns. */
  {
    char label[144];
    BLI_strncpy(label,
                state.model_label[0] ? state.model_label : state.model_slug,
                sizeof(label));
    pane_fit_text(label, BLI_rctf_size_x(&rects.model_chip) - 50.0f * u, font);
    pane_dropdown_chip_paint(rects.model_chip, label, u);
  }

  /* LOD segmented control — the kit's, labels from the catalog schema. */
  if (lod_count > 0 && rects.lod_count > 0) {
    const char *lod_labels[SPLAT_ENUM_MAX];
    /* -1, not 0: a track clamped down to fit may have dropped the segment
     * that is actually active, and lighting the first one would be a lie. */
    int active_index = -1;
    for (int i = 0; i < rects.lod_count; i++) {
      lod_labels[i] = lod_items[i].label;
      if (lod_items[i].active) {
        active_index = i;
      }
    }
    pane_segmented_paint(rects.lod_seg, lod_labels, active_index, rects.lod_count, u);
  }

  /* Bottom row. Image-source controls exist only in image mode — the
   * moodboard drawer shows prompt-only UI in text mode. */
  if (state.image_mode) {
    const float row_cy = BLI_rctf_cent_y(&rects.btn_generate);
    const float max_x = rects.btn_generate.xmin - PANE_CHIP_GAP * u;

    /* Every element of this run may have been dropped for want of room (see
     * splat_pane_rects_build) — paint only what was actually placed. */
    if (splat_rect_is_live(rects.chip_upload)) {
      pane_action_chip_paint(rects.chip_upload, "Upload Reference", true, false, u);
    }
    if (splat_rect_is_live(rects.chip_capture)) {
      pane_action_chip_paint(rects.chip_capture, "Capture Viewport", false, false, u);
    }

    if (rects.mood_label_w > 0.0f) {
      char mood_label[64];
      BLI_strncpy(mood_label, "Allow selected from Moodboard", sizeof(mood_label));
      pane_fit_text(mood_label, rects.mood_label_w, font);
      pane_label_left(mood_label, rects.mood_label_x, row_cy, font, text);
    }

    /* Switch. */
    if (splat_rect_is_live(rects.moodboard_switch)) {
      const float knob_r = BLI_rctf_size_y(&rects.moodboard_switch) * 0.5f - 2.0f * u;
      pane_fill_round(&rects.moodboard_switch,
                      BLI_rctf_size_y(&rects.moodboard_switch) * 0.5f,
                      state.use_selected ? accent : track);
      rctf knob;
      const float kx = state.use_selected ?
                           rects.moodboard_switch.xmax - 2.0f * u - knob_r * 2.0f :
                           rects.moodboard_switch.xmin + 2.0f * u;
      knob.xmin = kx;
      knob.xmax = kx + knob_r * 2.0f;
      knob.ymin = BLI_rctf_cent_y(&rects.moodboard_switch) - knob_r;
      knob.ymax = BLI_rctf_cent_y(&rects.moodboard_switch) + knob_r;
      const float knob_col[4] = {0.95f, 0.95f, 0.95f, 1.0f};
      pane_fill_round(&knob, knob_r, knob_col);
    }

    /* Reference preview — whatever this tab will actually SUBMIT: the board
     * selection while the switch is on, otherwise its own uploaded/captured
     * image (world_labs_ops::_resolve_image reads exactly this way). Same
     * thumbnails the Agent tab shows for its pending attachments. */
    if (splat_rect_is_live(rects.thumbs)) {
      Image *images[PANE_REF_THUMB_MAX] = {nullptr};
      int count = 0;
      if (state.use_selected) {
        count = pane_board_selected_images(C, images, PANE_REF_THUMB_MAX);
      }
      else if (state.reference_image != nullptr) {
        images[count++] = state.reference_image;
      }
      const float thumb_h = BLI_rctf_size_y(&rects.thumbs);
      const float end_x = pane_ref_thumbs_paint(
          images, count, rects.thumbs.xmin, rects.thumbs.ymin, thumb_h, max_x, u);
      if (count == 0) {
        /* `PANE_FONT_SUB * u`, never AGENT_DU: AGENT_DU is window-width
         * independent while `u` scales with the island, so an AGENT_DU hint
         * was the one label in the pane that changed size relative to
         * everything around it as soon as the bubble was resized. */
        const float hint_font = PANE_FONT_SUB * u;
        const char *hint = state.use_selected ? "none selected" : "no image added";
        if (end_x + pane_text_width(hint, hint_font) <= max_x) {
          pane_label_left(hint, end_x, row_cy, hint_font, dim);
        }
      }
    }
  }

  /* ("Powered by World Labs" attribution removed per design revision.) */

  /* Newest operator report, in the gap above the box (kit helper — the ONE
   * definition, shared with the 3D and Media panes). The island window has no
   * status bar, so a refusal from `mixie.world_labs_generate` reached the user
   * nowhere at all before this. Drawn before the field block, like everything
   * else this pane paints — the field lives INSIDE the box, so its chrome
   * cannot cover a line drawn above it. */
  pane_report_line_draw(C, rects.prompt_box, u);

  /* Generate — the kit's shared button and the kit's shared label, so this
   * pane says "Queued (N)" in the same words as 3D and Media and counts the
   * queue the same way.
   *
   * Armed on `prompt_ok` ALONE, which is the rule the control layout applies
   * (agent_ui_tabsplat.cc): a live job is a QUEUE entry, not a lock, and
   * stacking is the point. Painting it disabled while busy was the one place
   * the paint and the arm disagreed — the button read "Queued..." and dimmed
   * but still submitted a paid world_labs generation on click, which is
   * exactly the failure the "a click and a keypress can never submit
   * different PAID generations" contract exists to prevent. The two rules
   * must be written from the same expression; they are now both prompt_ok. */
  char gen_label[32];
  pane_queue_label(gen_label, sizeof(gen_label), state.active_jobs);
  pane_generate_paint(rects.btn_generate, gen_label, rects.prompt_ok, u);
}

/** \} */

}  // namespace blender
