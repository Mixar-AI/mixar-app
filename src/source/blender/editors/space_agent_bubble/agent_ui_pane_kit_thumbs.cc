/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The pane kit's reference-thumbnail half: reading the moodboard's selected
 * images and painting a run of them.
 *
 * Split out of `agent_ui_pane_kit.cc` only to keep both inside the 500-line
 * rule — there is no second concept here. It is also the only part of the kit
 * that touches `Image`/`ImBuf`, so those includes stay on this side.
 */

#include <algorithm>

#include "BKE_context.hh"
#include "BKE_image.hh"

#include "BLI_rect.h"
#include "BLI_string.h"

#include "DNA_image_types.h"
#include "DNA_scene_types.h"

#include "BIF_glutil.hh"

#include "GPU_shader_builtin.hh"
#include "GPU_state.hh"

#include "IMB_imbuf.hh"
#include "IMB_imbuf_types.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "agent_ui_pane_kit.hh"
#include "agent_ui_theme.hh"

/* -------------------------------------------------------------------- */
/** \name Reference thumbnails
 * \{ */

int pane_board_selected_images(const bContext *C, Image **r_images, const int max_images)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene || max_images <= 0) {
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

void pane_image_thumb_draw(Image *image, const rctf &box)
{
  if (image == nullptr) {
    return;
  }
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || ibuf->x <= 0 || ibuf->y <= 0) {
    /* Release even on the failure path — acquire always pairs with release. */
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

float pane_ref_thumbs_paint(Image *const *images,
                            const int count,
                            const float x,
                            const float row_ymin,
                            const float row_h,
                            const float max_x,
                            const float u)
{
  if (images == nullptr || count <= 0) {
    return x;
  }
  const float back[4] = PANE_COL_CHIP;
  const float dim[4] = AGENT_COL_TEXT_DIM;
  const float gap = PANE_REF_THUMB_GAP * u;

  float tx = x;
  int shown = 0;
  for (int i = 0; i < count && shown < PANE_REF_THUMB_MAX; i++) {
    if (images[i] == nullptr) {
      continue;
    }
    /* Stop before the run would reach whatever sits to its right (Generate),
     * and let the "+N" below account for the rest. */
    if (tx + row_h > max_x) {
      break;
    }
    rctf t;
    t.xmin = tx;
    t.xmax = tx + row_h;
    t.ymin = row_ymin;
    t.ymax = row_ymin + row_h;
    pane_fill_round(&t, PANE_REF_THUMB_RADIUS * u, back);
    pane_image_thumb_draw(images[i], t);
    tx = t.xmax + gap;
    shown++;
  }

  if (shown < count) {
    char more[24];
    SNPRINTF(more, "+%d", count - shown);
    pane_label_left(more, tx + 2.0f * u, row_ymin + row_h * 0.5f, PANE_FONT_SUB * u, dim);
    tx += pane_text_width(more, PANE_FONT_SUB * u) + gap;
  }
  return tx;
}

/** \} */

