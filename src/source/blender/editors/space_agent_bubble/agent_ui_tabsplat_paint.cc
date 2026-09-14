/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Gaussian Splat tab — measured geometry, surfaces and reference previews.
 * Native controls in agent_ui_tabsplat.cc own their presentation and targets.
 * Selected-moodboard thumbnails use the raw
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

#include "UI_mixar_tokens.hh"
#include "UI_mixar_layout.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_tabsplat_intern.hh"

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
                            const char *model_label,
                            const SplatEnumItem *mode_items,
                            const int mode_count,
                            const SplatEnumItem *lod_items,
                            const int lod_count,
                            SplatPaneRects *r)
{
  *r = {};

  const float row_top = panel.ymax - PANE_STRIP_TOP * u;
  const float strip_x = panel.xmin + PANE_INSET_X * u;
  const float strip_max_x = panel.xmax - (PANE_INSET_X + PANE_SETTINGS_W + PANE_CHIP_GAP) * u;
  const float box_floor = std::min(pane_params_floor(panel, u), row_top - PANE_ROW_H * u);
  ui::MixarFlow flow;
  flow.x = flow.x0 = strip_x;
  flow.x_max = strip_max_x;
  flow.y_top = row_top;
  flow.y_floor = box_floor;
  flow.row_height = PANE_ROW_H * u;
  flow.row_pitch = PANE_ROW_PITCH * u;
  flow.gap = PANE_CHIP_GAP * u;

  auto place_param = [&](float width, rctf &rect) {
    ui::MixarFlowRect placed;
    if (!flow.place(width, placed)) {
      return false;
    }
    rect = {placed.xmin, placed.xmax, placed.ymin, placed.ymax};
    return true;
  };
  auto choice = [&](const SplatEnumItem *items, int count, rctf &track,
                    rctf *segments, int &visible_count, bool &dropdown) {
    if (count <= 0) {
      return;
    }
    const char *labels[SPLAT_ENUM_MAX];
    float width = 0;
    if (count <= SPLAT_ENUM_MAX) {
      for (int i = 0; i < count; i++) {
        labels[i] = items[i].label.c_str();
      }
      const rctf measured = pane_segmented_layout(0, 0, labels, count, u, segments);
      width = BLI_rctf_size_x(&measured);
    }
    dropdown = count > SPLAT_ENUM_MAX || width > strip_max_x - strip_x;
    if (!place_param(dropdown ? 360.0f * u : width, track)) {
      return; /* The full schema is still available in Settings. */
    }
    if (!dropdown) {
      visible_count = count;
      pane_segmented_layout(track.xmin, track.ymax, labels, count, u, segments);
    }
  };
  choice(mode_items, mode_count, r->mode_track, r->mode_seg, r->mode_count, r->mode_dropdown);
  const float model_w = std::min(pane_dropdown_chip_w(model_label, u),
                                 (strip_max_x - strip_x) / 3.0f);
  place_param(model_w, r->model_chip);
  choice(lod_items, lod_count, r->lod_track, r->lod_seg, r->lod_count, r->lod_dropdown);

  float strip_bottom = flow.y_top - PANE_ROW_H * u;
  strip_bottom = std::max(strip_bottom, box_floor);
  r->prompt_box = pane_prompt_box_rect(panel, strip_bottom, u);
  /* Bottom row inside the box foot — the kit's shared rects. */
  const float chip_row_ymin = pane_bottom_row_ymin(r->prompt_box, u);
  r->btn_generate = pane_generate_rect(r->prompt_box, u);

  r->prompt_field = pane_prompt_field_rect(r->prompt_box, u);
  r->prompt_ok = pane_prompt_fits(r->prompt_box, u);

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

  /* One shared Toggle contains its label and ON/OFF state. Reserve its
   * measured native recipe before placing previews; never overlap Generate. */
  const float toggle_w = pane_text_width("Use Moodboard", PANE_FONT * u) +
                         pane_text_width("ON", PANE_FONT * u) +
                         pane_text_width("OFF", PANE_FONT * u) +
                         (2 * ui::mixar_tokens::padding + 52.0f) * u;
  r->moodboard_switch = place(toggle_w, 12.0f * u);

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
                      const float u)
{
  const float *dim = ui::mixar_tokens::zen.secondary;

  /* Prompt box (pane kit; the wash is painted by the caller, which owns the
   * true panel rect). */
  pane_prompt_box_paint(rects.prompt_box, u);

  /* Bottom row. Image-source controls exist only in image mode — the
   * moodboard drawer shows prompt-only UI in text mode. */
  if (state.image_mode) {
    const float row_cy = BLI_rctf_cent_y(&rects.btn_generate);
    const float max_x = rects.btn_generate.xmin - PANE_CHIP_GAP * u;

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
}

/** \} */

}  // namespace blender
