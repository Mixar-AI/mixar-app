/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * The dock's layout and its camera strip: the label column, the tinted span
 * of the camera's keys, the native keys and the rings on keyframes with an
 * image.
 */

#include <algorithm>
#include <array>
#include <cfloat>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>

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

/* The take's span is a TINT of a light grey with a firm edge in it. It is
 * the neutral the keys are read against: a tinted bar of its own hue (it was
 * the strip's orange) competed with the green key dots for the same row, and
 * a solid bar turned them to mush outright. */
constexpr float STRIP_COLOR[4] = {0.82f, 0.83f, 0.85f, 0.62f};
constexpr float STRIP_FILL_COLOR[4] = {0.82f, 0.83f, 0.85f, 0.13f};
constexpr float STRIP_HOVER_FILL_COLOR[4] = {0.82f, 0.83f, 0.85f, 0.22f};
constexpr float LABEL_TEXT_COLOR[4] = {1.0f, 0.98f, 0.96f, 1.0f};
/** A thin ring around a keyframe that carries a captured image. */
constexpr float STILL_RING_COLOR[4] = {1.0f, 1.0f, 1.0f, 0.78f};
/** The box-select rubber band. */
constexpr float BOX_FILL_COLOR[4] = {1.0f, 1.0f, 1.0f, 0.08f};
constexpr float BOX_LINE_COLOR[4] = {1.0f, 1.0f, 1.0f, 0.45f};

void draw_icon(const float x, const float y, const int icon, const float size)
{
  const uchar color[4] = {255, 250, 245, 255};
  ui::icon_draw_ex(x, y, icon, 16.0f / size, 1.0f, 0.0f, color, false, UI_NO_ICON_OVERLAY_TEXT);
  GPU_blend(GPU_BLEND_ALPHA);
}

/**
 * The frames the dock fits: every key the camera carries and every beat.
 * Falls back to the scene's start, so an empty shot opens on it.
 */
void content_range(const DirectorViewState &state, float *r_first, float *r_last)
{
  float first = float(state.scene_frame_start);
  float last = first;
  bool any = director_timeline_camera_key_range(state.shot_camera, &first, &last);
  if (!state.beats.is_empty()) {
    first = any ? std::min(first, float(state.frame_start)) : float(state.frame_start);
    last = any ? std::max(last, float(state.frame_end)) : float(state.frame_end);
    any = true;
  }
  *r_first = first;
  *r_last = last;
}

void reset_view(const DirectorViewState &state, DirectorTimelineRuntime *runtime)
{
  const float fps = std::max(state.fps, 0.001f);
  float first, last;
  content_range(state, &first, &last);
  runtime->view_start_frame = std::min(float(state.scene_frame_start), std::floor(first));
  runtime->view_span_frames = std::max(fps * 5.0f,
                                       std::ceil(last) + fps - runtime->view_start_frame);
  runtime->view_initialized = true;
  runtime->view_user_modified = false;
}

void sync_view(const DirectorViewState &state, DirectorTimelineRuntime *runtime)
{
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
  if (shot_changed) {
    /* A box started over another shot's keys selects nothing of this one. */
    runtime->box_arming = false;
    runtime->box_dragging = false;
  }
  runtime->shot_identity = state.shot_identity;
  runtime->content_count = count;
}

/** \a text cut down with an ellipsis until it fits \a max_width. */
std::string fit_text(const std::string &text, const float size, const float max_width)
{
  if (director_timeline_text_width(text.c_str(), size) <= max_width) {
    return text;
  }
  std::string cut = text;
  while (!cut.empty()) {
    /* Drop a whole UTF-8 sequence, never half of one. */
    size_t len = cut.size() - 1;
    while (len > 0 && (uchar(cut[len]) & 0xC0) == 0x80) {
      len--;
    }
    cut.resize(len);
    const std::string candidate = cut + "\xe2\x80\xa6" /* U+2026 */;
    if (director_timeline_text_width(candidate.c_str(), size) <= max_width) {
      return candidate;
    }
  }
  return std::string();
}

/**
 * The camera's name in its own column left of the keys — the Timeline's
 * channel list. It used to sit INSIDE the bar, where a key on every frame
 * drew straight over it.
 */
void draw_label(const DirectorViewState &state,
                DirectorTimelineRuntime *runtime,
                const float strip_y,
                const float strip_h)
{
  const rctf &label = runtime->label_bounds;
  const float u = UI_SCALE_FAC;
  const float font_size = 12.0f * u;
  const float icon_size = 16.0f * u;
  const float text_x = label.xmin + icon_size + 6.0f * u;
  if (!state.has_camera || label.xmax - text_x <= 0.0f) {
    return;
  }
  draw_icon(label.xmin, strip_y + (strip_h - icon_size) * 0.5f, ICON_CAMERA_DATA, icon_size);
  const std::string name = fit_text(state.camera_name, font_size, label.xmax - text_x);
  director_timeline_draw_text(name.c_str(),
                              text_x,
                              strip_y + (strip_h - font_size) * 0.5f + 1.0f * u,
                              font_size,
                              LABEL_TEXT_COLOR);
}

/** Put each beat on its key column, for its ring and the right-click menu. */
void attach_beats(const DirectorViewState &state, DirectorTimelineRuntime *runtime)
{
  for (DirectorTimelineKeyHit &hit : runtime->key_hits) {
    for (const DirectorBeatView &beat : state.beats) {
      if (std::abs(float(beat.frame) - hit.frame) <= 0.5f) {
        hit.beat = beat.index;
        hit.beat_has_still = beat.has_still;
        break;
      }
    }
  }
}

/**
 * A thin ring around each keyframe that carries a captured image — the ones
 * Export to Moodboard sends as Keyframe Images.
 *
 * The key itself already says it is a keyframe and not a recorded sample
 * (Blender's key types draw differently); the ring adds only what the key
 * cannot. It used to be an icon chip jammed against the bar's top edge,
 * which read as a rendering glitch. Rings are thinned when zoomed out so they
 * never chain into one another.
 */
void draw_still_rings(const DirectorTimelineRuntime &runtime, const float cy)
{
  const float u = UI_SCALE_FAC;
  const float radius = 8.0f * u;
  bool any = false;
  for (const DirectorTimelineKeyHit &hit : runtime.key_hits) {
    any |= hit.beat >= 0 && hit.beat_has_still;
  }
  if (!any) {
    return;
  }
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_POLYLINE_UNIFORM_COLOR);
  float viewport[4];
  GPU_viewport_size_get_f(viewport);
  immUniform2fv("viewportSize", &viewport[2]);
  immUniform1f("lineWidth", std::max(1.0f, 1.25f * u));
  immUniformColor4fv(STILL_RING_COLOR);
  float last_x = -FLT_MAX;
  for (const DirectorTimelineKeyHit &hit : runtime.key_hits) {
    if (hit.beat < 0 || !hit.beat_has_still || hit.x - last_x < radius * 2.0f + 2.0f * u) {
      continue;
    }
    last_x = hit.x;
    imm_draw_circle_wire_2d(pos, hit.x, cy, radius, 24);
  }
  immUnbindProgram();
}

void draw_strip(const ARegion *region,
                const DirectorViewState &state,
                DirectorTimelineRuntime *runtime,
                const float strip_y,
                const float strip_h)
{
  runtime->key_hits.clear();
  BLI_rctf_init(&runtime->strip_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  const float u = UI_SCALE_FAC;
  /* From the dock's inner edge to just short of the keys: the gap is wider
   * than half a key mark, so a key on the view's first frame stays clear. */
  runtime->label_bounds = {runtime->viewport_bounds.xmin - (DIRECTOR_LABEL_W - 6.0f) * u,
                           runtime->viewport_bounds.xmin - 12.0f * u,
                           strip_y,
                           strip_y + strip_h};
  draw_label(state, runtime, strip_y, strip_h);

  float first = 0.0f;
  float last = 0.0f;
  bool any = director_timeline_collect_keys(
      state.shot_camera, runtime, strip_y, strip_h, &first, &last);
  attach_beats(state, runtime);
  for (const DirectorBeatView &beat : state.beats) {
    first = any ? std::min(first, float(beat.frame)) : float(beat.frame);
    last = any ? std::max(last, float(beat.frame)) : float(beat.frame);
    any = true;
  }
  const float cy = strip_y + strip_h * 0.5f;
  if (any) {
    /* The span covers what the camera is animated over — its first key to
     * its last, the recorded samples as well as the beats — padded so an end
     * key, and the image ring around it, sit inside the rounded ends. */
    const float width = BLI_rctf_size_x(&runtime->viewport_bounds);
    const auto frame_x = [&](const float frame) {
      return runtime->viewport_bounds.xmin +
             (frame - runtime->view_start_frame) / runtime->view_span_frames * width;
    };
    const float pad = 13.0f * u;
    const float visible_start = std::max(frame_x(first) - pad, runtime->viewport_bounds.xmin);
    const float visible_end = std::min(frame_x(last) + pad, runtime->viewport_bounds.xmax);
    if (visible_end > visible_start) {
      runtime->strip_bounds = {visible_start, visible_end, strip_y, strip_y + strip_h};
      ui::draw_roundbox_corner_set(ui::CNR_ALL);
      ui::draw_roundbox_4fv_ex(&runtime->strip_bounds,
                               runtime->strip_hovered ? STRIP_HOVER_FILL_COLOR : STRIP_FILL_COLOR,
                               nullptr,
                               1.0f,
                               STRIP_COLOR,
                               std::max(1.0f, u),
                               7.0f * u);
    }
  }
  /* The image rings, then every key the camera carries — each one a handle —
   * on top, so a ring can never cover a key. */
  draw_still_rings(*runtime, cy);
  director_timeline_draw_keys(*runtime, region, cy);
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
  /* The camera's label owns a column of its own on the left; the keys start
   * past it, so none can ever draw over the name. */
  runtime->viewport_bounds = {float(margin) + DIRECTOR_LABEL_W * u,
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
  draw_strip(region, state, runtime, strip_y, strip_h);
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
