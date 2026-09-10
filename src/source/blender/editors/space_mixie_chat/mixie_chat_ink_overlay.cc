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
#include <array>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>

#include "BLI_math_base.h"
#include "BLI_rect.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"

#include "BLF_api.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "RNA_access.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_ink_intern.hh"
#include "mixie_chat_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

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

/* Draw-time Catmull-Rom resampling of one captured stroke. Pointer samples
 * are distance-decimated on capture (INK_MIN_SAMPLE_DIST), so a fast stroke
 * is a handful of points and every corner of the polyline showed. The spline
 * passes through every captured sample and only adds points between them;
 * the store itself is never touched — the recogniser reads the raw samples,
 * and this is only what the eye sees. Pressure interpolates linearly. */
static constexpr int INK_SMOOTH_SUBDIV = 4;
/* Segments already shorter than this (base px) are sub-pixel curves. */
static constexpr float INK_SMOOTH_MIN_SEG = 2.5f;

static void ink_smooth_stroke(const float (*points)[3],
                              const int count,
                              const float min_seg,
                              std::vector<std::array<float, 3>> &r_out)
{
  r_out.clear();
  if (count <= 0) {
    return;
  }
  r_out.reserve(size_t(count) * INK_SMOOTH_SUBDIV + 1);
  r_out.push_back({points[0][0], points[0][1], points[0][2]});
  if (count < 3) {
    for (int i = 1; i < count; i++) {
      r_out.push_back({points[i][0], points[i][1], points[i][2]});
    }
    return;
  }
  const float min_seg_sq = min_seg * min_seg;
  for (int i = 0; i < count - 1; i++) {
    const float *p0 = points[std::max(i - 1, 0)];
    const float *p1 = points[i];
    const float *p2 = points[i + 1];
    const float *p3 = points[std::min(i + 2, count - 1)];
    const float dx = p2[0] - p1[0];
    const float dy = p2[1] - p1[1];
    if (dx * dx + dy * dy < min_seg_sq) {
      r_out.push_back({p2[0], p2[1], p2[2]});
      continue;
    }
    for (int k = 1; k <= INK_SMOOTH_SUBDIV; k++) {
      if (k == INK_SMOOTH_SUBDIV) {
        r_out.push_back({p2[0], p2[1], p2[2]});
        break;
      }
      const float t = float(k) / float(INK_SMOOTH_SUBDIV);
      const float t2 = t * t;
      const float t3 = t2 * t;
      std::array<float, 3> q;
      for (int c = 0; c < 2; c++) {
        q[c] = 0.5f * ((2.0f * p1[c]) + (-p0[c] + p2[c]) * t +
                       (2.0f * p0[c] - 5.0f * p1[c] + 4.0f * p2[c] - p3[c]) * t2 +
                       (-p0[c] + 3.0f * p1[c] - 3.0f * p2[c] + p3[c]) * t3);
      }
      q[2] = p1[2] + (p2[2] - p1[2]) * t;
      r_out.push_back(q);
    }
  }
}

/** One resampled stroke through Blender's anti-aliased polyline shader at the
 * real width. GPU_line_width is deliberately NOT used: the Metal backend has
 * no wide lines and drew the strip one pixel wide with no anti-aliasing at
 * all — the jagged hairline this replaced. Per-vertex alpha still follows
 * pressure. */
static void ink_draw_polyline(const std::vector<std::array<float, 3>> &pts,
                              const float width,
                              const float base_color[4],
                              const float ease)
{
  if (pts.size() < 2) {
    return;
  }
  float viewport[4];
  GPU_viewport_size_get_f(viewport);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32_32);
  const uint col = GPU_vertformat_attr_add(
      format, "color", blender::gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_POLYLINE_SMOOTH_COLOR);
  immUniform2fv("viewportSize", &viewport[2]);
  immUniform1f("lineWidth", width);
  immUniform1i("lineSmooth", 1);
  immBegin(GPU_PRIM_LINE_STRIP, int(pts.size()));
  for (const std::array<float, 3> &p : pts) {
    const float alpha = base_color[3] * ease * (0.55f + 0.45f * p[2]);
    immAttr4f(col, base_color[0], base_color[1], base_color[2], alpha);
    immVertex3f(pos, p[0], p[1], 0.0f);
  }
  immEnd();
  immUnbindProgram();
}

/** One stroke: resampled, then an anti-aliased polyline; pressure drives
 * per-vertex alpha. */
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

  /* Scratch for the resampled stroke — main thread only, reused per stroke. */
  static std::vector<std::array<float, 3>> smooth;
  ink_smooth_stroke(points, count, INK_SMOOTH_MIN_SEG * (width / INK_STROKE_WIDTH), smooth);
  ink_draw_polyline(smooth, width, base_color, ease);

  /* Round caps: a dot at each end hides the strip's square ends. */
  for (const int i : {0, count - 1}) {
    const float cap_color[4] = {base_color[0],
                               base_color[1],
                               base_color[2],
                               base_color[3] * ease * (0.55f + 0.45f * points[i][2]) * 0.9f};
    ink_draw_dot(points[i][0], points[i][1], dot_r * 0.8f, cap_color);
  }
}

void mixie_chat_ink_draw_strokes(
    MixieChatRuntime *rt, float scale, float ease, float offset_x, float offset_y)
{
  if (!rt || rt->ink_stroke_count <= 0) {
    return;
  }
  GPU_matrix_push();
  GPU_matrix_translate_2f(offset_x, offset_y);
  GPU_line_smooth(true);
  const float width = INK_STROKE_WIDTH * scale;
  for (int s = 0; s < rt->ink_stroke_count; s++) {
    const int start = rt->ink_stroke_starts[s];
    const int end = (s + 1 < rt->ink_stroke_count) ? rt->ink_stroke_starts[s + 1] :
                                                     rt->ink_point_count;
    ink_draw_stroke(&rt->ink_points[start], end - start, width, INK_COL_STROKE, ease);
  }
  GPU_line_smooth(false);
  GPU_matrix_pop();
}

void mixie_chat_draw_ink_strokes_for_region(const bContext *C, ARegion *region)
{
  if (!C || !region) {
    return;
  }
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!mixie_chat_ink_read_visible(wm)) {
    return;
  }
  ScrArea *area = CTX_wm_area(C);
  SpaceMixieChat *smixie = ink_space_from_area(area);
  if (!smixie) {
    return;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  if (!rt || !rt->ink_overlay_active || rt->ink_stroke_count <= 0) {
    return;
  }
  ARegion *main_region = mixie_chat_ink_area_main_region(area);
  if (!main_region) {
    return;
  }

  const float ox = float(main_region->winrct.xmin - region->winrct.xmin);
  const float oy = float(main_region->winrct.ymin - region->winrct.ymin);
  const float scale = UI_SCALE_FAC;
  const float ease = 1.0f;

  GPU_blend(GPU_BLEND_ALPHA);
  mixie_chat_ink_draw_strokes(rt, scale, ease, ox, oy);
  GPU_blend(GPU_BLEND_NONE);
}

/**
 * The writing surface itself: scrim, then lattice, clipped to *rect*.
 *
 * The Agent island's composer paints its own share of the panel with this, so
 * that band is the SAME surface as the transcript above it rather than a box
 * ruled across the pad. It used to be pinned to the input line's rect, which
 * left a strip of bare panel above and below it and sat inside the
 * transcript's own left and right edges — three straight lines where there
 * should have been none.
 */
void mixie_chat_ink_draw_canvas(const rctf *rect,
                                const float scale,
                                const float origin_x,
                                const float origin_y,
                                const float ease)
{
  if (!rect || rect->xmin >= rect->xmax || rect->ymin >= rect->ymax) {
    return;
  }
  GPU_blend(GPU_BLEND_ALPHA);
  const float scrim[4] = {INK_CANVAS_SCRIM[0],
                          INK_CANVAS_SCRIM[1],
                          INK_CANVAS_SCRIM[2],
                          INK_CANVAS_SCRIM[3] * ease};
  chat_ui_draw_rounded_rect(rect, 0.0f, scrim);
  mixie_chat_ink_draw_grid(rect, scale, origin_x, origin_y, ease);
}

/**
 * The writing surface's dot lattice, clipped to *rect*.
 *
 * ONE definition, because the canvas is not confined to the transcript: the
 * Agent island's composer paints the same surface over its input line so the
 * two read as one sheet of paper. A second copy of the metrics there drifted
 * — it stepped by the island's width-derived unit instead of UI_SCALE_FAC, so
 * the patch's dots came out at 24px against the canvas's 36px and the grid
 * visibly changed pitch at the region seam.
 *
 * `origin` anchors the lattice, so a caller drawing into a different region
 * passes that region's offset and gets the SAME dots continuing, rather than
 * a lattice that restarts at its own corner.
 *
 * The reserved vertex count must equal what the loop emits. Immediate mode
 * hands back a buffer sized by `immBegin` and draws all of it; emitting fewer
 * vertices than reserved leaves whatever the previous draw put there, which
 * reaches the screen as stray triangles from stale coordinates.
 */
void mixie_chat_ink_draw_grid(const rctf *rect,
                              const float scale,
                              const float origin_x,
                              const float origin_y,
                              const float ease)
{
  if (!rect || rect->xmin >= rect->xmax || rect->ymin >= rect->ymax) {
    return;
  }
  const float grid_step = INK_GRID_STEP * scale;
  const float dot_radius = INK_GRID_DOT_R * scale;
  const int segments = INK_GRID_SEGMENTS;
  if (grid_step <= 0.0f) {
    return;
  }

  /* A dot is drawn when its DISC meets the rect, so the lattice runs to the
   * edge rather than stopping a step short of it. Deriving the loop bounds
   * from the same inflated rect is what keeps the count exact: there is no
   * per-dot test inside the loop that could skip one. */
  const int first_col = int(ceilf((rect->xmin - dot_radius - origin_x) / grid_step));
  const int last_col = int(floorf((rect->xmax + dot_radius - origin_x) / grid_step));
  const int first_row = int(ceilf((rect->ymin - dot_radius - origin_y) / grid_step));
  const int last_row = int(floorf((rect->ymax + dot_radius - origin_y) / grid_step));
  if (last_col < first_col || last_row < first_row) {
    return;
  }
  const int dot_count = (last_col - first_col + 1) * (last_row - first_row + 1);

  const float dot_color[4] = {0.45f, 0.45f, 0.45f, 0.35f * ease};

  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  GPU_blend(GPU_BLEND_ALPHA);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(dot_color);

  immBegin(GPU_PRIM_TRIS, dot_count * segments * 3);
  for (int r = first_row; r <= last_row; r++) {
    const float cy = origin_y + float(r) * grid_step;
    for (int c = first_col; c <= last_col; c++) {
      const float cx = origin_x + float(c) * grid_step;
      for (int s = 0; s < segments; s++) {
        const float a0 = (2.0f * float(M_PI) * float(s)) / float(segments);
        const float a1 = (2.0f * float(M_PI) * float(s + 1)) / float(segments);
        immVertex2f(pos, cx, cy);
        immVertex2f(pos, cx + cosf(a0) * dot_radius, cy + sinf(a0) * dot_radius);
        immVertex2f(pos, cx + cosf(a1) * dot_radius, cy + sinf(a1) * dot_radius);
      }
    }
  }
  immEnd();
  immUnbindProgram();
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

  /* Translucent surface with the moodboard background pattern over the chat window. */
  {
    rctf full;
    BLI_rctf_init(&full, 0.0f, float(winx), 0.0f, float(winy));
    mixie_chat_ink_draw_canvas(&full, scale, 0.0f, 0.0f, ease);
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
      hint_text = "Pause to convert · Enter converts now · Esc closes";
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

}  // namespace blender
