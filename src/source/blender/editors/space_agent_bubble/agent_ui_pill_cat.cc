/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Mixie, the resting-pill mascot. Pose comes from `mixie_cat_eval_pose`;
 * this file paints the shared black silhouette and luminous eyes at any UI
 * scale.
 */

#include <algorithm>
#include <cmath>

#include "BLI_listbase.h"
#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_state.hh"

#include "../interface/interface_qa_inspect.hh"

#include "agent_ui_cat_style.hh"
#include "agent_ui_pill_cat.hh"
#include "agent_ui_pill_cat_pose.hh"

namespace blender {

namespace {

rcti g_last_cat_rect = {};
bool g_last_cat_valid = false;

/** Geometry owns its pixel-sized coverage fringe. Widget roundbox shaders
 * assume pixel-space coordinates and cannot be used under the mascot scale. */
void polygon(const float (*points)[2], int count, float pixel, const float color[4])
{
  float center[2] = {};
  for (int i = 0; i < count; i++) {
    center[0] += points[i][0] / count;
    center[1] += points[i][1] / count;
  }
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint col = GPU_vertformat_attr_add(format, "color", gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);
  immBegin(GPU_PRIM_TRIS, count * 9);
  auto vertex = [&](float x, float y, float alpha) {
    immAttr4f(col, color[0], color[1], color[2], alpha);
    immVertex2f(pos, x, y);
  };
  for (int i = 0; i < count; i++) {
    const float *a = points[i], *b = points[(i + 1) % count];
    float outer[2][2];
    for (int k = 0; k < 2; k++) {
      const float *v = k == 0 ? a : b;
      const float dx = v[0] - center[0], dy = v[1] - center[1];
      const float factor = pixel / std::max(0.001f, std::sqrt(dx * dx + dy * dy));
      outer[k][0] = v[0] + dx * factor;
      outer[k][1] = v[1] + dy * factor;
    }
    vertex(center[0], center[1], color[3]);
    vertex(a[0], a[1], color[3]);
    vertex(b[0], b[1], color[3]);
    vertex(a[0], a[1], color[3]);
    vertex(outer[0][0], outer[0][1], 0.0f);
    vertex(outer[1][0], outer[1][1], 0.0f);
    vertex(a[0], a[1], color[3]);
    vertex(outer[1][0], outer[1][1], 0.0f);
    vertex(b[0], b[1], color[3]);
  }
  immEnd();
  immUnbindProgram();
}

void ellipse(float x, float y, float rx, float ry, float pixel, const float color[4])
{
  constexpr int count = 40;
  float points[count][2];
  for (int i = 0; i < count; i++) {
    const float angle = float(i) * 6.283185307f / count;
    points[i][0] = x + rx * std::cos(angle);
    points[i][1] = y + ry * std::sin(angle);
  }
  polygon(points, count, pixel, color);
}

/** Rounded triangular ears, with the same coverage fringe as the face. */
void ear(float side, float height, float twitch, float pixel, const float color[4])
{
  const float corners[3][2] = {
      {side * 0.305f, 0.055f},
      {side * (0.285f + twitch), 0.375f * height},
      {side * 0.060f, 0.210f},
  };
  constexpr int steps = 8;
  constexpr int count = steps * 3;
  float points[count][2];
  for (int i = 0; i < 3; i++) {
    for (int j = 0; j < steps; j++) {
      const float t = float(j) / (steps - 1);
      for (int axis = 0; axis < 2; axis++) {
        const float v = corners[i][axis];
        const float a = v + (corners[(i + 2) % 3][axis] - v) * 0.10f;
        const float b = v + (corners[(i + 1) % 3][axis] - v) * 0.10f;
        const float value = (1 - t) * (1 - t) * a + 2 * (1 - t) * t * v + t * t * b;
        points[i * steps + j][axis] = value;
      }
    }
  }
  polygon(points, count, pixel, color);
}

void draw_eyes(const MixieCatPose &pose, const MixieCatStyle &style, float pixel, float alpha)
{
  const float eye[4] = {style.eyes[0], style.eyes[1], style.eyes[2], alpha};
  const float ink[4] = {0.002f, 0.006f, 0.004f, alpha};
  const float shine[4] = {0.94f, 0.98f, 0.95f, alpha};
  for (float side : {-1.0f, 1.0f}) {
    const float x = side * 0.128f + pose.look_x * 0.018f;
    const float openness = pose.openness;
    /* Eyelids compress the entire eye, including its pupil and catchlight.
     * That keeps every detail inside the eye through a blink. */
    GPU_matrix_push();
    GPU_matrix_translate_2f(x, 0.012f + pose.look_y * 0.012f);
    const float lid = 1.0f - 0.10f * std::max(0.0f, side * pose.look_x);
    GPU_matrix_scale_2f(pose.eye_scale, openness * pose.eye_scale * lid);
    ellipse(0.0f, 0.0f, 0.086f, 0.112f, pixel, eye);
    const float rx = 0.037f * pose.pupil_scale;
    const float ry = 0.040f * pose.pupil_scale;
    float px = 0.012f + pose.look_x * 0.042f;
    float py = 0.044f + pose.look_y * 0.050f;
    /* Fit the moving pupil inside the iris even at a diagonal glance. */
    const float mx = std::max(0.005f, 0.086f - rx - pixel);
    const float my = std::max(0.005f, 0.112f - ry - pixel);
    const float distance = std::sqrt((px / mx) * (px / mx) + (py / my) * (py / my));
    const float fit = 0.94f / std::max(0.94f, distance);
    px *= fit;
    py *= fit;
    ellipse(px, py, rx, ry, pixel, ink);
    const float catchlight[4] = {
        shine[0], shine[1], shine[2], shine[3] * mixie_cat_smooth01((openness - 0.12f) / 0.28f)};
    ellipse(px + 0.016f, py + 0.010f, 0.019f, 0.019f, pixel, catchlight);
    GPU_matrix_pop();
  }
}

}  // namespace

void agent_ui_draw_cat(
    const rctf &chip, const double now, const bool working, const int variation, const float alpha)
{
  const float s = std::min(BLI_rctf_size_x(&chip), BLI_rctf_size_y(&chip)) - 2.0f;
  if (s < 6.0f || alpha <= 0.0f) {
    return;
  }
  const MixieCatPose pose = mixie_cat_eval_pose(now, working);
  const MixieCatStyle &style = mixie_cat_style(variation);
  const float ink[4] = {0.002f, 0.006f, 0.004f, std::clamp(alpha, 0.0f, 1.0f)};

  GPU_matrix_push();
  GPU_matrix_translate_2f(BLI_rctf_cent_x(&chip), BLI_rctf_cent_y(&chip) - s * 0.025f);
  GPU_matrix_rotate_2d(style.tilt + pose.tilt);
  GPU_matrix_scale_2f(s * pose.breathe, s * pose.breathe);
  ear(-1.0f, style.ear_left, pose.ear_l * 0.002f, 0.7f / s, ink);
  ear(1.0f, style.ear_right, pose.ear_r * 0.002f, 0.7f / s, ink);
  ellipse(0.0f, -0.025f, 0.326f * style.cheek_width, 0.263f, 0.7f / s, ink);
  draw_eyes(pose, style, 0.7f / s, ink[3]);
  GPU_matrix_pop();
}

void agent_ui_draw_pill_cat(const rctf *chip, const double now, const bool working)
{
  g_last_cat_valid = false;
  if (chip == nullptr || BLI_rctf_size_x(chip) < 8.0f || BLI_rctf_size_y(chip) < 8.0f) {
    return;
  }
  g_last_cat_rect = {int(std::floor(chip->xmin)),
                     int(std::ceil(chip->xmax)),
                     int(std::floor(chip->ymin)),
                     int(std::ceil(chip->ymax))};
  g_last_cat_valid = true;
  agent_ui_draw_cat(*chip, now, working, 0, 1.0f);
}

bool agent_ui_pill_cat_last_rect(rcti *r_rect)
{
  if (!g_last_cat_valid || r_rect == nullptr) {
    return false;
  }
  *r_rect = g_last_cat_rect;
  return true;
}

void agent_ui_pill_cat_clear()
{
  g_last_cat_valid = false;
}

namespace {

void pill_cat_qa_targets(const wmWindow * /*win*/,
                         const ScrArea *area,
                         const ARegion *region,
                         std::vector<MixarQATarget> &r_targets)
{
  if (area == nullptr || region == nullptr) {
    return;
  }
  if (area->spacetype != SPACE_AGENT_BUBBLE || region->regiontype != RGN_TYPE_HEADER) {
    return;
  }
  bool has_body = false;
  for (ARegion &other : area->regionbase) {
    if (ELEM(other.regiontype, RGN_TYPE_WINDOW, RGN_TYPE_TOOLS)) {
      has_body = true;
      break;
    }
  }
  if (has_body) {
    return;
  }

  rcti cat;
  if (!agent_ui_pill_cat_last_rect(&cat)) {
    return;
  }
  rcti mapped = cat;
  mapped.xmin += region->winrct.xmin;
  mapped.xmax += region->winrct.xmin;
  mapped.ymin += region->winrct.ymin;
  mapped.ymax += region->winrct.ymin;
  rcti dummy;
  if (!BLI_rcti_isect(&mapped, &region->winrct, &dummy)) {
    mapped = region->winrct;
  }

  MixarQATarget t;
  t.surface = "pill_cat";
  t.text = "Mixie";
  t.value = "mascot";
  t.rect_win = mapped;
  r_targets.push_back(std::move(t));
}

}  // namespace

void agent_ui_pill_cat_qa_register()
{
  Mixar_qa_register_target_provider(SPACE_AGENT_BUBBLE, pill_cat_qa_targets);
}

}  // namespace blender
