/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Past-chats overlay: a Mixar-styled floating card listing archived chat
 * sessions, drawn in screen-space on top of the message area (after
 * UI_view2d_view_restore, like the scroll indicator).
 *
 * Data flows one way from Python:
 *   - visibility:  WindowManager.mixie_chat_history_visible (bool, toggled
 *     by MIXIE_CHAT_OT_show_history in the header, which also syncs)
 *   - rows:        WindowManager.mixie_chat_history_entries (name /
 *     session_id / when), the runtime mirror of ~/.mixar/chat_history/
 *   - current:     scene.mixie_session_id marks the open chat's row
 *
 * Interactions dispatch back to Python operators (same pattern as slot
 * actions): row click -> mixie_chat.open_history_session, X click ->
 * mixie_chat.delete_history_session (InvokeDefault for its confirm).
 * While open the overlay is modal for this region: it consumes clicks
 * (click-away closes), wheel/trackpad scroll (row-stepped, so no GPU
 * scissor clipping is needed) and ESC.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_string_utf8.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"

#include "BLF_api.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"

/* -------------------------------------------------------------------- */
/** \name Constants (base px, scaled by UI_SCALE_FAC at draw time)
 * \{ */

static const float PANEL_MAX_WIDTH = 480.0f;
static const float PANEL_SIDE_MARGIN = 12.0f;
static const float PANEL_TOP_MARGIN = 10.0f;
static const float PANEL_RADIUS = 14.0f;
static const float PANEL_PAD = 12.0f;
static const float HEADER_HEIGHT = 46.0f;
static const float ROW_HEIGHT = 40.0f;
static const float ROW_RADIUS = 9.0f;
static const float ROW_SIDE_INSET = 6.0f;
static const float DOT_RADIUS = 3.5f;
static const float TITLE_INDENT = 26.0f;
static const float DELETE_SIZE = 22.0f;
static const float DELETE_RIGHT_INSET = 8.0f;
static const int MAX_VISIBLE_ROWS = 12;
static const float OPEN_ANIM_DURATION = 0.18f; /* seconds */
static const float OPEN_SLIDE_PX = 8.0f;

/* Colors (Mixar dark surface language; alpha multiplied by open anim). */
static const float COL_SCRIM[4] = {0.02f, 0.03f, 0.04f, 0.42f};
static const float COL_PANEL[4] = {0.105f, 0.115f, 0.135f, 0.995f};
static const float COL_PANEL_OUTLINE[4] = {1.0f, 1.0f, 1.0f, 0.075f};
static const float COL_PANEL_SHADOW[4] = {0.0f, 0.0f, 0.0f, 0.35f};
static const float COL_HEADER_TEXT[4] = {0.92f, 0.94f, 0.97f, 1.0f};
static const float COL_MUTED[4] = {0.52f, 0.56f, 0.61f, 1.0f};
static const float COL_DIVIDER[4] = {1.0f, 1.0f, 1.0f, 0.06f};
static const float COL_ROW_HOVER[4] = {1.0f, 1.0f, 1.0f, 0.055f};
static const float COL_TITLE[4] = {0.86f, 0.88f, 0.91f, 0.96f};
static const float COL_TITLE_CURRENT[4] = {0.97f, 0.98f, 1.0f, 1.0f};
static const float COL_ACCENT[4] = CHAT_ACCENT_LIVE;
static const float COL_DELETE[4] = {0.55f, 0.58f, 0.62f, 0.75f};
static const float COL_DELETE_HOVER[4] = {0.95f, 0.42f, 0.42f, 1.0f};
static const float COL_DELETE_HOVER_BG[4] = {1.0f, 1.0f, 1.0f, 0.09f};
static const float COL_SCROLL_THUMB[4] = {1.0f, 1.0f, 1.0f, 0.16f};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Small Helpers
 * \{ */

static SpaceMixieChat *history_space_from_area(ScrArea *area)
{
  /* SPACE_AGENT_BUBBLE reuses these callbacks via its layout-compatible
   * spacedata struct (see DNA_space_types.h on SpaceAgentBubble). */
  if (!area || !area->spacedata.first ||
      (area->spacetype != SPACE_MIXIE_CHAT && area->spacetype != SPACE_AGENT_BUBBLE))
  {
    return nullptr;
  }
  return static_cast<SpaceMixieChat *>(area->spacedata.first);
}

static float ease_out_cubic(float t)
{
  t = std::max(0.0f, std::min(1.0f, t));
  const float t1 = t - 1.0f;
  return t1 * t1 * t1 + 1.0f;
}

/** Bounded read of a Python-registered RNA string property. */
static void history_read_string(PointerRNA *ptr, PropertyRNA *prop, char *buf, int buf_maxncpy)
{
  buf[0] = '\0';
  if (!prop) {
    return;
  }
  char fixed[256];
  int len = 0;
  char *value = RNA_property_string_get_alloc(ptr, prop, fixed, sizeof(fixed), &len);
  if (value) {
    BLI_strncpy(buf, value, buf_maxncpy);
    if (value != fixed) {
      MEM_freeN(value);
    }
  }
}

/** Clip `src` to `max_width` px (font already implied by `font_px`),
 * appending a UTF-8 ellipsis when trimmed. The chat primitives only wrap
 * (never truncate), so list rows need their own single-line clipper. */
static void history_text_ellipsis(
    const char *src, int font_id, int font_px, float max_width, char *dst, size_t dst_size)
{
  BLF_size(font_id, float(font_px));
  const size_t len = strlen(src);
  if (BLF_width(font_id, src, len) <= max_width) {
    BLI_strncpy(dst, src, dst_size);
    return;
  }
  const char *ellipsis = "\xe2\x80\xa6"; /* U+2026 */
  const float ellipsis_w = BLF_width(font_id, ellipsis, 3);
  size_t keep = 0;
  while (keep < len) {
    const size_t step = size_t(std::max(1, BLI_str_utf8_size_safe(src + keep)));
    const size_t next = keep + step;
    if (next >= len || next + 4 >= dst_size) {
      break;
    }
    if (BLF_width(font_id, src, next) + ellipsis_w > max_width) {
      break;
    }
    keep = next;
  }
  memcpy(dst, src, keep);
  dst[keep] = '\0';
  BLI_strncpy(dst + keep, ellipsis, dst_size - keep);
}

static void history_draw_label(
    const char *text, int font_id, int font_px, float x, float baseline_y, const float color[4])
{
  BLF_size(font_id, float(font_px));
  BLF_color4fv(font_id, color);
  BLF_position(font_id, x, baseline_y, 0.0f);
  BLF_draw(font_id, text, strlen(text));
}

static float history_text_width(const char *text, int font_id, int font_px)
{
  BLF_size(font_id, float(font_px));
  return BLF_width(font_id, text, strlen(text));
}

/** Two crossing GPU lines forming the delete X glyph. */
static void history_draw_x_glyph(float cx, float cy, float half, const float color[4], float scale)
{
  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);
  GPU_line_width(1.5f * scale);

  immBegin(GPU_PRIM_LINES, 4);
  immVertex2f(pos, cx - half, cy - half);
  immVertex2f(pos, cx + half, cy + half);
  immVertex2f(pos, cx - half, cy + half);
  immVertex2f(pos, cx + half, cy - half);
  immEnd();

  immUnbindProgram();
  GPU_line_width(1.0f);
}

/** Row index under the mouse, or -1. `r_over_delete` reports the X hit. */
static int history_hit_row(const MixieChatRuntime *rt, float mx, float my, bool *r_over_delete)
{
  *r_over_delete = false;
  for (int i = 0; i < int(rt->history_rows.size()); i++) {
    const HistoryRowHit &row = rt->history_rows[i];
    if (row.bounds.xmax <= row.bounds.xmin) {
      continue;
    }
    if (BLI_rctf_isect_pt(&row.bounds, mx, my)) {
      *r_over_delete = BLI_rctf_isect_pt(&row.delete_bounds, mx, my);
      return i;
    }
  }
  return -1;
}

static void history_reset_runtime(MixieChatRuntime *rt)
{
  rt->history_rows.clear();
  BLI_rctf_init(&rt->history_panel_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  rt->history_total_rows = 0;
  rt->history_visible_rows = 0;
}

/** Dispatch a Python operator that takes a single session_id string. */
static void history_dispatch_session_op(bContext *C,
                                        ARegion *region,
                                        const char *op_idname,
                                        const char *session_id,
                                        blender::wm::OpCallContext call_context)
{
  wmOperatorType *ot = WM_operatortype_find(op_idname, true);
  if (!ot || session_id[0] == '\0') {
    return;
  }
  PointerRNA op_ptr;
  WM_operator_properties_create_ptr(&op_ptr, ot);
  RNA_string_set(&op_ptr, "session_id", session_id);
  WM_operator_name_call_ptr(C, ot, call_context, &op_ptr, nullptr);
  WM_operator_properties_free(&op_ptr);
  ED_region_tag_redraw(region);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Visibility (Python-registered WM bool)
 * \{ */

static bool history_read_visible(wmWindowManager *wm)
{
  if (!wm) {
    return false;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_history_visible");
  if (!prop) {
    return false;
  }
  return RNA_property_boolean_get(&wm_ptr, prop);
}

void mixie_chat_history_set_visible(bContext *C, bool visible)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_history_visible");
  if (!prop) {
    return;
  }
  RNA_property_boolean_set(&wm_ptr, prop, visible);
  /* Every chat surface (editor + floating bubble) shows the overlay —
   * repaint them all via the space notifier the listener already handles. */
  WM_main_add_notifier(NC_SPACE | ND_SPACE_MIXIE_CHAT, nullptr);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Drawing
 * \{ */

/** Local snapshot of one history entry read from RNA. */
struct HistoryDrawEntry {
  char title[200];
  char when[24];
  char session_id[128];
};

static void history_read_entries(wmWindowManager *wm, blender::Vector<HistoryDrawEntry> &r_items)
{
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *entries_prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_history_entries");
  if (!entries_prop) {
    return;
  }

  PropertyRNA *p_name = nullptr;
  PropertyRNA *p_sid = nullptr;
  PropertyRNA *p_when = nullptr;

  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&wm_ptr, entries_prop, &iter);
  for (; iter.valid; RNA_property_collection_next(&iter)) {
    PointerRNA item_ptr = iter.ptr;
    if (!p_name) {
      /* All items share one runtime StructRNA — resolve once. */
      p_name = RNA_struct_find_property(&item_ptr, "name");
      p_sid = RNA_struct_find_property(&item_ptr, "session_id");
      p_when = RNA_struct_find_property(&item_ptr, "when");
    }
    HistoryDrawEntry entry;
    history_read_string(&item_ptr, p_name, entry.title, sizeof(entry.title));
    history_read_string(&item_ptr, p_sid, entry.session_id, sizeof(entry.session_id));
    history_read_string(&item_ptr, p_when, entry.when, sizeof(entry.when));
    if (entry.session_id[0] != '\0') {
      r_items.append(entry);
    }
  }
  RNA_property_collection_end(&iter);
}

void mixie_chat_draw_history_overlay(const bContext *C, ARegion *region)
{
  ScrArea *area = CTX_wm_area(C);
  SpaceMixieChat *smixie = history_space_from_area(area);
  if (!smixie) {
    return;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);

  wmWindowManager *wm = CTX_wm_manager(C);
  const bool visible = history_read_visible(wm);

  const double now = BLI_time_now_seconds();
  if (visible && !rt->history_overlay_active) {
    /* Opening edge: restart animation and scroll position. */
    rt->history_anim_start = now;
    rt->history_scroll_row = 0;
    rt->history_pan_accum = 0.0f;
  }
  rt->history_overlay_active = visible;
  if (!visible) {
    history_reset_runtime(rt);
    return;
  }

  /* Open animation (fade + slide), pumped like the other chat animations. */
  const float anim_t = float((now - rt->history_anim_start) / OPEN_ANIM_DURATION);
  const float ease = ease_out_cubic(anim_t);
  mixie_chat_anim_pump_request(C, anim_t < 1.0f);
  if (anim_t < 1.0f && area) {
    ED_area_tag_redraw(area);
  }

  blender::Vector<HistoryDrawEntry> items;
  history_read_entries(wm, items);

  /* Current chat's session id (marks its row with the accent dot). */
  char current_id[128] = "";
  if (Scene *scene = CTX_data_scene(C)) {
    PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
    PropertyRNA *sid_prop = RNA_struct_find_property(&scene_ptr, "mixie_session_id");
    if (sid_prop) {
      history_read_string(&scene_ptr, sid_prop, current_id, sizeof(current_id));
    }
  }

  const float scale = UI_SCALE_FAC;
  const int winx = region->winx;
  const int winy = region->winy;
  const int font_id = BLF_default();
  const int title_px = int(14.0f * scale);
  const int meta_px = int(12.0f * scale);
  const int header_px = int(15.0f * scale);

  const float pad = PANEL_PAD * scale;
  const float row_h = ROW_HEIGHT * scale;
  const float header_h = HEADER_HEIGHT * scale;

  float panel_w = std::min(float(winx) - 2.0f * PANEL_SIDE_MARGIN * scale,
                           PANEL_MAX_WIDTH * scale);
  panel_w = std::max(panel_w, 120.0f * scale);

  const int total = int(items.size());

  /* Visible row count: fit the region, capped, leaving breathing room. */
  const float avail_h = float(winy) - PANEL_TOP_MARGIN * scale - header_h - pad - 24.0f * scale;
  const int fit_rows = std::max(1, int(avail_h / row_h));
  const int visible_rows = std::min(total, std::min(fit_rows, MAX_VISIBLE_ROWS));

  const float body_h = (total == 0) ? 64.0f * scale : float(visible_rows) * row_h;
  const float panel_h = header_h + body_h + pad;
  const float panel_x = (float(winx) - panel_w) * 0.5f;
  const float panel_top = float(winy) - PANEL_TOP_MARGIN * scale;
  const float panel_bottom = panel_top - panel_h;

  /* Clamp scroll to the row range. */
  const int max_scroll = std::max(0, total - visible_rows);
  rt->history_scroll_row = std::max(0, std::min(rt->history_scroll_row, max_scroll));
  rt->history_total_rows = total;
  rt->history_visible_rows = visible_rows;

  /* Hit bounds at the FINAL (unslid) position for stable click targets. */
  BLI_rctf_init(&rt->history_panel_bounds, panel_x, panel_x + panel_w, panel_bottom, panel_top);
  rt->history_rows.clear();

  /* Mouse position for hover (freshest source, like the empty state). */
  wmWindow *win = CTX_wm_window(C);
  float mouse_x = -1000.0f, mouse_y = -1000.0f;
  if (win) {
    mouse_x = float(win->eventstate->xy[0] - region->winrct.xmin);
    mouse_y = float(win->eventstate->xy[1] - region->winrct.ymin);
  }

  const float slide = OPEN_SLIDE_PX * scale * (1.0f - ease);

  GPU_blend(GPU_BLEND_ALPHA);

  /* Scrim: dim the chat behind the card. */
  {
    rctf full;
    BLI_rctf_init(&full, 0.0f, float(winx), 0.0f, float(winy));
    float scrim[4] = {COL_SCRIM[0], COL_SCRIM[1], COL_SCRIM[2], COL_SCRIM[3] * ease};
    chat_ui_draw_rounded_rect(&full, 0.0f, scrim);
  }

  const float radius = PANEL_RADIUS * scale;
  rctf panel;
  BLI_rctf_init(&panel, panel_x, panel_x + panel_w, panel_bottom - slide, panel_top - slide);

  /* Soft shadow substitute: a slightly larger dark card behind. */
  {
    rctf shadow = panel;
    const float grow = 3.0f * scale;
    shadow.xmin -= grow;
    shadow.xmax += grow;
    shadow.ymin -= grow * 1.6f;
    shadow.ymax += grow * 0.4f;
    float col[4] = {COL_PANEL_SHADOW[0], COL_PANEL_SHADOW[1], COL_PANEL_SHADOW[2],
                    COL_PANEL_SHADOW[3] * ease};
    chat_ui_draw_rounded_rect(&shadow, radius + grow, col);
  }

  /* Card. */
  {
    float fill[4] = {COL_PANEL[0], COL_PANEL[1], COL_PANEL[2], COL_PANEL[3] * ease};
    float outline[4] = {COL_PANEL_OUTLINE[0], COL_PANEL_OUTLINE[1], COL_PANEL_OUTLINE[2],
                        COL_PANEL_OUTLINE[3] * ease};
    chat_ui_draw_rounded_rect(&panel, radius, fill);
    chat_ui_draw_rounded_rect_outline(&panel, radius, outline, 1.0f);
  }

  /* Header: "Chats" left, dimmed count right, hairline divider below. */
  {
    const float header_center = panel.ymax - header_h * 0.5f;
    const float baseline = header_center - float(header_px) * 0.35f;

    float title_col[4] = {COL_HEADER_TEXT[0], COL_HEADER_TEXT[1], COL_HEADER_TEXT[2],
                          COL_HEADER_TEXT[3] * ease};
    history_draw_label("Chats", font_id, header_px, panel.xmin + pad, baseline, title_col);

    if (total > 0) {
      char count_buf[16];
      SNPRINTF(count_buf, "%d", total);
      float count_col[4] = {COL_MUTED[0], COL_MUTED[1], COL_MUTED[2], COL_MUTED[3] * ease};
      const float count_w = history_text_width(count_buf, font_id, meta_px);
      history_draw_label(count_buf, font_id, meta_px, panel.xmax - pad - count_w,
                         header_center - float(meta_px) * 0.35f, count_col);
    }

    rctf divider;
    BLI_rctf_init(&divider,
                  panel.xmin + pad,
                  panel.xmax - pad,
                  panel.ymax - header_h,
                  panel.ymax - header_h + 1.0f * scale);
    float div_col[4] = {COL_DIVIDER[0], COL_DIVIDER[1], COL_DIVIDER[2], COL_DIVIDER[3] * ease};
    chat_ui_draw_rounded_rect(&divider, 0.0f, div_col);
  }

  /* Empty state. */
  if (total == 0) {
    float title_col[4] = {COL_TITLE[0], COL_TITLE[1], COL_TITLE[2], COL_TITLE[3] * ease};
    float hint_col[4] = {COL_MUTED[0], COL_MUTED[1], COL_MUTED[2], COL_MUTED[3] * ease};

    const char *empty_text = "No past chats yet";
    const char *hint_text = "New Chat saves the current conversation here";
    const float cx = (panel.xmin + panel.xmax) * 0.5f;
    const float cy = panel.ymax - header_h - body_h * 0.5f;

    float w = history_text_width(empty_text, font_id, title_px);
    history_draw_label(empty_text, font_id, title_px, cx - w * 0.5f,
                       cy + 4.0f * scale, title_col);
    w = history_text_width(hint_text, font_id, meta_px);
    history_draw_label(hint_text, font_id, meta_px, cx - w * 0.5f,
                       cy - (4.0f * scale + float(meta_px)), hint_col);

    GPU_blend(GPU_BLEND_NONE);
    if (win) {
      WM_cursor_set(win, WM_CURSOR_DEFAULT);
    }
    return;
  }

  /* Rows (row-stepped scroll: only whole rows draw, so nothing clips). */
  const bool has_scrollbar = (total > visible_rows);
  const float row_xmin = panel_x + ROW_SIDE_INSET * scale;
  const float row_xmax =
      panel_x + panel_w - ROW_SIDE_INSET * scale - (has_scrollbar ? 8.0f * scale : 0.0f);
  const float list_top = panel_top - header_h;

  bool any_hovered = false;

  for (int v = 0; v < visible_rows; v++) {
    const int idx = rt->history_scroll_row + v;
    if (idx >= total) {
      break;
    }
    const HistoryDrawEntry &entry = items[idx];
    const bool is_current = (current_id[0] != '\0') &&
                            STREQ(entry.session_id, current_id);

    const float row_top = list_top - float(v) * row_h;
    const float row_bottom = row_top - row_h;
    const float row_center = (row_top + row_bottom) * 0.5f;

    /* Hit rects at final position. */
    HistoryRowHit hit;
    BLI_rctf_init(&hit.bounds, row_xmin, row_xmax, row_bottom, row_top);
    const float del_half = DELETE_SIZE * 0.5f * scale;
    const float del_cx = row_xmax - DELETE_RIGHT_INSET * scale - del_half;
    BLI_rctf_init(&hit.delete_bounds,
                  del_cx - del_half,
                  del_cx + del_half,
                  row_center - del_half,
                  row_center + del_half);
    BLI_strncpy(hit.session_id, entry.session_id, sizeof(hit.session_id));
    hit.is_hovered = BLI_rctf_isect_pt(&hit.bounds, mouse_x, mouse_y);
    hit.delete_hovered = hit.is_hovered &&
                         BLI_rctf_isect_pt(&hit.delete_bounds, mouse_x, mouse_y);
    any_hovered |= hit.is_hovered;
    rt->history_rows.append(hit);

    /* Draw geometry follows the slide offset. */
    const float draw_top = row_top - slide;
    const float draw_bottom = row_bottom - slide;
    const float draw_center = row_center - slide;

    if (hit.is_hovered) {
      rctf hover_rect;
      BLI_rctf_init(&hover_rect, row_xmin, row_xmax, draw_bottom + 2.0f * scale,
                    draw_top - 2.0f * scale);
      float hover_col[4] = {COL_ROW_HOVER[0], COL_ROW_HOVER[1], COL_ROW_HOVER[2],
                            COL_ROW_HOVER[3] * ease};
      chat_ui_draw_rounded_rect(&hover_rect, ROW_RADIUS * scale, hover_col);
    }

    /* Accent dot on the currently open chat. */
    if (is_current) {
      const float dot_r = DOT_RADIUS * scale;
      const float dot_cx = row_xmin + 13.0f * scale;
      rctf dot;
      BLI_rctf_init(&dot, dot_cx - dot_r, dot_cx + dot_r, draw_center - dot_r,
                    draw_center + dot_r);
      float dot_col[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], COL_ACCENT[3] * ease};
      chat_ui_draw_rounded_rect(&dot, dot_r, dot_col);
    }

    /* Time label, right-aligned before the X. */
    const float del_zone_left = hit.delete_bounds.xmin - 8.0f * scale;
    float when_w = 0.0f;
    if (entry.when[0] != '\0') {
      when_w = history_text_width(entry.when, font_id, meta_px);
      float when_col[4] = {COL_MUTED[0], COL_MUTED[1], COL_MUTED[2], COL_MUTED[3] * 0.95f * ease};
      history_draw_label(entry.when, font_id, meta_px, del_zone_left - when_w,
                         draw_center - float(meta_px) * 0.35f, when_col);
    }

    /* Title, ellipsis-clipped to the space before the time label. */
    {
      const float title_x = row_xmin + TITLE_INDENT * scale;
      const float title_max_w = (del_zone_left - when_w - 10.0f * scale) - title_x;
      char clipped[224];
      history_text_ellipsis(entry.title[0] ? entry.title : "Untitled chat",
                            font_id, title_px, std::max(title_max_w, 20.0f * scale),
                            clipped, sizeof(clipped));
      const float *base_col = is_current ? COL_TITLE_CURRENT : COL_TITLE;
      float title_col[4] = {base_col[0], base_col[1], base_col[2], base_col[3] * ease};
      history_draw_label(clipped, font_id, title_px, title_x,
                         draw_center - float(title_px) * 0.35f, title_col);
    }

    /* Delete X (hover ring + glyph). */
    {
      if (hit.delete_hovered) {
        rctf ring = hit.delete_bounds;
        ring.ymin -= slide;
        ring.ymax -= slide;
        float ring_col[4] = {COL_DELETE_HOVER_BG[0], COL_DELETE_HOVER_BG[1],
                             COL_DELETE_HOVER_BG[2], COL_DELETE_HOVER_BG[3] * ease};
        chat_ui_draw_rounded_rect(&ring, del_half, ring_col);
      }
      const float *base_col = hit.delete_hovered ? COL_DELETE_HOVER : COL_DELETE;
      float x_col[4] = {base_col[0], base_col[1], base_col[2], base_col[3] * ease};
      history_draw_x_glyph(del_cx, draw_center, 4.2f * scale, x_col, scale);
    }
  }

  /* Slim scrollbar thumb when the list overflows. */
  if (has_scrollbar) {
    const float track_top = list_top - 2.0f * scale;
    const float track_bottom = panel_bottom + pad;
    const float track_h = track_top - track_bottom;
    if (track_h > 8.0f * scale) {
      const float thumb_h = std::max(track_h * float(visible_rows) / float(total),
                                     14.0f * scale);
      const float scroll_frac = (max_scroll > 0) ?
                                    float(rt->history_scroll_row) / float(max_scroll) :
                                    0.0f;
      const float thumb_top = track_top - (track_h - thumb_h) * scroll_frac - slide;
      rctf thumb;
      const float thumb_x = panel_x + panel_w - 7.0f * scale;
      BLI_rctf_init(&thumb, thumb_x, thumb_x + 3.5f * scale, thumb_top - thumb_h, thumb_top);
      float thumb_col[4] = {COL_SCROLL_THUMB[0], COL_SCROLL_THUMB[1], COL_SCROLL_THUMB[2],
                            COL_SCROLL_THUMB[3] * ease};
      chat_ui_draw_rounded_rect(&thumb, 1.75f * scale, thumb_col);
    }
  }

  GPU_blend(GPU_BLEND_NONE);

  /* Cursor: this draw runs after the empty-state draw (which also sets the
   * cursor), so setting it here wins while the overlay is open. */
  if (win) {
    WM_cursor_set(win, any_hovered ? WM_CURSOR_HAND : WM_CURSOR_DEFAULT);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Hover (region cursor callback)
 * \{ */

bool mixie_chat_history_cursor(
    wmWindow *win, MixieChatRuntime *rt, ARegion *region, float mouse_x, float mouse_y)
{
  if (!rt->history_overlay_active) {
    return false;
  }

  bool needs_redraw = false;
  bool any_hovered = false;
  for (HistoryRowHit &row : rt->history_rows) {
    const bool was_hovered = row.is_hovered;
    const bool was_delete = row.delete_hovered;
    row.is_hovered = BLI_rctf_isect_pt(&row.bounds, mouse_x, mouse_y);
    row.delete_hovered = row.is_hovered &&
                         BLI_rctf_isect_pt(&row.delete_bounds, mouse_x, mouse_y);
    needs_redraw |= (was_hovered != row.is_hovered) || (was_delete != row.delete_hovered);
    any_hovered |= row.is_hovered;
  }

  if (needs_redraw) {
    ED_region_tag_redraw(region);
  }
  WM_cursor_set(win, any_hovered ? WM_CURSOR_HAND : WM_CURSOR_DEFAULT);
  return true; /* Overlay is modal — suppress hover on elements behind it. */
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Events (called first from the region UI handler)
 * \{ */

bool mixie_chat_history_handle_event(bContext *C, const wmEvent *event)
{
  ScrArea *area = CTX_wm_area(C);
  ARegion *region = CTX_wm_region(C);
  SpaceMixieChat *smixie = history_space_from_area(area);
  if (!smixie || !region) {
    return false;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  if (!rt->history_overlay_active) {
    return false;
  }

  /* ESC closes. */
  if (event->type == EVT_ESCKEY && event->val == KM_PRESS) {
    mixie_chat_history_set_visible(C, false);
    return true;
  }

  const float mx = float(event->mval[0]);
  const float my = float(event->mval[1]);
  const bool inside_panel = BLI_rctf_isect_pt(&rt->history_panel_bounds, mx, my);
  const bool scrollable = (rt->history_total_rows > rt->history_visible_rows);
  const int max_scroll = std::max(0, rt->history_total_rows - rt->history_visible_rows);

  /* Wheel: row-stepped scroll inside the panel; consumed everywhere while
   * open so the chat behind the scrim never scrolls. */
  if (event->type == WHEELUPMOUSE || event->type == WHEELDOWNMOUSE) {
    if (inside_panel && scrollable) {
      rt->history_scroll_row += (event->type == WHEELDOWNMOUSE) ? 1 : -1;
      rt->history_scroll_row = std::max(0, std::min(rt->history_scroll_row, max_scroll));
      ED_region_tag_redraw(region);
    }
    return true;
  }

  /* Trackpad pan: accumulate into row steps. */
  if (event->type == MOUSEPAN) {
    if (inside_panel && scrollable) {
      rt->history_pan_accum += float(event->xy[1] - event->prev_xy[1]);
      const float step = 24.0f * UI_SCALE_FAC;
      while (rt->history_pan_accum >= step) {
        rt->history_scroll_row -= 1;
        rt->history_pan_accum -= step;
      }
      while (rt->history_pan_accum <= -step) {
        rt->history_scroll_row += 1;
        rt->history_pan_accum += step;
      }
      rt->history_scroll_row = std::max(0, std::min(rt->history_scroll_row, max_scroll));
      ED_region_tag_redraw(region);
    }
    return true;
  }

  if (event->type == LEFTMOUSE && event->val == KM_PRESS) {
    if (!inside_panel) {
      /* Click-away closes and consumes the click. */
      mixie_chat_history_set_visible(C, false);
      return true;
    }

    bool over_delete = false;
    const int idx = history_hit_row(rt, mx, my, &over_delete);
    if (idx >= 0) {
      /* Copy the id out — the dispatched operator redraws/rebuilds rows. */
      char session_id[128];
      BLI_strncpy(session_id, rt->history_rows[idx].session_id, sizeof(session_id));
      if (over_delete) {
        /* InvokeDefault so the operator's confirm dialog shows. */
        history_dispatch_session_op(C,
                                    region,
                                    "mixie_chat.delete_history_session",
                                    session_id,
                                    blender::wm::OpCallContext::InvokeDefault);
      }
      else {
        history_dispatch_session_op(C,
                                    region,
                                    "mixie_chat.open_history_session",
                                    session_id,
                                    blender::wm::OpCallContext::ExecDefault);
        mixie_chat_history_set_visible(C, false);
      }
    }
    /* Clicks inside the panel (rows, header, blank space) never fall
     * through to the chat behind it. */
    return true;
  }

  return false;
}

/** \} */
