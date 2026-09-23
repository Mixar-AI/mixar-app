/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Capture lightbox: click a capture tile in the steps block and the image
 * opens large over the chat — scrim, the image fit to the region, its
 * caption and position, ‹ › to step through every capture of that bubble.
 * ESC, a click anywhere off a control, or the ✕ closes it.
 *
 * Screen-space, drawn after the messages (like the past-chats overlay) and
 * modal for this region while open. All state is on MixieChatRuntime; the
 * gallery is read from the layout cache each draw (the bubble's step-tagged
 * image items, in order), so a layout rebuild that drops the bubble simply
 * closes the lightbox.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"
#include "BKE_main.hh"

#include "BLF_api.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"
#include "mixie_chat_layout_data.hh"
#include "mixie_chat_ui_types.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* Open animation (scrim + image fade). */
#define LIGHTBOX_ANIM_SECONDS 0.16
/* Region inset around the image (pre-UI-scale). */
#define LIGHTBOX_MARGIN 28.0f
/* Reserved band above the image (close button) and below it (caption). */
#define LIGHTBOX_TOP_BAND 44.0f
#define LIGHTBOX_BOTTOM_BAND 40.0f
/* Control chips: close (top-right) and prev / next (left / right middle). */
#define LIGHTBOX_CHIP 30.0f
#define LIGHTBOX_CHIP_RADIUS 8.0f
#define LIGHTBOX_TEXT_PX 13.0f

static const float LIGHTBOX_SCRIM[4] = {0.02f, 0.03f, 0.04f, 0.82f};
static const float LIGHTBOX_CHIP_BG[4] = {1.0f, 1.0f, 1.0f, 0.08f};
static const float LIGHTBOX_CHIP_BG_HOVER[4] = {1.0f, 1.0f, 1.0f, 0.18f};
static const float LIGHTBOX_INK[4] = {0.94f, 0.95f, 0.96f, 0.92f};
static const float LIGHTBOX_INK_DIM[4] = {0.94f, 0.95f, 0.96f, 0.6f};

/* -------------------------------------------------------------------- */
/** \name Helpers
 * \{ */

static SpaceMixieChat *lightbox_space(const bContext *C)
{
  ScrArea *area = CTX_wm_area(C);
  /* SPACE_AGENT_BUBBLE reuses the chat callbacks through its
   * layout-compatible spacedata struct (see DNA_space_types.h). */
  if (!area || !area->spacedata.first || area->spacetype != SPACE_AGENT_BUBBLE) {
    return nullptr;
  }
  return static_cast<SpaceMixieChat *>(area->spacedata.first);
}

/* The bubble's capture tiles, in layout order. Returns the layout (or null)
 * and fills `r_indices` with indices into its slot_images. */
static const MessageLayoutData *lightbox_gallery(const MixieChatRuntime *rt,
                                                 blender::Vector<int> &r_indices)
{
  r_indices.clear();
  if (rt->lightbox_bubble_id[0] == '\0') {
    return nullptr;
  }
  for (const MessageLayoutData &layout : rt->layout_cache) {
    if (!layout.has_steps || !STREQ(layout.bubble_id, rt->lightbox_bubble_id)) {
      continue;
    }
    for (int i = 0; i < layout.slot_image_count; i++) {
      const ImageSlotData &img = layout.slot_images[i];
      if (img.step_id[0] != '\0' && img.local_path[0] != '\0') {
        r_indices.append(i);
      }
    }
    return &layout;
  }
  return nullptr;
}

static void lightbox_draw_glyph_chip(const rctf &chip,
                                     const char *glyph,
                                     bool hovered,
                                     int font_id)
{
  const float radius = LIGHTBOX_CHIP_RADIUS * UI_SCALE_FAC;
  chat_ui_draw_rounded_rect(&chip, radius, hovered ? LIGHTBOX_CHIP_BG_HOVER : LIGHTBOX_CHIP_BG);

  BLF_size(font_id, LIGHTBOX_TEXT_PX * 1.15f * UI_SCALE_FAC);
  rcti bb;
  BLF_boundbox(font_id, glyph, strlen(glyph), &bb);
  const float gx = chip.xmin + (BLI_rctf_size_x(&chip) - float(BLI_rcti_size_x(&bb))) * 0.5f -
                   float(bb.xmin);
  const float gy = chip.ymin + (BLI_rctf_size_y(&chip) - float(BLI_rcti_size_y(&bb))) * 0.5f -
                   float(bb.ymin);
  BLF_color4fv(font_id, hovered ? LIGHTBOX_INK : LIGHTBOX_INK_DIM);
  BLF_position(font_id, gx, gy, 0.0f);
  BLF_draw(font_id, glyph, strlen(glyph));
}

static void lightbox_step(MixieChatRuntime *rt, ARegion *region, int delta, int count)
{
  if (count <= 1) {
    return;
  }
  rt->lightbox_index = ((rt->lightbox_index + delta) % count + count) % count;
  ED_region_tag_redraw(region);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Open / Close
 * \{ */

void mixie_chat_lightbox_open(SpaceMixieChat *smixie, const char *bubble_id, int image_index)
{
  if (!smixie || !bubble_id || bubble_id[0] == '\0') {
    return;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  BLI_strncpy(rt->lightbox_bubble_id, bubble_id, sizeof(rt->lightbox_bubble_id));
  /* The caller hands us an index into slot_images; the gallery counts only
   * the step tiles, so translate to a gallery position. */
  blender::Vector<int> gallery;
  lightbox_gallery(rt, gallery);
  int pos = 0;
  for (int i = 0; i < int(gallery.size()); i++) {
    if (gallery[i] == image_index) {
      pos = i;
      break;
    }
  }
  rt->lightbox_index = pos;
  rt->lightbox_hover = 0;
  rt->lightbox_anim_start = BLI_time_now_seconds();
  rt->lightbox_active = true;
}

void mixie_chat_lightbox_close(SpaceMixieChat *smixie)
{
  if (!smixie) {
    return;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  rt->lightbox_active = false;
  rt->lightbox_hover = 0;
  memset(&rt->lightbox_image_bounds, 0, sizeof(rt->lightbox_image_bounds));
  memset(&rt->lightbox_close_bounds, 0, sizeof(rt->lightbox_close_bounds));
  memset(&rt->lightbox_prev_bounds, 0, sizeof(rt->lightbox_prev_bounds));
  memset(&rt->lightbox_next_bounds, 0, sizeof(rt->lightbox_next_bounds));
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Drawing
 * \{ */

void mixie_chat_draw_lightbox(const bContext *C, ARegion *region)
{
  SpaceMixieChat *smixie = lightbox_space(C);
  if (!smixie) {
    return;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  if (!rt->lightbox_active) {
    return;
  }

  blender::Vector<int> gallery;
  const MessageLayoutData *layout = lightbox_gallery(rt, gallery);
  if (!layout || gallery.is_empty()) {
    mixie_chat_lightbox_close(smixie);
    return;
  }
  const int count = int(gallery.size());
  rt->lightbox_index = std::clamp(rt->lightbox_index, 0, count - 1);
  const ImageSlotData &img = layout->slot_images[gallery[rt->lightbox_index]];

  Main *bmain = CTX_data_main(C);
  const float scale = UI_SCALE_FAC;
  const float winx = float(region->winx);
  const float winy = float(region->winy);

  /* Open fade. */
  const double now = BLI_time_now_seconds();
  float ease = 1.0f;
  if (rt->lightbox_anim_start > 0.0) {
    const double t = (now - rt->lightbox_anim_start) / LIGHTBOX_ANIM_SECONDS;
    ease = std::clamp(float(t), 0.0f, 1.0f);
    ease = 1.0f - (1.0f - ease) * (1.0f - ease);
    if (t < 1.0) {
      ED_region_tag_redraw(region);
    }
  }

  GPU_blend(GPU_BLEND_ALPHA);

  /* Scrim over the whole region. */
  {
    rctf full;
    BLI_rctf_init(&full, 0.0f, winx, 0.0f, winy);
    const float scrim[4] = {LIGHTBOX_SCRIM[0], LIGHTBOX_SCRIM[1], LIGHTBOX_SCRIM[2],
                            LIGHTBOX_SCRIM[3] * ease};
    chat_ui_draw_rounded_rect(&full, 0.0f, scrim);
  }

  /* Image box: the region minus the margin and the two text bands. */
  const float margin = LIGHTBOX_MARGIN * scale;
  rctf box;
  box.xmin = margin;
  box.xmax = winx - margin;
  box.ymin = margin + LIGHTBOX_BOTTOM_BAND * scale;
  box.ymax = winy - margin - LIGHTBOX_TOP_BAND * scale;
  if (BLI_rctf_size_x(&box) < 32.0f || BLI_rctf_size_y(&box) < 32.0f) {
    /* Too small to show anything; keep the scrim so ESC still reads. */
    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  rctf drawn;
  const bool ok = chat_ui_draw_image_fitted(bmain, img.local_path, /*source=*/0, &box, &drawn);
  const int font_id = BLF_default();
  if (ok) {
    rt->lightbox_image_bounds = drawn;
    const float line[4] = {1.0f, 1.0f, 1.0f, 0.18f * ease};
    chat_ui_draw_rounded_rect_outline(&drawn, 0.0f, line, 1.0f * scale);
  }
  else {
    /* The file is gone (media pruned): say so instead of a bare scrim. */
    memset(&rt->lightbox_image_bounds, 0, sizeof(rt->lightbox_image_bounds));
    drawn = box;
    const char *missing = "Image no longer available";
    BLF_size(font_id, LIGHTBOX_TEXT_PX * scale);
    const float tw = BLF_width(font_id, missing, strlen(missing));
    BLF_color4fv(font_id, LIGHTBOX_INK_DIM);
    BLF_position(font_id, (winx - tw) * 0.5f, (box.ymin + box.ymax) * 0.5f, 0.0f);
    BLF_draw(font_id, missing, strlen(missing));
  }

  /* Caption band: caption left, "n / N" right. */
  {
    BLF_size(font_id, LIGHTBOX_TEXT_PX * scale);
    const float baseline = margin + (LIGHTBOX_BOTTOM_BAND * scale - float(BLF_height_max(font_id))) * 0.5f +
                           -float(BLF_descender(font_id));
    const char *caption = img.caption[0] ? img.caption : (img.alt[0] ? img.alt : "Capture");
    BLF_color4fv(font_id, LIGHTBOX_INK);
    BLF_position(font_id, drawn.xmin, baseline, 0.0f);
    BLF_draw(font_id, caption, strlen(caption));

    char counter[32];
    BLI_snprintf(counter, sizeof(counter), "%d / %d", rt->lightbox_index + 1, count);
    const float cw = BLF_width(font_id, counter, strlen(counter));
    BLF_color4fv(font_id, LIGHTBOX_INK_DIM);
    BLF_position(font_id, drawn.xmax - cw, baseline, 0.0f);
    BLF_draw(font_id, counter, strlen(counter));
  }

  /* Close chip, top-right of the region. */
  {
    const float chip = LIGHTBOX_CHIP * scale;
    rctf close;
    close.xmax = winx - margin;
    close.xmin = close.xmax - chip;
    close.ymax = winy - margin * 0.5f;
    close.ymin = close.ymax - chip;
    rt->lightbox_close_bounds = close;
    lightbox_draw_glyph_chip(close, "\xE2\x9C\x95" /* ✕ */, rt->lightbox_hover == 1, font_id);
  }

  /* Prev / next chips, vertically centred on the image, only with > 1 tile. */
  if (count > 1) {
    const float chip = LIGHTBOX_CHIP * scale;
    const float mid = (drawn.ymin + drawn.ymax) * 0.5f;
    rctf prev, next;
    prev.xmin = margin * 0.25f;
    prev.xmax = prev.xmin + chip;
    prev.ymin = mid - chip * 0.5f;
    prev.ymax = mid + chip * 0.5f;
    next.xmax = winx - margin * 0.25f;
    next.xmin = next.xmax - chip;
    next.ymin = prev.ymin;
    next.ymax = prev.ymax;
    rt->lightbox_prev_bounds = prev;
    rt->lightbox_next_bounds = next;
    lightbox_draw_glyph_chip(prev, "\xE2\x80\xB9" /* ‹ */, rt->lightbox_hover == 2, font_id);
    lightbox_draw_glyph_chip(next, "\xE2\x80\xBA" /* › */, rt->lightbox_hover == 3, font_id);
  }
  else {
    memset(&rt->lightbox_prev_bounds, 0, sizeof(rt->lightbox_prev_bounds));
    memset(&rt->lightbox_next_bounds, 0, sizeof(rt->lightbox_next_bounds));
  }

  GPU_blend(GPU_BLEND_NONE);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Events + Cursor
 * \{ */

static int lightbox_hit_control(const MixieChatRuntime *rt, float mx, float my)
{
  const rctf *rects[] = {&rt->lightbox_close_bounds, &rt->lightbox_prev_bounds,
                         &rt->lightbox_next_bounds};
  for (int i = 0; i < 3; i++) {
    if (rects[i]->xmax > rects[i]->xmin && BLI_rctf_isect_pt(rects[i], mx, my)) {
      return i + 1;
    }
  }
  return 0;
}

bool mixie_chat_lightbox_cursor(
    wmWindow *win, MixieChatRuntime *rt, ARegion *region, float mouse_x, float mouse_y)
{
  if (!rt->lightbox_active) {
    return false;
  }
  const int hover = lightbox_hit_control(rt, mouse_x, mouse_y);
  if (hover != rt->lightbox_hover) {
    rt->lightbox_hover = hover;
    ED_region_tag_redraw(region);
  }
  WM_cursor_set(win, hover ? WM_CURSOR_HAND : WM_CURSOR_DEFAULT);
  return true;
}

bool mixie_chat_lightbox_handle_event(bContext *C, const wmEvent *event)
{
  SpaceMixieChat *smixie = lightbox_space(C);
  ARegion *region = CTX_wm_region(C);
  if (!smixie || !region) {
    return false;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  if (!rt->lightbox_active) {
    return false;
  }

  blender::Vector<int> gallery;
  lightbox_gallery(rt, gallery);
  const int count = int(gallery.size());

  if (ISKEYBOARD(event->type)) {
    if (event->val != KM_PRESS) {
      return true; /* Modal: releases are consumed too. */
    }
    switch (event->type) {
      case EVT_ESCKEY:
        mixie_chat_lightbox_close(smixie);
        ED_region_tag_redraw(region);
        return true;
      case EVT_LEFTARROWKEY:
      case EVT_UPARROWKEY:
        lightbox_step(rt, region, -1, count);
        return true;
      case EVT_RIGHTARROWKEY:
      case EVT_DOWNARROWKEY:
      case EVT_SPACEKEY:
        lightbox_step(rt, region, +1, count);
        return true;
      default:
        return true;
    }
  }

  /* Scrolling never reaches the chat behind the scrim. */
  if (ELEM(event->type, WHEELUPMOUSE, WHEELDOWNMOUSE, MOUSEPAN)) {
    return true;
  }

  if (ELEM(event->type, MOUSEMOVE, INBETWEEN_MOUSEMOVE)) {
    const int hover = lightbox_hit_control(rt, float(event->mval[0]), float(event->mval[1]));
    if (hover != rt->lightbox_hover) {
      rt->lightbox_hover = hover;
      ED_region_tag_redraw(region);
    }
    return false; /* Let the region's cursor handler run too. */
  }

  if (event->type == LEFTMOUSE && event->val == KM_PRESS) {
    switch (lightbox_hit_control(rt, float(event->mval[0]), float(event->mval[1]))) {
      case 1:
        mixie_chat_lightbox_close(smixie);
        break;
      case 2:
        lightbox_step(rt, region, -1, count);
        break;
      case 3:
        lightbox_step(rt, region, +1, count);
        break;
      default:
        /* Anywhere else — the image included — closes. */
        mixie_chat_lightbox_close(smixie);
        break;
    }
    ED_region_tag_redraw(region);
    return true;
  }
  if (ELEM(event->type, LEFTMOUSE, RIGHTMOUSE, MIDDLEMOUSE)) {
    return true; /* Releases / other buttons stay inside the overlay. */
  }
  return false;
}

/** \} */
}  // namespace blender
