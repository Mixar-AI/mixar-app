/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Flow-style ruler, camera strip, beat handles, and playhead drawing.
 */

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_rect.h"
#include "BLI_string.h"

#include "DNA_screen_types.h"

#include "GPU_immediate.hh"
#include "GPU_immediate_util.hh"
#include "GPU_shader_shared_utils.hh"
#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_interface_icons.hh"
#include "UI_resources.hh"

#include "view3d_director_timeline.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

constexpr float STRIP_COLOR[4] = {1.0f, 0.72f, 0.48f, 1.0f};
constexpr float STRIP_HOVER_COLOR[4] = {1.0f, 0.76f, 0.54f, 1.0f};
/* Keyframes are DIAMONDS with a dark outline, the shape every Blender editor
 * marks a key with. They used to be rounded pills in #FFD4B0 on a #FFB87A
 * strip — two shades of the same orange, which is no contrast at all. The
 * outline is what makes them read whatever the strip is doing underneath. */
constexpr float HANDLE_COLOR[4] = {1.0f, 0.97f, 0.93f, 1.0f};
constexpr float HANDLE_ACTIVE_COLOR[4] = {1.0f, 1.0f, 1.0f, 1.0f};
constexpr float HANDLE_SELECTED_COLOR[4] = {0.13f, 0.60f, 0.33f, 1.0f};
constexpr float HANDLE_OUTLINE_COLOR[4] = {0.10f, 0.07f, 0.05f, 0.92f};
constexpr float STRIP_TEXT_COLOR[4] = {1.0f, 0.98f, 0.96f, 1.0f};
/** Ring around a selected handle, and the box-select rubber band. */
constexpr float SELECTED_OUTLINE_COLOR[4] = {1.0f, 1.0f, 1.0f, 0.95f};
constexpr float BOX_FILL_COLOR[4] = {1.0f, 1.0f, 1.0f, 0.08f};
constexpr float BOX_LINE_COLOR[4] = {1.0f, 1.0f, 1.0f, 0.45f};

/** Filled diamond centred on (\a cx, \a cy) — the keyframe mark. */
void draw_diamond(const float cx, const float cy, const float radius, const float color[4])
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);
  immBegin(GPU_PRIM_TRI_FAN, 4);
  immVertex2f(pos, cx, cy + radius);
  immVertex2f(pos, cx + radius, cy);
  immVertex2f(pos, cx, cy - radius);
  immVertex2f(pos, cx - radius, cy);
  immEnd();
  immUnbindProgram();
}

/** Its outline; drawn after the fill so it is never painted over. */
void draw_diamond_outline(
    const float cx, const float cy, const float radius, const float width, const float color[4])
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);
  GPU_line_width(width);
  immBegin(GPU_PRIM_LINE_LOOP, 4);
  immVertex2f(pos, cx, cy + radius);
  immVertex2f(pos, cx + radius, cy);
  immVertex2f(pos, cx, cy - radius);
  immVertex2f(pos, cx - radius, cy);
  immEnd();
  GPU_line_width(1.0f);
  immUnbindProgram();
}

void draw_camera_icon(const float x, const float y, const float size)
{
  const uchar color[4] = {255, 250, 245, 255};
  ui::icon_draw_ex(
      x, y, ICON_CAMERA_DATA, 16.0f / size, 1.0f, 0.0f, color, false, UI_NO_ICON_OVERLAY_TEXT);
  GPU_blend(GPU_BLEND_ALPHA);
}

void reset_view(const DirectorViewState &state, DirectorTimelineRuntime *runtime)
{
  const float fps = std::max(state.fps, 0.001f);
  const int first = state.beats.is_empty() ? state.scene_frame_start : state.frame_start;
  const int last = state.beats.is_empty() ? state.scene_frame_start : state.frame_end;
  runtime->view_start_frame = float(std::min(state.scene_frame_start, first));
  runtime->view_span_frames = std::max(fps * 5.0f, float(last) + fps - runtime->view_start_frame);
  runtime->view_initialized = true;
  runtime->view_user_modified = false;
}

void sync_view(const DirectorViewState &state, DirectorTimelineRuntime *runtime)
{
  const int first = state.beats.is_empty() ? state.scene_frame_start : state.frame_start;
  const int last = state.beats.is_empty() ? state.scene_frame_start : state.frame_end;
  const int count = int(state.beats.size());
  const bool shot_changed = runtime->shot_identity != state.shot_identity;
  /* Shot or beat-count changes are new content and may need a re-fit.
   * Retiming the first or last keyframe is not: auto-fitting would keep that
   * handle glued to the same pixel, so end keys look undraggable while
   * middle ones slide. */
  const bool count_changed = runtime->content_count != count;
  if (!runtime->view_initialized || shot_changed ||
      (count_changed && !runtime->view_user_modified))
  {
    reset_view(state, runtime);
  }
  /* Before the identity and count are overwritten: an index means nothing
   * across a shot switch or a beat added or removed. */
  director_timeline_selection_sync(runtime, state.shot_identity, count);
  runtime->shot_identity = state.shot_identity;
  runtime->content_first = first;
  runtime->content_last = last;
  runtime->content_count = count;
}

void draw_strip(const DirectorViewState &state,
                DirectorTimelineRuntime *runtime,
                const float strip_y,
                const float strip_h)
{
  runtime->beat_hits.clear();
  BLI_rctf_init(&runtime->strip_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  if (state.beats.is_empty()) {
    return;
  }
  const float width = BLI_rctf_size_x(&runtime->viewport_bounds);
  const auto frame_x = [&](const float frame) {
    return runtime->viewport_bounds.xmin +
           (frame - runtime->view_start_frame) / runtime->view_span_frames * width;
  };
  float raw_start = frame_x(float(state.frame_start));
  float raw_end = frame_x(float(state.frame_end));
  if (state.beats.size() == 1) {
    raw_start -= 9.0f * UI_SCALE_FAC;
    raw_end += 9.0f * UI_SCALE_FAC;
  }
  const float visible_start = std::max(raw_start, runtime->viewport_bounds.xmin);
  const float visible_end = std::min(raw_end, runtime->viewport_bounds.xmax);
  if (visible_end <= visible_start) {
    return;
  }
  runtime->strip_bounds = {visible_start, visible_end, strip_y, strip_y + strip_h};
  const float *strip_color = runtime->strip_hovered ? STRIP_HOVER_COLOR : STRIP_COLOR;
  director_timeline_draw_round_rect(runtime->strip_bounds, 7.0f * UI_SCALE_FAC, strip_color);

  const float font_size = 12.0f * UI_SCALE_FAC;
  const float icon_size = 16.0f * UI_SCALE_FAC;
  const float label_x = visible_start + 27.0f * UI_SCALE_FAC;
  const float label_width = icon_size + 7.0f * UI_SCALE_FAC +
                            director_timeline_text_width(state.camera_name.c_str(), font_size);
  if (visible_end - label_x > label_width) {
    draw_camera_icon(label_x, strip_y + (strip_h - icon_size) * 0.5f, icon_size);
    director_timeline_draw_text(state.camera_name.c_str(),
              label_x + icon_size + 7.0f * UI_SCALE_FAC,
              strip_y + (strip_h - font_size) * 0.5f + 1.0f * UI_SCALE_FAC,
              font_size,
              STRIP_TEXT_COLOR);
  }

  const float handle_w = std::max(9.0f, 11.0f * UI_SCALE_FAC);
  const float hit_pad = 10.0f * UI_SCALE_FAC;
  for (const DirectorBeatView &beat : state.beats) {
    const float x = frame_x(float(beat.frame));
    const float hit_xmin = x - hit_pad;
    const float hit_xmax = x + hit_pad;
    /* Keep a partly-visible handle hittable. The last keyframe sits on the
     * strip's right edge; dropping it when its centre crosses xmax made
     * that handle undraggable. */
    if (hit_xmax < runtime->viewport_bounds.xmin ||
        hit_xmin > runtime->viewport_bounds.xmax)
    {
      continue;
    }
    const bool selected = director_timeline_is_selected(*runtime, beat.index);
    const bool highlighted = beat.index == state.active_beat_index ||
                             beat.index == runtime->hovered_beat;
    const float cy = strip_y + strip_h * 0.5f;
    /* Big enough to aim at, never taller than the strip carrying it. */
    const float radius = std::max(5.0f * UI_SCALE_FAC,
                                  std::min(handle_w * 0.75f, strip_h * 0.42f));
    const float *fill = selected  ? HANDLE_SELECTED_COLOR :
                        highlighted ? HANDLE_ACTIVE_COLOR :
                                      HANDLE_COLOR;
    draw_diamond(x, cy, radius, fill);
    /* The outline is what makes the mark read at all: a fill alone is two
     * shades of the strip's own orange. A selected key gets a thicker one. */
    draw_diamond_outline(x,
                         cy,
                         radius,
                         std::max(1.0f, (selected ? 2.0f : 1.2f) * UI_SCALE_FAC),
                         selected ? SELECTED_OUTLINE_COLOR : HANDLE_OUTLINE_COLOR);
    DirectorTimelineBeatHit hit;
    hit.bounds = {hit_xmin,
                  hit_xmax,
                  strip_y - 4.0f * UI_SCALE_FAC,
                  strip_y + strip_h + 4.0f * UI_SCALE_FAC};
    hit.index = beat.index;
    runtime->beat_hits.append(hit);
  }
}

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Shared paint primitives
 *
 * The dock draws in two translation units — this one paints the strip and
 * its keyframes, `view3d_director_timeline_ruler.cc` paints the ruler and
 * the playhead — and both need these. Declared in the timeline header so
 * neither file grows a second copy that can drift.
 * \{ */

void director_timeline_draw_rect(
    const float x1, const float y1, const float x2, const float y2, const float color[4])
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);
  immRectf(pos, x1, y1, x2, y2);
  immUnbindProgram();
}

void director_timeline_draw_round_rect(const rctf &rect,
                                      const float radius,
                                      const float color[4])
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&rect, true, radius, color);
}

void director_timeline_draw_text(
    const char *text, const float x, const float y, const float size, const float color[4])
{
  const int font = BLF_default();
  BLF_size(font, size);
  BLF_color4fv(font, color);
  BLF_position(font, x, y, 0.0f);
  BLF_draw(font, text, strlen(text));
  GPU_blend(GPU_BLEND_ALPHA);
}

float director_timeline_text_width(const char *text, const float size)
{
  const int font = BLF_default();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}

/** \} */

void view3d_director_timeline_draw_content(const ARegion *region,
                                           const DirectorViewState &state,
                                           DirectorTimelineRuntime *runtime,
                                           const int margin,
                                           const int /*unit*/,
                                           const int content_top)
{
  sync_view(state, runtime);
  const float u = UI_SCALE_FAC;
  runtime->viewport_bounds = {float(margin) + 26.0f * u,
                              float(region->winx - margin) - 26.0f * u,
                              float(margin),
                              float(content_top)};
  /* Bottom-up: ruler ticks on the dock floor, labels above them, then the
   * camera strip — and the playhead's frame pill keeps a band of its own at
   * the top.
   *
   * The pill used to be drawn into the same band as the strip, so scrubbing
   * dragged it across the keyframe handles: a rounded grey chip sliding over
   * the very markers the director is trying to aim at. The playhead LINE
   * still crosses them, which is what a playhead is for; only the label moved
   * out of their way. */
  const float tick_base = float(margin) + 10.0f * u;
  /* The ruler's tick and label band, from the same tokens the ruler draws
   * with, then the 12 px label itself. */
  const float label_top = tick_base +
                          (DIRECTOR_RULER_TICK_H + DIRECTOR_RULER_LABEL_GAP) * u +
                          12.0f * u;
  const float available = float(content_top) - label_top - 8.0f * u;
  /* The strip is LOAD-BEARING: the keyframes live on it, and a strip of zero
   * height takes every keyframe with it. So the pill's band is what gives way
   * when the dock is short, and the strip keeps a floor below which it would
   * not read as a row at all — the pill overlapping it again is the lesser
   * failure, and only happens on a dock dragged smaller than its own
   * preferred size. (`VIEW3D_DIRECTOR_TIMELINE_HEIGHT` is sized so the full
   * layout fits; `tests/director/test_timeline_layout.py` does that
   * arithmetic so the budget can never silently go to zero again.) */
  const float pill_band = (DIRECTOR_PLAYHEAD_PILL_H + DIRECTOR_PLAYHEAD_PILL_GAP) * u;
  float strip_h = std::min(DIRECTOR_STRIP_H * u, available - pill_band);
  if (strip_h < DIRECTOR_STRIP_MIN_H * u) {
    strip_h = std::clamp(available, DIRECTOR_STRIP_MIN_H * u, DIRECTOR_STRIP_H * u);
  }
  const float strip_y = label_top + 6.0f * u;
  /* Everything under the strip is the ruler row, and the ruler row is the
   * only place the playhead can be dragged from. */
  runtime->ruler_bounds = {runtime->viewport_bounds.xmin,
                           runtime->viewport_bounds.xmax,
                           runtime->viewport_bounds.ymin,
                           strip_y - 2.0f * u};

  director_timeline_draw_ruler(state, *runtime, tick_base);
  draw_strip(state, runtime, strip_y, strip_h);
  director_timeline_draw_playhead(
      state, runtime, tick_base, float(content_top) - 6.0f * u);
  /* Last of the content, so it dims the whole stack at once. */
  director_timeline_draw_range_scrim(
      state, *runtime, runtime->viewport_bounds.ymin, float(content_top));

  /* The box-select rubber band, over everything it is selecting — including
   * the scrim, since a selection is a live gesture and must stay legible. */
  rctf box;
  if (director_timeline_box_rect(*runtime, &box)) {
    director_timeline_draw_round_rect(box, 2.0f * u, BOX_FILL_COLOR);
    ui::draw_roundbox_corner_set(ui::CNR_ALL);
    ui::draw_roundbox_4fv_ex(
        &box, nullptr, nullptr, 1.0f, BOX_LINE_COLOR, std::max(1.0f, u), 2.0f * u);
  }
}
}  // namespace blender
