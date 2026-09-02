/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Implementation of the island pane kit — see agent_ui_pane_kit.hh for the
 * vocabulary, sources and the layout contract.
 */

#include <algorithm>
#include <cstring>
#include <string>

#include "MEM_guardedalloc.h"

#include "BLF_api.hh"

#include "BIF_glutil.hh"

#include "BKE_context.hh"
#include "BKE_image.hh"

#include "BLI_rect.h"
#include "BLI_string.h"

#include "DNA_image_types.h"
#include "DNA_scene_types.h"

#include "GPU_shader_builtin.hh"
#include "GPU_state.hh"

#include "IMB_imbuf.hh"
#include "IMB_imbuf_types.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "agent_ui_icons.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_theme.hh"

/* -------------------------------------------------------------------- */
/** \name Primitives
 * \{ */

void pane_fill_round(const rctf *rect, const float radius, const float col[4])
{
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(rect, true, radius, col);
}

float pane_text_width(const char *text, const float size)
{
  const int font = BLF_default();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}

void pane_label_left(
    const char *text, const float x, const float cy, const float size, const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  const int font = BLF_default();
  BLF_size(font, size);
  BLF_disable(font, BLF_CLIPPING);

  rcti box;
  BLF_boundbox(font, text, strlen(text), &box);
  const float baseline = cy - float(box.ymin + box.ymax) * 0.5f;

  BLF_color4fv(font, col);
  BLF_position(font, x, baseline, 0.0f);
  BLF_draw(font, text, strlen(text));
}

void pane_label_centre(
    const char *text, const float cx, const float cy, const float size, const float col[4])
{
  pane_label_left(text, cx - pane_text_width(text, size) * 0.5f, cy, size, col);
}

void pane_label_right(
    const char *text, const float x, const float cy, const float size, const float col[4])
{
  pane_label_left(text, x - pane_text_width(text, size), cy, size, col);
}

void pane_fit_text(char *text, const float max_w, const float size)
{
  if (pane_text_width(text, size) <= max_w) {
    return;
  }
  size_t len = strlen(text);
  while (len > 1) {
    len--;
    /* Never split a UTF-8 sequence: back up over continuation bytes. */
    while (len > 1 && ((unsigned char)(text[len]) & 0xC0) == 0x80) {
      len--;
    }
    text[len] = '\0';
    if (pane_text_width(text, size) <= max_w) {
      break;
    }
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Composites
 * \{ */

void pane_wash_paint(const rctf &panel, const float u)
{
  const float top[4] = PANE_COL_WASH_TOP;
  const float bottom[4] = PANE_COL_WASH_BOTTOM;
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  /* Vertical stand-in for the frames' near-vertical gradient; the diagonal
   * component is imperceptible at this delta. */
  UI_draw_roundbox_4fv_ex(&panel, bottom, top, 1.0f, nullptr, 0.0f, AGENT_PANEL_RADIUS * u);
}

rctf pane_prompt_box_rect(const rctf &panel, const float strip_bottom_y, const float u)
{
  rctf box;
  box.xmin = panel.xmin + PANE_BOX_INSET * u;
  box.xmax = panel.xmax - PANE_BOX_INSET * u;
  box.ymax = strip_bottom_y - PANE_BOX_GAP * u;
  box.ymin = panel.ymin + PANE_BOX_INSET * u;
  /* Never below the region edge: the panel's bottom inset lives inside the
   * TOOLS card-foot band, so panel.ymin can be slightly NEGATIVE in this
   * region's coordinates — a box (and its bottom row) placed from it then
   * paints below y=0 and is scissored off. 2px keeps the box's rounded foot
   * visible in every geometry. */
  if (box.ymin < 2.0f) {
    box.ymin = 2.0f;
  }
  if (box.ymax < box.ymin) {
    box.ymax = box.ymin;
  }
  return box;
}

rctf pane_prompt_field_rect(const rctf &box, const float u)
{
  /* The field IS the whole box — the design's prompt area. Blender's
   * multiline text path (Text + UI_BUT_TEXTEDIT_UPDATE + tall rect) renders
   * top-left with a text-height caret, so no strip-sizing is needed; a
   * top-strip variant was tried and read as "just a thin bar". */
  UNUSED_VARS(u);
  return box;
}

void pane_prompt_box_paint(const rctf &box, const float u)
{
  if (BLI_rctf_size_y(&box) <= 1.0f) {
    return;
  }
  const float col[4] = PANE_COL_BOX;
  pane_fill_round(&box, PANE_BOX_RADIUS * u, col);
}

float pane_bottom_row_ymin(const rctf &box, const float u)
{
  return box.ymin + PANE_BOTTOM_UP * u;
}

rctf pane_generate_rect(const rctf &box, const float u)
{
  rctf rect;
  rect.xmax = box.xmax - PANE_BOTTOM_IN_R * u;
  rect.xmin = rect.xmax - PANE_GENERATE_W * u;
  rect.ymin = pane_bottom_row_ymin(box, u);
  rect.ymax = rect.ymin + PANE_ROW_H * u;
  return rect;
}

void pane_generate_paint(const rctf &rect, const char *label, const bool enabled, const float u)
{
  const float fill[4] = PANE_COL_GENERATE;
  const float strong[4] = AGENT_COL_TEXT_STRONG;
  const float dim[4] = AGENT_COL_TEXT_DIM;
  pane_fill_round(&rect, PANE_RADIUS * u, fill);
  pane_label_centre(label,
                    BLI_rctf_cent_x(&rect),
                    BLI_rctf_cent_y(&rect),
                    PANE_FONT * u,
                    enabled ? strong : dim);
}

float pane_action_chip_w(const char *label, const bool with_icon, const float u)
{
  const float pad = PANE_CHIP_PAD_X * u;
  const float icon = with_icon ? (AGENT_CHIP_ICON * u + AGENT_CHIP_ICON_GAP * u) : 0.0f;
  return pad + icon + pane_text_width(label, PANE_FONT * u) + pad;
}

void pane_action_chip_paint(
    const rctf &rect, const char *label, const bool with_icon, const bool dim, const float u)
{
  const float fill[4] = PANE_COL_ACTION;
  const float text[4] = AGENT_COL_TEXT;
  const float text_dim[4] = AGENT_COL_TEXT_DIM;
  pane_fill_round(&rect, PANE_RADIUS * u, fill);
  const float cy = BLI_rctf_cent_y(&rect);
  float x = rect.xmin + PANE_CHIP_PAD_X * u;
  if (with_icon) {
    const float edge = AGENT_CHIP_ICON * u;
    rctf icon = {x, x + edge, cy - edge * 0.5f, cy + edge * 0.5f};
    agent_ui_icon_draw(AGENT_ICON_IMAGE, &icon, dim ? text_dim : text, fill);
    x += edge + AGENT_CHIP_ICON_GAP * u;
  }
  pane_label_left(label, x, cy, PANE_FONT * u, dim ? text_dim : text);
}

float pane_dropdown_chip_w(const char *label, const float u)
{
  const float pad = PANE_CHIP_PAD_X * u;
  const float chev = AGENT_CHIP_ICON * u * 0.8f;
  return pad + pane_text_width(label, PANE_FONT * u) + 10.0f * u + chev + pad * 0.75f;
}

void pane_dropdown_chip_paint(const rctf &rect, const char *label, const float u)
{
  const float fill[4] = PANE_COL_CHIP;
  const float text[4] = AGENT_COL_TEXT;
  pane_fill_round(&rect, PANE_RADIUS * u, fill);
  const float cy = BLI_rctf_cent_y(&rect);
  pane_label_left(label, rect.xmin + PANE_CHIP_PAD_X * u, cy, PANE_FONT * u, text);

  const float chev = AGENT_CHIP_ICON * u * 0.8f;
  rctf chev_box;
  chev_box.xmax = rect.xmax - PANE_CHIP_PAD_X * u * 0.75f;
  chev_box.xmin = chev_box.xmax - chev;
  chev_box.ymin = cy - chev * 0.5f;
  chev_box.ymax = cy + chev * 0.5f;
  agent_ui_icon_draw(AGENT_ICON_CHEVRON_DOWN, &chev_box, text, fill);
}

rctf pane_segmented_layout(const float x,
                           const float y_top,
                           const char *const *labels,
                           const int count,
                           const float u,
                           rctf *r_segs)
{
  const float pad = 14.0f * u;
  float sx = x;
  for (int i = 0; i < count; i++) {
    const float w = pane_text_width(labels[i], PANE_FONT * u) + pad * 2.0f;
    r_segs[i].xmin = sx;
    r_segs[i].xmax = sx + w;
    r_segs[i].ymax = y_top;
    r_segs[i].ymin = y_top - PANE_ROW_H * u;
    sx = r_segs[i].xmax;
  }
  rctf track;
  track.xmin = x;
  track.xmax = sx;
  track.ymax = y_top;
  track.ymin = y_top - PANE_ROW_H * u;
  return track;
}

void pane_segmented_paint(const rctf *segs,
                          const char *const *labels,
                          const int active_index,
                          const int count,
                          const float u)
{
  if (count <= 0) {
    return;
  }
  const float track_col[4] = PANE_COL_CHIP;
  const float thumb_col[4] = PANE_COL_PILL;
  const float text[4] = AGENT_COL_TEXT;
  const float dim[4] = AGENT_COL_TEXT_DIM;

  rctf track = segs[0];
  track.xmax = segs[count - 1].xmax;
  pane_fill_round(&track, PANE_RADIUS * u, track_col);

  for (int i = 0; i < count; i++) {
    if (i == active_index) {
      rctf thumb = segs[i];
      thumb.xmin += PANE_SEG_INSET * u;
      thumb.xmax -= PANE_SEG_INSET * u;
      thumb.ymin += PANE_SEG_INSET * u;
      thumb.ymax -= PANE_SEG_INSET * u;
      pane_fill_round(&thumb, PANE_RADIUS * u, thumb_col);
    }
    pane_label_centre(labels[i],
                      BLI_rctf_cent_x(&segs[i]),
                      BLI_rctf_cent_y(&segs[i]),
                      PANE_FONT * u,
                      (i == active_index) ? text : dim);
  }
}

float pane_onoff_chip_w(const char *label, const float u)
{
  const float font = PANE_FONT * u;
  return PANE_CHIP_PAD_X * u + pane_text_width(label, font) + 12.0f * u +
         pane_text_width("ON", font) + 20.0f * u + pane_text_width("OFF", font) + 20.0f * u +
         PANE_CHIP_PAD_X * u * 0.75f;
}

void pane_onoff_chip_paint(const rctf &rect, const char *label, const bool on, const float u)
{
  const float fill[4] = PANE_COL_CHIP;
  const float pill[4] = PANE_COL_PILL_ON;
  const float text[4] = AGENT_COL_TEXT;
  const float dim[4] = AGENT_COL_TEXT_DIM;
  const float font = PANE_FONT * u;

  pane_fill_round(&rect, PANE_RADIUS * u, fill);
  const float cy = BLI_rctf_cent_y(&rect);
  float x = rect.xmin + PANE_CHIP_PAD_X * u;
  pane_label_left(label, x, cy, font, text);
  x += pane_text_width(label, font) + 12.0f * u;

  const float on_w = pane_text_width("ON", font) + 20.0f * u;
  const float off_w = pane_text_width("OFF", font) + 20.0f * u;
  const float pill_h = PANE_PILL_H * u;
  rctf live;
  live.xmin = on ? x : x + on_w;
  live.xmax = live.xmin + (on ? on_w : off_w);
  live.ymin = cy - pill_h * 0.5f;
  live.ymax = cy + pill_h * 0.5f;
  pane_fill_round(&live, PANE_RADIUS * u, pill);

  pane_label_centre("ON", x + on_w * 0.5f, cy, font, on ? text : dim);
  pane_label_centre("OFF", x + on_w + off_w * 0.5f, cy, font, on ? dim : text);
}

/** \} */

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

/* -------------------------------------------------------------------- */
/** \name Owned tooltips
 * \{ */

namespace {

std::string pane_tooltip_owned_fn(bContext * /*C*/, void *argN, blender::StringRef /*tip*/)
{
  return std::string(static_cast<const char *>(argN));
}

}  // namespace

void pane_but_tooltip_owned(uiBut *but, const char *text)
{
  if (but == nullptr || text == nullptr || text[0] == '\0') {
    return;
  }
  const size_t size = strlen(text) + 1;
  char *owned = static_cast<char *>(MEM_mallocN(size, __func__));
  memcpy(owned, text, size);
  /* The callback form is the only one that owns its argument; `but->tip` is a
   * bare StringRef and would dangle. `MEM_freeN` is the matching free func. */
  UI_but_func_tooltip_set(but, pane_tooltip_owned_fn, owned, MEM_freeN);
}

/** \} */

