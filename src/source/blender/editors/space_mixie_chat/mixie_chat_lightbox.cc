/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Capture lightbox: click a capture tile in the steps block and the image
 * opens large over the WHOLE WINDOW — scrim, the image fit to the window,
 * "n / N", ‹ › (and ← →) through every capture of that bubble. ESC, a click
 * anywhere off a control, or the ✕ closes it. Captures are numbered in the
 * order they were taken and the gallery row leads with the NEWEST, so
 * "next" (›, →) walks to OLDER captures: 32 / 32, 31 / 32 … 1 / 32.
 *
 * A modal operator (MIXIE_CHAT_OT_lightbox) with a window draw callback
 * (WM_draw_cb_activate, the pattern of space_mixie/mixie_attachment_flight.cc):
 * the chat's message region is often a short strip at the bottom of the
 * window, and an enlargement confined to it came out SMALLER than the tile.
 * The gallery (the bubble's step-tagged tiles, in order) is copied into the
 * operator at invoke, so a layout rebuild while it is open changes nothing.
 */

#include <algorithm>
#include <climits>
#include <cstring>
#include <string>
#include <vector>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_global.hh"
#include "BKE_main.hh"

#include "BLF_api.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "GPU_state.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"
#include "mixie_chat_layout_data.hh"
#include "mixie_chat_ui_types.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* Window inset around the image (pre-UI-scale). */
#define LIGHTBOX_MARGIN 32.0f
/* Reserved band above the image (close button) and below it (counter). */
#define LIGHTBOX_TOP_BAND 44.0f
#define LIGHTBOX_BOTTOM_BAND 40.0f
/* Control chips: close (top-right) and prev / next (left / right middle). */
#define LIGHTBOX_CHIP 30.0f
#define LIGHTBOX_TEXT_PX 13.0f

static const float LIGHTBOX_SCRIM[4] = {0.02f, 0.03f, 0.04f, 0.86f};
static const float LIGHTBOX_INK[4] = {0.94f, 0.95f, 0.96f, 0.92f};
static const float LIGHTBOX_INK_DIM[4] = {0.94f, 0.95f, 0.96f, 0.6f};

struct LightboxData {
  std::vector<std::string> paths; /* the bubble's capture tiles, in order */
  int index = 0;
  wmWindow *win = nullptr;
  void *handle = nullptr; /* WM_draw_cb_activate handle */
  /* Hit rects in window pixels, rebuilt per draw. */
  rctf close_bounds = {0, 0, 0, 0};
  rctf prev_bounds = {0, 0, 0, 0};
  rctf next_bounds = {0, 0, 0, 0};
  int hover = 0; /* 0 none, 1 close, 2 prev, 3 next */
};

/* -------------------------------------------------------------------- */
/** \name Drawing (window draw callback)
 * \{ */

static void lightbox_draw_glyph_chip(const rctf &chip, const char *glyph, bool hovered, int font_id)
{
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

static void lightbox_draw(const wmWindow *win, void *customdata)
{
  LightboxData *data = static_cast<LightboxData *>(customdata);
  if (!data || data->win != win || data->paths.empty()) {
    return;
  }
  const int count = int(data->paths.size());
  data->index = std::clamp(data->index, 0, count - 1);

  const float winx = float(WM_window_native_pixel_x(win));
  const float winy = float(WM_window_native_pixel_y(win));
  const float scale = UI_SCALE_FAC;
  const float margin = LIGHTBOX_MARGIN * scale;
  const int font_id = BLF_default();

  GPU_blend(GPU_BLEND_ALPHA);

  /* Scrim over the whole window, instantly (no fade: it read as a delay). */
  {
    rctf full;
    BLI_rctf_init(&full, 0.0f, winx, 0.0f, winy);
    chat_ui_draw_rounded_rect(&full, 0.0f, LIGHTBOX_SCRIM);
  }

  /* Image box: the window minus the margin and the two bands. */
  rctf box;
  box.xmin = margin;
  box.xmax = winx - margin;
  box.ymin = margin + LIGHTBOX_BOTTOM_BAND * scale;
  box.ymax = winy - margin - LIGHTBOX_TOP_BAND * scale;
  if (BLI_rctf_size_x(&box) < 32.0f || BLI_rctf_size_y(&box) < 32.0f) {
    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  rctf drawn;
  const bool ok = chat_ui_draw_image_fitted(
      G_MAIN, data->paths[data->index].c_str(), /*source=*/0, &box, &drawn);
  if (!ok) {
    drawn = box;
    const char *missing = "Image no longer available";
    BLF_size(font_id, LIGHTBOX_TEXT_PX * scale);
    const float tw = BLF_width(font_id, missing, strlen(missing));
    BLF_color4fv(font_id, LIGHTBOX_INK_DIM);
    BLF_position(font_id, (winx - tw) * 0.5f, (box.ymin + box.ymax) * 0.5f, 0.0f);
    BLF_draw(font_id, missing, strlen(missing));
  }

  /* Counter, bottom right. The capture's label is the backend's internal
   * name and says nothing a user needs, so it is not shown. */
  {
    BLF_size(font_id, LIGHTBOX_TEXT_PX * scale);
    const float baseline = margin +
                           (LIGHTBOX_BOTTOM_BAND * scale - float(BLF_height_max(font_id))) * 0.5f -
                           float(BLF_descender(font_id));
    char counter[32];
    BLI_snprintf(counter, sizeof(counter), "%d / %d", data->index + 1, count);
    const float cw = BLF_width(font_id, counter, strlen(counter));
    BLF_color4fv(font_id, LIGHTBOX_INK_DIM);
    BLF_position(font_id, winx - margin - cw, baseline, 0.0f);
    BLF_draw(font_id, counter, strlen(counter));
  }

  /* Close chip, top-right of the window. */
  {
    const float chip = LIGHTBOX_CHIP * scale;
    rctf close;
    close.xmax = winx - margin;
    close.xmin = close.xmax - chip;
    close.ymax = winy - margin * 0.5f;
    close.ymin = close.ymax - chip;
    data->close_bounds = close;
    lightbox_draw_glyph_chip(close, "\xE2\x9C\x95" /* ✕ */, data->hover == 1, font_id);
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
    data->prev_bounds = prev;
    data->next_bounds = next;
    lightbox_draw_glyph_chip(prev, "\xE2\x80\xB9" /* ‹ */, data->hover == 2, font_id);
    lightbox_draw_glyph_chip(next, "\xE2\x80\xBA" /* › */, data->hover == 3, font_id);
  }
  else {
    memset(&data->prev_bounds, 0, sizeof(data->prev_bounds));
    memset(&data->next_bounds, 0, sizeof(data->next_bounds));
  }

  GPU_blend(GPU_BLEND_NONE);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operator
 * \{ */

static void lightbox_redraw(bContext *C, wmWindow *win)
{
  if (win) {
    if (bScreen *screen = WM_window_get_active_screen(win)) {
      screen->do_draw = true;
    }
  }
  WM_event_add_notifier(C, NC_WINDOW, nullptr);
}

static void lightbox_close(bContext *C, wmOperator *op)
{
  LightboxData *data = static_cast<LightboxData *>(op->customdata);
  if (!data) {
    return;
  }
  if (data->win && data->handle) {
    WM_draw_cb_exit(data->win, data->handle);
    WM_cursor_set(data->win, WM_CURSOR_DEFAULT);
  }
  lightbox_redraw(C, data->win ? data->win : CTX_wm_window(C));
  MEM_delete(data);
  op->customdata = nullptr;
}

static int lightbox_hit(const LightboxData *data, float mx, float my)
{
  const rctf *rects[] = {&data->close_bounds, &data->prev_bounds, &data->next_bounds};
  for (int i = 0; i < 3; i++) {
    if (rects[i]->xmax > rects[i]->xmin && BLI_rctf_isect_pt(rects[i], mx, my)) {
      return i + 1;
    }
  }
  return 0;
}

static void lightbox_step(LightboxData *data, int delta)
{
  const int count = int(data->paths.size());
  if (count <= 1) {
    return;
  }
  data->index = ((data->index + delta) % count + count) % count;
}

static wmOperatorStatus lightbox_invoke(bContext *C, wmOperator *op, const wmEvent * /*event*/)
{
  ScrArea *area = CTX_wm_area(C);
  wmWindow *win = CTX_wm_window(C);
  if (!area || !win || !area->spacedata.first || area->spacetype != SPACE_AGENT_BUBBLE) {
    return OPERATOR_CANCELLED;
  }
  SpaceMixieChat *smixie = static_cast<SpaceMixieChat *>(area->spacedata.first);

  char bubble_id[128] = "";
  RNA_string_get(op->ptr, "bubble_id", bubble_id);
  const int wanted = RNA_int_get(op->ptr, "index");

  LightboxData *data = MEM_new<LightboxData>("mixie_chat_lightbox");
  for (const MessageLayoutData &layout : mixie_chat_get_layout_cache(smixie)) {
    if (!STREQ(layout.bubble_id, bubble_id)) {
      continue;
    }
    for (int i = 0; i < layout.slot_image_count; i++) {
      const ImageSlotData &img = layout.slot_images[i];
      if (img.step_id[0] != '\0' && img.local_path[0] != '\0') {
        if (i == wanted) {
          data->index = int(data->paths.size());
        }
        data->paths.emplace_back(img.local_path);
      }
    }
    break;
  }
  if (data->paths.empty()) {
    MEM_delete(data);
    return OPERATOR_CANCELLED;
  }
  data->win = win;
  data->handle = WM_draw_cb_activate(win, lightbox_draw, data);
  op->customdata = data;
  WM_event_add_modal_handler(C, op);
  lightbox_redraw(C, win);
  return OPERATOR_RUNNING_MODAL;
}

static wmOperatorStatus lightbox_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  LightboxData *data = static_cast<LightboxData *>(op->customdata);
  if (!data) {
    return OPERATOR_CANCELLED;
  }
  wmWindow *win = data->win;

  if (ISKEYBOARD(event->type)) {
    if (event->val != KM_PRESS) {
      return OPERATOR_RUNNING_MODAL;
    }
    switch (event->type) {
      case EVT_ESCKEY:
        lightbox_close(C, op);
        return OPERATOR_FINISHED;
      case EVT_LEFTARROWKEY:
      case EVT_UPARROWKEY:
        lightbox_step(data, +1); /* newer */
        lightbox_redraw(C, win);
        return OPERATOR_RUNNING_MODAL;
      case EVT_RIGHTARROWKEY:
      case EVT_DOWNARROWKEY:
      case EVT_SPACEKEY:
        lightbox_step(data, -1); /* older */
        lightbox_redraw(C, win);
        return OPERATOR_RUNNING_MODAL;
      default:
        return OPERATOR_RUNNING_MODAL;
    }
  }

  /* Event xy are window pixels — the draw callback's space. */
  const float mx = float(event->xy[0]);
  const float my = float(event->xy[1]);

  if (ELEM(event->type, MOUSEMOVE, INBETWEEN_MOUSEMOVE)) {
    const int hover = lightbox_hit(data, mx, my);
    if (hover != data->hover) {
      data->hover = hover;
      lightbox_redraw(C, win);
    }
    WM_cursor_set(win, hover ? WM_CURSOR_HAND : WM_CURSOR_DEFAULT);
    return OPERATOR_RUNNING_MODAL;
  }

  if (event->type == LEFTMOUSE && event->val == KM_PRESS) {
    switch (lightbox_hit(data, mx, my)) {
      case 2: /* ‹ newer */
        lightbox_step(data, +1);
        lightbox_redraw(C, win);
        return OPERATOR_RUNNING_MODAL;
      case 3: /* › older */
        lightbox_step(data, -1);
        lightbox_redraw(C, win);
        return OPERATOR_RUNNING_MODAL;
      default:
        /* The ✕, the image, or anywhere else — closes. */
        lightbox_close(C, op);
        return OPERATOR_FINISHED;
    }
  }
  if (event->type == RIGHTMOUSE && event->val == KM_PRESS) {
    lightbox_close(C, op);
    return OPERATOR_FINISHED;
  }
  /* Everything else (wheel, other buttons, releases) stays inside the overlay. */
  return OPERATOR_RUNNING_MODAL;
}

static void lightbox_cancel(bContext *C, wmOperator *op)
{
  lightbox_close(C, op);
}

void MIXIE_CHAT_OT_lightbox(wmOperatorType *ot)
{
  ot->name = "View Capture";
  ot->idname = "MIXIE_CHAT_OT_lightbox";
  ot->description = "Show an agent capture large over the whole window";
  ot->invoke = lightbox_invoke;
  ot->modal = lightbox_modal;
  ot->cancel = lightbox_cancel;
  ot->flag = OPTYPE_INTERNAL | OPTYPE_BLOCKING;

  RNA_def_string(ot->srna, "bubble_id", nullptr, 128, "Bubble ID", "");
  RNA_def_int(ot->srna, "index", 0, 0, INT_MAX, "Index", "slot_images index of the tile", 0, INT_MAX);
}

void mixie_chat_lightbox_open(bContext *C, const char *bubble_id, int image_index)
{
  wmOperatorType *ot = WM_operatortype_find("MIXIE_CHAT_OT_lightbox", true);
  if (!ot || !bubble_id || bubble_id[0] == '\0') {
    return;
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  RNA_string_set(&op_ptr, "bubble_id", bubble_id);
  RNA_int_set(&op_ptr, "index", image_index);
  WM_operator_name_call_ptr(C, ot, blender::wm::OpCallContext::InvokeDefault, &op_ptr, nullptr);
  WM_operator_properties_free(&op_ptr);
}

/** \} */
}  // namespace blender
