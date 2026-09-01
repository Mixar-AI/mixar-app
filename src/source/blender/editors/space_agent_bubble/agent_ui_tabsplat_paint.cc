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

#include "agent_ui_tabsplat_intern.hh"
#include "agent_ui_theme.hh"

/* -------------------------------------------------------------------- */
/** \name Local paint helpers (queue-tab idiom, deliberately local)
 * \{ */

namespace {

void s_fill_round(const rctf *rect, const float radius, const float col[4])
{
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(rect, true, radius, col);
}

int s_font()
{
  return BLF_default();
}

float s_text_width(const char *text, const float size)
{
  const int font = s_font();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}

void s_label_left(
    const char *text, const float x, const float cy, const float size, const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  const int font = s_font();
  BLF_size(font, size);
  BLF_disable(font, BLF_CLIPPING);
  rcti box;
  BLF_boundbox(font, text, strlen(text), &box);
  const float baseline = cy - float(box.ymin + box.ymax) * 0.5f;
  BLF_color4fv(font, col);
  BLF_position(font, x, baseline, 0.0f);
  BLF_draw(font, text, strlen(text));
}

/** Selected moodboard images, oldest first (board order). */
int selected_moodboard_images(const bContext *C, Image **r_images, const int max_images)
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

void draw_image_thumb(Image *image, const rctf &box)
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

}  // namespace

void splat_label_centre(
    const char *text, const float cx, const float cy, const float size, const float col[4])
{
  s_label_left(text, cx - s_text_width(text, size) * 0.5f, cy, size, col);
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

  r->mode_track = box(SPLAT_MODE_X, SPLAT_PARAMS_Y, SPLAT_MODE_W, SPLAT_ROW_H);
  r->mode_text = box(SPLAT_MODE_X, SPLAT_PARAMS_Y, SPLAT_MODE_SPLIT, SPLAT_ROW_H);
  r->mode_image = box(SPLAT_MODE_X + SPLAT_MODE_SPLIT,
                      SPLAT_PARAMS_Y,
                      SPLAT_MODE_W - SPLAT_MODE_SPLIT,
                      SPLAT_ROW_H);
  r->model_chip = box(SPLAT_MODEL_X, SPLAT_PARAMS_Y, SPLAT_MODEL_W, SPLAT_ROW_H);
  r->lod_track = box(SPLAT_LOD_X, SPLAT_PARAMS_Y, SPLAT_LOD_W, SPLAT_ROW_H);

  const float box_h = (panel.ymax - panel.ymin) / u - SPLAT_BOX_Y - SPLAT_BOX_INSET_X;
  r->prompt_box = box(SPLAT_BOX_INSET_X,
                      SPLAT_BOX_Y,
                      (panel.xmax - panel.xmin) / u - SPLAT_BOX_INSET_X * 2,
                      box_h);
  /* Field spans the box above the (bottom-anchored) chip row, 8-unit gap. */
  const float field_h = ((panel.ymax - panel.ymin) / u - SPLAT_ROW_H - SPLAT_BOX_INSET_X) - 8 -
                        SPLAT_BOX_Y;
  r->prompt_field = box(SPLAT_BOX_INSET_X + 8,
                        SPLAT_BOX_Y + 4,
                        (panel.xmax - panel.xmin) / u - (SPLAT_BOX_INSET_X + 8) * 2,
                        field_h);

  /* Chip row anchored to the PANEL BOTTOM, not the artboard's fixed offset —
   * the default window's panel is shorter than the design frame's, and the
   * fixed 302-unit offset pushed the whole row past the panel edge. */
  const float panel_h_units = (panel.ymax - panel.ymin) / u;
  const float chip_row_y = panel_h_units - SPLAT_ROW_H - SPLAT_BOX_INSET_X;
  r->chip_upload = box(SPLAT_CHIP_UPLOAD_X, chip_row_y, SPLAT_CHIP_UPLOAD_W, SPLAT_ROW_H);
  r->chip_capture = box(
      SPLAT_CHIP_CAPTURE_X, chip_row_y, SPLAT_CHIP_CAPTURE_W, SPLAT_ROW_H);
  r->moodboard_switch = box(SPLAT_SWITCH_X,
                            chip_row_y + (SPLAT_ROW_H - SPLAT_SWITCH_H) * 0.5f,
                            SPLAT_SWITCH_W,
                            SPLAT_SWITCH_H);
  r->thumbs = box(SPLAT_THUMB_X,
                  chip_row_y - 1,
                  SPLAT_THUMB_EDGE,
                  SPLAT_THUMB_EDGE);
  r->btn_generate = box(SPLAT_GEN_X, chip_row_y, SPLAT_GEN_W, SPLAT_ROW_H);

  /* LOD segments sized from their MEASURED labels — the catalog's labels
   * ("Balanced (500k)") are far longer than the design's Fast/Balanced/Max,
   * and an even split overlapped them. The track grows to fit. */
  r->lod_count = std::min(lod_count, SPLAT_ENUM_MAX);
  if (r->lod_count > 0) {
    const float font = AGENT_DU(AGENT_CHIP_FONT);
    const float pad = 14.0f * u;
    float x = r->lod_track.xmin;
    for (int i = 0; i < r->lod_count; i++) {
      const float w = s_text_width(lod_items ? lod_items[i].label : "", font) + pad * 2.0f;
      rctf seg = r->lod_track;
      seg.xmin = x;
      seg.xmax = x + w;
      r->lod_seg[i] = seg;
      x = seg.xmax;
    }
    r->lod_track.xmax = x;
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
  const float track[4] = {0.192f, 0.192f, 0.192f, 1.0f};  /* #313131 */
  const float thumb[4] = {0.282f, 0.282f, 0.282f, 1.0f};  /* #484848 */
  const float chip[4] = AGENT_COL_CHIP;
  const float generate[4] = AGENT_COL_GENERATE;
  const float text[4] = AGENT_COL_TEXT;
  const float dim[4] = AGENT_COL_TEXT_DIM;
  const float accent[4] = AGENT_COL_ACCENT;

  const float radius = SPLAT_ROW_RADIUS * u;
  const float font = AGENT_DU(SPLAT_FONT);

  /* Prompt box — a slightly recessed slab inside the panel. */
  const float box_col[4] = {0.051f, 0.051f, 0.051f, 1.0f}; /* #0D0D0D */
  s_fill_round(&rects.prompt_box, 28.0f * u, box_col);

  /* Mode toggle (Text / Image) — thumb over the active half. */
  s_fill_round(&rects.mode_track, radius, track);
  const rctf *mode_rects[2] = {&rects.mode_text, &rects.mode_image};
  for (int i = 0; i < mode_count && i < 2; i++) {
    if (mode_items[i].active) {
      rctf th = *mode_rects[i];
      th.xmin += SPLAT_SEG_INSET * u;
      th.xmax -= SPLAT_SEG_INSET * u;
      th.ymin += SPLAT_SEG_INSET * u;
      th.ymax -= SPLAT_SEG_INSET * u;
      s_fill_round(&th, radius, thumb);
    }
  }
  for (int i = 0; i < mode_count && i < 2; i++) {
    splat_label_centre(mode_items[i].label,
                       BLI_rctf_cent_x(mode_rects[i]),
                       BLI_rctf_cent_y(mode_rects[i]),
                       font,
                       mode_items[i].active ? text : dim);
  }

  /* Model dropdown chip: current catalog model label + chevron. */
  s_fill_round(&rects.model_chip, radius, track);
  {
    char label[144];
    SNPRINTF(label,
             "%s  \xE2\x8C\x84", /* U+2304 down arrowhead. */
             state.model_label[0] ? state.model_label : state.model_slug);
    splat_label_centre(label,
                       BLI_rctf_cent_x(&rects.model_chip),
                       BLI_rctf_cent_y(&rects.model_chip),
                       font,
                       text);
  }

  /* LOD segmented control — labels from the catalog schema. */
  s_fill_round(&rects.lod_track, radius, track);
  {
    for (int i = 0; i < lod_count && i < rects.lod_count; i++) {
      const rctf &seg = rects.lod_seg[i];
      if (lod_items[i].active) {
        rctf th = seg;
        th.xmin += SPLAT_SEG_INSET * u;
        th.xmax -= SPLAT_SEG_INSET * u;
        th.ymin += SPLAT_SEG_INSET * u;
        th.ymax -= SPLAT_SEG_INSET * u;
        s_fill_round(&th, radius, thumb);
      }
      splat_label_centre(lod_items[i].label,
                         BLI_rctf_cent_x(&seg),
                         BLI_rctf_cent_y(&seg),
                         font,
                         lod_items[i].active ? text : dim);
    }
  }

  /* Bottom row. Image-source controls exist only in image mode — the
   * moodboard drawer shows prompt-only UI in text mode. */
  if (state.image_mode) {
    s_fill_round(&rects.chip_upload, radius, chip);
    splat_label_centre("Upload Reference",
                       BLI_rctf_cent_x(&rects.chip_upload),
                       BLI_rctf_cent_y(&rects.chip_upload),
                       font,
                       text);

    /* Capture Viewport: painted per the design but INERT — the only existing
     * capture operator feeds chat attachments, which World Labs cannot
     * consume. Dimmed so it does not read as clickable. */
    s_fill_round(&rects.chip_capture, radius, chip);
    splat_label_centre("Capture Viewport",
                       BLI_rctf_cent_x(&rects.chip_capture),
                       BLI_rctf_cent_y(&rects.chip_capture),
                       font,
                       dim);

    const float row_cy = BLI_rctf_cent_y(&rects.chip_upload);
    s_label_left("Allow selected from Moodboard",
                 rects.prompt_box.xmin + (SPLAT_MOOD_LABEL_X - SPLAT_BOX_INSET_X) * u,
                 row_cy,
                 font,
                 text);

    /* Switch. */
    const float knob_r = BLI_rctf_size_y(&rects.moodboard_switch) * 0.5f - 2.0f * u;
    s_fill_round(&rects.moodboard_switch,
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
    s_fill_round(&knob, knob_r, knob_col);

    /* Selected-image thumbnails + overflow count (only meaningful while the
     * switch is on). */
    if (state.use_selected) {
      Image *images[8] = {nullptr};
      const int selected = selected_moodboard_images(C, images, 8);
      const int show = std::min(selected, 2);
      float x = rects.thumbs.xmin;
      for (int i = 0; i < show; i++) {
        rctf t;
        t.xmin = x;
        t.xmax = x + SPLAT_THUMB_EDGE * u;
        t.ymin = rects.thumbs.ymin;
        t.ymax = rects.thumbs.ymax;
        s_fill_round(&t, 6.0f * u, track);
        draw_image_thumb(images[i], t);
        x = t.xmax + SPLAT_THUMB_GAP * u;
      }
      if (selected > show) {
        char more[24];
        SNPRINTF(more, "+%d more", selected - show);
        s_label_left(more, x + 4.0f * u, row_cy, AGENT_DU(15), dim);
      }
      else if (selected == 0) {
        s_label_left("none selected", x, row_cy, AGENT_DU(15), dim);
      }
    }
  }

  /* Powered by World Labs — dim attribution left of Generate. */
  {
    const char *powered = "Powered by  World Labs";
    const float w = s_text_width(powered, AGENT_DU(15));
    s_label_left(powered,
                 rects.btn_generate.xmin - 24.0f * u - w,
                 BLI_rctf_cent_y(&rects.btn_generate),
                 AGENT_DU(15),
                 dim);
  }

  /* Generate. */
  s_fill_round(&rects.btn_generate, radius, generate);
  splat_label_centre("Generate",
                     BLI_rctf_cent_x(&rects.btn_generate),
                     BLI_rctf_cent_y(&rects.btn_generate),
                     font,
                     text);
}

/** \} */
