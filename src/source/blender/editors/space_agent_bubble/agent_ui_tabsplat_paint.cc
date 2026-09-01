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

#include "BIF_glutil.hh"

#include "BKE_context.hh"
#include "BKE_image.hh"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "DNA_image_types.h"
#include "DNA_scene_types.h"

#include "GPU_shader_builtin.hh"
#include "GPU_state.hh"

#include "IMB_imbuf.hh"
#include "IMB_imbuf_types.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"

#include "agent_ui_pane_kit.hh"
#include "agent_ui_tabsplat_intern.hh"
#include "agent_ui_theme.hh"

/* -------------------------------------------------------------------- */
/** \name Local paint helpers (queue-tab idiom, deliberately local)
 * \{ */

namespace {

/* Painter primitives come from the pane kit (agent_ui_pane_kit.cc); the two
 * helpers below are splat-specific (moodboard selection scan + raw-ImBuf
 * thumbnail draw, the mixie_chat_footer_thumbnails.cc idiom). */


/** Selected moodboard images, oldest first (board order). */

}  // namespace

/* Shared with the Media pane (declared in agent_ui_tabsplat_intern.hh). */
int splat_selected_moodboard_images(const bContext *C, Image **r_images, const int max_images)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return 0;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *items = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
  if (!items || RNA_property_type(items) != PROP_COLLECTION) {
    return 0;
  }
  int count = 0;
  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&scene_ptr, items, &iter);
  for (; iter.valid && count < max_images; RNA_property_collection_next(&iter)) {
    PointerRNA item = iter.ptr;
    PropertyRNA *sel = RNA_struct_find_property(&item, "selected");
    if (!sel || !RNA_property_boolean_get(&item, sel)) {
      continue;
    }
    PropertyRNA *img_prop = RNA_struct_find_property(&item, "image");
    if (!img_prop || RNA_property_type(img_prop) != PROP_POINTER) {
      continue;
    }
    PointerRNA img_ptr = RNA_property_pointer_get(&item, img_prop);
    if (img_ptr.data) {
      r_images[count++] = static_cast<Image *>(img_ptr.data);
    }
  }
  RNA_property_collection_end(&iter);
  return count;
}

void splat_draw_image_thumb(Image *image, const rctf &box)
{
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || ibuf->x <= 0 || ibuf->y <= 0) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return;
  }
  const float size_x = BLI_rctf_size_x(&box);
  const float size_y = BLI_rctf_size_y(&box);
  const float aspect = float(ibuf->x) / float(ibuf->y);
  float draw_w, draw_h;
  if (aspect > size_x / size_y) {
    draw_w = size_x;
    draw_h = size_x / aspect;
  }
  else {
    draw_h = size_y;
    draw_w = size_y * aspect;
  }
  const float draw_x = box.xmin + (size_x - draw_w) * 0.5f;
  const float draw_y = box.ymin + (size_y - draw_h) * 0.5f;

  IMMDrawPixelsTexState tex_state = immDrawPixelsTexSetup(GPU_SHADER_3D_IMAGE);
  GPU_blend(GPU_BLEND_ALPHA_PREMULT);
  if (ibuf->float_buffer.data) {
    immDrawPixelsTexScaledFullSize(&tex_state, draw_x, draw_y, ibuf->x, ibuf->y,
                                   blender::gpu::TextureFormat::SFLOAT_16_16_16_16, true,
                                   ibuf->float_buffer.data, draw_w / float(ibuf->x),
                                   draw_h / float(ibuf->y), 1.0f, 1.0f, nullptr);
  }
  else if (ibuf->byte_buffer.data) {
    immDrawPixelsTexScaledFullSize(&tex_state, draw_x, draw_y, ibuf->x, ibuf->y,
                                   blender::gpu::TextureFormat::UNORM_8_8_8_8, false,
                                   ibuf->byte_buffer.data, draw_w / float(ibuf->x),
                                   draw_h / float(ibuf->y), 1.0f, 1.0f, nullptr);
  }
  GPU_blend(GPU_BLEND_ALPHA);
  BKE_image_release_ibuf(image, ibuf, lock);
}


/** \} */

/* -------------------------------------------------------------------- */
/** \name Geometry
 * \{ */

void splat_pane_rects_build(const rctf &panel,
                            const float u,
                            const SplatEnumItem *lod_items,
                            const int lod_count,
                            SplatPaneRects *r)
{
  *r = {};
  const float top = panel.ymax;
  const float left = panel.xmin;

  auto box = [&](float dx, float dy, float w, float h) {
    rctf out;
    out.xmin = left + dx * u;
    out.xmax = out.xmin + w * u;
    out.ymax = top - dy * u;
    out.ymin = out.ymax - h * u;
    return out;
  };

  /* One params row on the kit grid: mode toggle, model dropdown, LOD
   * segments — all metrics from the pane kit so this strip is pixel-equal
   * to the 3D and Media strips. */
  const float row_top = top - PANE_STRIP_TOP * u;

  /* Mode toggle at the design stub widths (its two labels are near-fixed:
   * Text / Image); model chip and LOD track anchor off it. */
  r->mode_text = box(SPLAT_MODE_X, PANE_STRIP_TOP, SPLAT_MODE_SPLIT, PANE_ROW_H);
  r->mode_image = box(SPLAT_MODE_X + SPLAT_MODE_SPLIT,
                      PANE_STRIP_TOP,
                      SPLAT_MODE_W - SPLAT_MODE_SPLIT,
                      PANE_ROW_H);
  r->mode_track = box(SPLAT_MODE_X, PANE_STRIP_TOP, SPLAT_MODE_W, PANE_ROW_H);
  r->model_chip = box(SPLAT_MODEL_X, PANE_STRIP_TOP, SPLAT_MODEL_W, PANE_ROW_H);
  r->lod_track = box(SPLAT_LOD_X, PANE_STRIP_TOP, SPLAT_LOD_W, PANE_ROW_H);

  /* Prompt box: strip bottom -> panel bottom (kit contract). */
  const float strip_bottom = row_top - PANE_ROW_H * u;
  r->prompt_box = pane_prompt_box_rect(panel, strip_bottom, u);
  /* The field stops ABOVE the bottom row: this pane paints its chips in the
   * same monolithic pass as the box, so an embossed field spanning the whole
   * box would cover them (the kit invariant the other panes honour by
   * reordering; here the field simply keeps clear of the foot). */
  /* Bottom row inside the box foot — the kit's shared rects. */
  const float chip_row_ymin = pane_bottom_row_ymin(r->prompt_box, u);

  /* Field: the box above the chip row. This pane paints its bottom row in
   * the same monolithic pass as the box (before the field block is drawn),
   * so a full-box field chrome would cover the chips — unlike the other
   * panes, which paint their chips after the field draw. Multiline (top-left
   * text, text-height caret) engages regardless of the exact height. */
  r->prompt_field = r->prompt_box;
  r->prompt_field.ymin = chip_row_ymin + (PANE_ROW_H + 8.0f) * u;
  if (r->prompt_field.ymin > r->prompt_field.ymax) {
    r->prompt_field.ymin = r->prompt_box.ymin;
  }
  auto bottom_chip = [&](float x_px, float w_units) {
    rctf out;
    out.xmin = x_px;
    out.xmax = x_px + w_units * u;
    out.ymin = chip_row_ymin;
    out.ymax = chip_row_ymin + PANE_ROW_H * u;
    return out;
  };
  /* Chips sized from their MEASURED labels (the kit width), and the
   * label -> switch -> thumbs run flows left-to-right with measured gaps —
   * fixed artboard x's truncated "Upload Reference" mid-word and drove the
   * switch into the "Moodboard" label. */
  const float bx0 = r->prompt_box.xmin + PANE_BOTTOM_IN_L * u;
  const float upload_w_px = pane_action_chip_w("Upload Reference", true, u);
  const float capture_w_px = pane_action_chip_w("Capture Viewport", false, u);
  r->chip_upload = bottom_chip(bx0, upload_w_px / u);
  r->chip_capture = bottom_chip(r->chip_upload.xmax + PANE_CHIP_GAP * u, capture_w_px / u);
  r->mood_label_x = r->chip_capture.xmax + 18.0f * u;
  const float mood_label_w = pane_text_width("Allow selected from Moodboard", PANE_FONT * u);
  r->moodboard_switch = bottom_chip(r->mood_label_x + mood_label_w + 10.0f * u, SPLAT_SWITCH_W);
  {
    const float inset = (PANE_ROW_H - SPLAT_SWITCH_H) * 0.5f * u;
    r->moodboard_switch.ymin += inset;
    r->moodboard_switch.ymax -= inset;
  }
  r->thumbs = bottom_chip(r->moodboard_switch.xmax + 12.0f * u, SPLAT_THUMB_EDGE);
  r->thumbs.ymax = r->thumbs.ymin + SPLAT_THUMB_EDGE * u;
  r->btn_generate = pane_generate_rect(r->prompt_box, u);

  /* LOD segments sized from their MEASURED labels — the catalog's labels
   * ("Balanced (500k)") are far longer than the design's Fast/Balanced/Max,
   * and an even split overlapped them. The track grows to fit. */
  r->lod_count = std::min(lod_count, SPLAT_ENUM_MAX);
  if (r->lod_count > 0) {
    const char *labels[SPLAT_ENUM_MAX];
    for (int i = 0; i < r->lod_count; i++) {
      labels[i] = lod_items ? lod_items[i].label : "";
    }
    r->lod_track = pane_segmented_layout(
        r->lod_track.xmin, row_top, labels, r->lod_count, u, r->lod_seg);
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

  /* Mode toggle (Text / Image) — thumb over the active half. */
  pane_fill_round(&rects.mode_track, radius, track);
  const rctf *mode_rects[2] = {&rects.mode_text, &rects.mode_image};
  for (int i = 0; i < mode_count && i < 2; i++) {
    if (mode_items[i].active) {
      rctf th = *mode_rects[i];
      th.xmin += SPLAT_SEG_INSET * u;
      th.xmax -= SPLAT_SEG_INSET * u;
      th.ymin += SPLAT_SEG_INSET * u;
      th.ymax -= SPLAT_SEG_INSET * u;
      pane_fill_round(&th, radius, thumb);
    }
  }
  for (int i = 0; i < mode_count && i < 2; i++) {
    pane_label_centre(mode_items[i].label,
                       BLI_rctf_cent_x(mode_rects[i]),
                       BLI_rctf_cent_y(mode_rects[i]),
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
    int active_index = 0;
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
    pane_action_chip_paint(rects.chip_upload, "Upload Reference", true, false, u);

    /* Capture Viewport: painted per the design but INERT — the only existing
     * capture operator feeds chat attachments, which World Labs cannot
     * consume. Dimmed so it does not read as clickable. */
    pane_action_chip_paint(rects.chip_capture, "Capture Viewport", false, false, u);

    const float row_cy = BLI_rctf_cent_y(&rects.chip_upload);
    pane_label_left("Allow selected from Moodboard",
                    rects.mood_label_x,
                    row_cy,
                    font,
                    text);

    /* Switch. */
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

    /* Selected-image thumbnails + overflow count (only meaningful while the
     * switch is on). */
    if (state.use_selected) {
      Image *images[8] = {nullptr};
      const int selected = splat_selected_moodboard_images(C, images, 8);
      const int show = std::min(selected, 2);
      float x = rects.thumbs.xmin;
      for (int i = 0; i < show; i++) {
        rctf t;
        t.xmin = x;
        t.xmax = x + SPLAT_THUMB_EDGE * u;
        t.ymin = rects.thumbs.ymin;
        t.ymax = rects.thumbs.ymax;
        pane_fill_round(&t, 6.0f * u, track);
        splat_draw_image_thumb(images[i], t);
        x = t.xmax + SPLAT_THUMB_GAP * u;
      }
      if (selected > show) {
        char more[24];
        SNPRINTF(more, "+%d more", selected - show);
        pane_label_left(more, x + 4.0f * u, row_cy, AGENT_DU(15), dim);
      }
      else if (selected == 0) {
        pane_label_left("none selected", x, row_cy, AGENT_DU(15), dim);
      }
    }
  }

  /* ("Powered by World Labs" attribution removed per design revision.) */

  /* Generate — the kit's shared button. */
  pane_generate_paint(rects.btn_generate, "Generate", true, u);
}

/** \} */
