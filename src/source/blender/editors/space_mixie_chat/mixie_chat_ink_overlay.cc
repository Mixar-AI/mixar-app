/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Scribble ink overlay — drawing half (events live in
 * mixie_chat_ink_events.cc, helpers in mixie_chat_ink_util.cc).
 *
 * The whole chat main region becomes a writing surface: a light scrim
 * (the conversation stays readable underneath), the captured ink strokes
 * in the live accent color with pressure-modulated opacity, and a compact
 * hint pill along the top edge carrying the state line ("write with your
 * pen…" / "Converting…" while recognition runs), a Clear button and a
 * close X. Styled with the HIST_* palette so the chat overlays read as
 * one design family.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLI_math_base.h"
#include "BLI_rect.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "BLF_api.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_ink_intern.hh"
#include "mixie_chat_intern.hh"

static const float INK_COL_STROKE[4] = CHAT_ACCENT_LIVE;

/* -------------------------------------------------------------------- */
/** \name Small Helpers
 * \{ */

static SpaceMixieChat *ink_space_from_area(ScrArea *area)
{
  if (!area || !area->spacedata.first ||
      (area->spacetype != SPACE_MIXIE_CHAT && area->spacetype != SPACE_AGENT_BUBBLE))
  {
    return nullptr;
  }
  return static_cast<SpaceMixieChat *>(area->spacedata.first);
}

static float ink_ease_out_cubic(float t)
{
  t = std::max(0.0f, std::min(1.0f, t));
  const float t1 = t - 1.0f;
  return t1 * t1 * t1 + 1.0f;
}

/** Filled circle (round stroke caps / single-tap dots). */
static void ink_draw_dot(float cx, float cy, float radius, const float color[4])
{
  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);
  const int segments = 12;
  immBegin(GPU_PRIM_TRI_FAN, segments + 2);
  immVertex2f(pos, cx, cy);
  for (int i = 0; i <= segments; i++) {
    const float a = float(i) / float(segments) * 2.0f * float(M_PI);
    immVertex2f(pos, cx + cosf(a) * radius, cy + sinf(a) * radius);
  }
  immEnd();
  immUnbindProgram();
}

/** One stroke as a smooth line strip; pressure drives per-vertex alpha. */
static void ink_draw_stroke(
    const float (*points)[3], int count, float width, const float base_color[4], float ease)
{
  if (count <= 0) {
    return;
  }
  const float dot_r = width * 0.55f;
  if (count == 1) {
    const float dot_color[4] = {base_color[0],
                               base_color[1],
                               base_color[2],
                               base_color[3] * ease * (0.55f + 0.45f * points[0][2])};
    ink_draw_dot(points[0][0], points[0][1], dot_r, dot_color);
    return;
  }

  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  uint col = GPU_vertformat_attr_add(format, "color", blender::gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);
  GPU_line_width(width);
  immBegin(GPU_PRIM_LINE_STRIP, count);
  for (int i = 0; i < count; i++) {
    const float alpha = base_color[3] * ease * (0.55f + 0.45f * points[i][2]);
    immAttr4f(col, base_color[0], base_color[1], base_color[2], alpha);
    immVertex2f(pos, points[i][0], points[i][1]);
  }
  immEnd();
  immUnbindProgram();
  GPU_line_width(1.0f);

  /* Round caps: a dot at each end hides the strip's square ends. */
  for (const int i : {0, count - 1}) {
    const float cap_color[4] = {base_color[0],
                               base_color[1],
                               base_color[2],
                               base_color[3] * ease * (0.55f + 0.45f * points[i][2]) * 0.9f};
    ink_draw_dot(points[i][0], points[i][1], dot_r * 0.8f, cap_color);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Drawing
 * \{ */

void mixie_chat_draw_ink_overlay(const bContext *C, ARegion *region)
{
  ScrArea *area = CTX_wm_area(C);
  SpaceMixieChat *smixie = ink_space_from_area(area);
  if (!smixie) {
    return;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  wmWindowManager *wm = CTX_wm_manager(C);
  const bool visible = mixie_chat_ink_read_visible(wm);

  if (visible && !rt->ink_overlay_active) {
    /* Opening edge via the Python toggle. The event-side auto-open paths
     * pre-latch ink_overlay_active after running this same init, so a
     * seeded first stroke is never reset here. */
    mixie_chat_ink_begin_session(rt);
  }
  rt->ink_overlay_active = visible;
  if (!visible) {
    /* Closing edge: pending ink was flushed by whichever close path ran
     * (event-side closes and the Python toggles both flush first). */
    if (rt->ink_point_count > 0 || rt->ink_stroke_count > 0) {
      mixie_chat_ink_reset_runtime(rt);
    }
    mixie_chat_ink_idle_timer_remove(wm);
    return;
  }

  const double now = BLI_time_now_seconds();
  const float anim_t = float((now - rt->ink_anim_start) / HIST_OPEN_ANIM_DURATION);
  const float ease = ink_ease_out_cubic(anim_t);
  const bool busy = mixie_chat_ink_read_busy(wm);
  /* Keep frames coming while the open animation or the busy pulse runs. */
  mixie_chat_anim_pump_request(C, anim_t < 1.0f || busy);

  const float scale = UI_SCALE_FAC;
  const int winx = region->winx;
  const int winy = region->winy;
  const int font_id = BLF_default();
  const int hint_px = int(12.0f * scale);

  GPU_blend(GPU_BLEND_ALPHA);

  /* Scrim — lighter than the card overlays: this is a writing surface,
   * not a dialog; the conversation stays readable. */
  {
    rctf full;
    BLI_rctf_init(&full, 0.0f, float(winx), 0.0f, float(winy));
    const float scrim[4] = {
        INK_COL_SCRIM[0], INK_COL_SCRIM[1], INK_COL_SCRIM[2], INK_COL_SCRIM[3] * ease};
    chat_ui_draw_rounded_rect(&full, 0.0f, scrim);
  }

  /* Ink strokes (completed + live). */
  {
    GPU_line_smooth(true);
    const float width = INK_STROKE_WIDTH * scale;
    for (int s = 0; s < rt->ink_stroke_count; s++) {
      const int start = rt->ink_stroke_starts[s];
      const int end = (s + 1 < rt->ink_stroke_count) ? rt->ink_stroke_starts[s + 1] :
                                                       rt->ink_point_count;
      ink_draw_stroke(&rt->ink_points[start], end - start, width, INK_COL_STROKE, ease);
    }
    GPU_line_smooth(false);
  }

  /* Hint pill along the top edge: state line + Clear + close X. */
  {
    const float hint_h = INK_HINT_H * scale;
    const float pad_x = INK_HINT_PAD_X * scale;
    const float gap = INK_HINT_GAP * scale;
    const float btn_h = INK_BTN_H * scale;
    const float clear_w = INK_CLEAR_W * scale;
    const float close_size = HIST_CLOSE_SIZE * 0.8f * scale;

    const char *hint_text;
    if (busy) {
      hint_text = "Converting handwriting…";
    }
    else if (rt->ink_store_full) {
      hint_text = "Canvas full — pause to convert";
    }
    else if (rt->ink_point_count == 0) {
      hint_text = "Scribble — write here with your pen";
    }
    else {
      hint_text = "Text appears as you write · Enter finishes · Esc closes";
    }

    BLF_size(font_id, float(hint_px));
    const float text_w = BLF_width(font_id, hint_text, strlen(hint_text));
    const float pill_w = pad_x + text_w + gap + clear_w + gap + close_size + pad_x;
    const float pill_x = (float(winx) - pill_w) * 0.5f;
    const float pill_top = float(winy) - 8.0f * scale;
    const float pill_bottom = pill_top - hint_h;

    rctf pill;
    BLI_rctf_init(&pill, pill_x, pill_x + pill_w, pill_bottom, pill_top);
    const float pill_bg[4] = {HIST_COL_PANEL[0],
                              HIST_COL_PANEL[1],
                              HIST_COL_PANEL[2],
                              0.92f * ease};
    chat_ui_draw_rounded_rect(&pill, hint_h * 0.5f, pill_bg);
    const float pill_line[4] = {HIST_COL_PANEL_OUTLINE[0],
                                HIST_COL_PANEL_OUTLINE[1],
                                HIST_COL_PANEL_OUTLINE[2],
                                HIST_COL_PANEL_OUTLINE[3] * ease};
    chat_ui_draw_rounded_rect_outline(&pill, hint_h * 0.5f, pill_line, 1.0f);

    /* State line. `busy` pulses so a slow request still reads as alive. */
    float text_col[4] = {HIST_COL_HEADER_TEXT[0],
                         HIST_COL_HEADER_TEXT[1],
                         HIST_COL_HEADER_TEXT[2],
                         (rt->ink_point_count == 0 && !busy ? 0.8f : 1.0f) * ease};
    if (busy) {
      const float pulse = 0.72f + 0.28f * float(0.5 + 0.5 * sin(now * 5.0));
      text_col[0] = INK_COL_STROKE[0];
      text_col[1] = INK_COL_STROKE[1];
      text_col[2] = INK_COL_STROKE[2];
      text_col[3] = pulse * ease;
    }
    const float baseline = pill_bottom + (hint_h - float(hint_px)) * 0.5f + 1.0f * scale;
    hist_draw_label(hint_text, font_id, hint_px, pill_x + pad_x, baseline, text_col);

    /* Clear button (text pill), disabled-looking when there is no ink. */
    {
      const float cx_min = pill_x + pad_x + text_w + gap;
      const float cy_mid = (pill_bottom + pill_top) * 0.5f;
      BLI_rctf_init(&rt->ink_clear_bounds,
                    cx_min,
                    cx_min + clear_w,
                    cy_mid - btn_h * 0.5f,
                    cy_mid + btn_h * 0.5f);
      if (rt->ink_clear_hovered && rt->ink_point_count > 0) {
        const float hover_bg[4] = {1.0f, 1.0f, 1.0f, 0.09f * ease};
        chat_ui_draw_rounded_rect(&rt->ink_clear_bounds, btn_h * 0.5f, hover_bg);
      }
      const float clear_col[4] = {HIST_COL_MUTED[0],
                                  HIST_COL_MUTED[1],
                                  HIST_COL_MUTED[2],
                                  (rt->ink_point_count > 0 ? 1.0f : 0.45f) * ease};
      BLF_size(font_id, float(hint_px));
      const float cw = BLF_width(font_id, "Clear", 5);
      hist_draw_label("Clear",
                      font_id,
                      hint_px,
                      cx_min + (clear_w - cw) * 0.5f,
                      baseline,
                      clear_col);
    }

    /* Close X. */
    {
      const float close_half = close_size * 0.5f;
      const float close_cx = pill_x + pill_w - pad_x - close_half;
      const float close_cy = (pill_bottom + pill_top) * 0.5f;
      BLI_rctf_init(&rt->ink_close_bounds,
                    close_cx - close_half,
                    close_cx + close_half,
                    close_cy - close_half,
                    close_cy + close_half);
      if (rt->ink_close_hovered) {
        const float hover_bg[4] = {1.0f, 1.0f, 1.0f, 0.09f * ease};
        chat_ui_draw_rounded_rect(&rt->ink_close_bounds, close_half, hover_bg);
      }
      const float x_col[4] = {HIST_COL_HEADER_TEXT[0],
                              HIST_COL_HEADER_TEXT[1],
                              HIST_COL_HEADER_TEXT[2],
                              0.9f * ease};
      hist_draw_x_glyph(close_cx, close_cy, close_half * 0.45f, x_col, scale);
    }
  }

  GPU_blend(GPU_BLEND_NONE);
}

/** \} */
