/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "cinema_label.hh"

#include "../interface_mixar_card_paint.hh"
#include "BKE_appdir.hh"
#include "BLI_fileops.h"
#include "BLI_utildefines.h"
#include "BLI_path_utils.hh"
#include "BLF_api.hh"
#include "DNA_space_types.h"
#include "UI_resources.hh"
#include "UI_interface_icons.hh"
#include "UI_mixar_theme.hh"
#include "GPU_immediate.hh"
#include "GPU_texture.hh"
#include "GPU_state.hh"

#include <algorithm>
#include <cstring>
#include <cmath>
#include <vector>

namespace blender::ui {

static int cinema_font()
{
  const auto dir = BKE_appdir_folder_id(BLENDER_DATAFILES, BLF_DATAFILES_FONTS_DIR);
  if (!dir) {
    return -1;
  }
  char path[FILE_MAX];
  BLI_path_join(path, sizeof(path), dir->c_str(), "ClashGrotesk-Regular.otf");
  /* BLF owns the cache and clears it when UI fonts reload. Resolve by path so
   * no stale integer font ID survives that reload; keep one cached reference. */
  const bool cached = BLF_is_loaded(path);
  if (!cached && !BLI_is_file(path)) {
    return -1;
  }
  const int font = BLF_load(path);
  if (cached && font >= 0) {
    BLF_unload_id(font);
  }
  return font;
}

void mixar_cinema_background(const rctf &bounds,
                             const float radius,
                             const float selected,
                             const float emphasis)
{
  MIXAR_THEME_LOAD(left, CinemaBrandTop);
  MIXAR_THEME_LOAD(right, CinemaBrandBottom);
  MIXAR_THEME_LOAD(active_left, CinemaPillOnA);
  MIXAR_THEME_LOAD(active_right, CinemaPillOnB);
  for (int i = 0; i < 4; i++) {
    left[i] += (active_left[i] - left[i]) * selected * 0.65f;
    right[i] += (active_right[i] - right[i]) * selected * 0.85f;
  }
  for (int i = 0; i < 3; i++) {
    left[i] = std::min(1.0f, left[i] + 0.025f * emphasis);
    right[i] = std::min(1.0f, right[i] + 0.025f * emphasis);
  }
  draw_roundbox_corner_set(CNR_ALL);
  /* The widget shader mixes inner2 -> inner1 along X when shade_dir is zero. */
  draw_roundbox_4fv_ex(&bounds, right, left, 0.0f, nullptr, 0.0f, radius);
}

/** Rasterize `text` once at the font's current size, tint the coverage from
 * `left` to `right` across its ink width and blit it with its ink box centred
 * on (`cx` + half its width, `cy`). Preserves kerning, UTF-8 and antialiasing
 * without redrawing the string for every column. Returns the ink width. */
static int draw_tinted_text(const int font,
                            const char *text,
                            const float x,
                            const float cy,
                            const float left[4],
                            const float right[4],
                            const float alpha)
{
  const size_t length = strlen(text);
  rcti ink;
  BLF_boundbox(font, text, length, &ink);
  const int w = BLI_rcti_size_x(&ink) + 2;
  const int h = BLI_rcti_size_y(&ink) + 2;
  if (w <= 2 || h <= 2) {
    return 0;
  }
  std::vector<unsigned char> pixels(size_t(w) * h * 4, 0);
  BLFBufferState *buffer_state = BLF_buffer_state_push(font);
  const float white[4] = {1, 1, 1, 1};
  BLF_buffer_col(font, white);
  BLF_buffer(font, nullptr, pixels.data(), w, h, 4, nullptr);
  BLF_position(font, 1 - ink.xmin, 1 - ink.ymin, 0);
  BLF_draw_buffer(font, text, length);
  BLF_buffer_state_pop(buffer_state);

  for (int y = 0; y < h; y++) {
    for (int px = 0; px < w; px++) {
      unsigned char *pixel = &pixels[(size_t(y) * w + px) * 4];
      const float t = std::clamp(float(px - 1) / std::max(1, w - 3), 0.0f, 1.0f);
      for (int i = 0; i < 3; i++) {
        pixel[i] = uchar(std::lround(255.0f * (left[i] + (right[i] - left[i]) * t)));
      }
      pixel[3] = uchar(std::lround(pixel[3] * (left[3] + (right[3] - left[3]) * t) * alpha));
    }
  }
  gpu::Texture *texture = GPU_texture_create_2d(
      "cinema_label", w, h, 1, gpu::TextureFormat::UNORM_8_8_8_8,
      GPU_TEXTURE_USAGE_GENERAL, nullptr);
  if (!texture) {
    return w - 2;
  }
  GPU_texture_update(texture, GPU_DATA_UBYTE, pixels.data());
  GPU_texture_filter_mode(texture, false);
  GPU_texture_bind(texture, 0);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint uv = GPU_vertformat_attr_add(format, "texCoord", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_IMAGE_COLOR);
  immUniformColor4f(1, 1, 1, 1);
  /* Ink starts one texel in; land it exactly on `x`. */
  const float qx = std::round(x) - 1.0f;
  const float qy = std::round(cy - h * 0.5f);
  immBegin(GPU_PRIM_TRI_FAN, 4);
  immAttr2f(uv, 0, 0); immVertex2f(pos, qx, qy);
  immAttr2f(uv, 1, 0); immVertex2f(pos, qx + w, qy);
  immAttr2f(uv, 1, 1); immVertex2f(pos, qx + w, qy + h);
  immAttr2f(uv, 0, 1); immVertex2f(pos, qx, qy + h);
  immEnd();
  immUnbindProgram();
  GPU_texture_unbind(texture);
  GPU_texture_free(texture);
  return w - 2;
}

void mixar_cinema_label(const rcti &bounds,
                        const char *label,
                        const float selected,
                        const bool disabled,
                        const int icon_id)
{
  if (!label || !label[0]) {
    return;
  }
  const uiFontStyle style = mixar_card_font(1.47f, 0);
  const int custom_font = cinema_font();
  const int font = custom_font >= 0 ? custom_font : BLF_default();
  if (font < 0) {
    return;
  }
  const float u = UI_SCALE_FAC;
  const size_t length = strlen(label);
  /* Same content geometry as the flat design: 16px icon, 4px icon gap, 3px
   * version gap, 7px side padding; the V1 marker is 60% of the label and
   * raised 4px. Everything scales together when the bounds are tight. */
  const float icon_size = 16.0f * u;
  const bool has_icon = !ELEM(icon_id, ICON_NONE, ICON_BLANK1);
  const float leading = has_icon ? icon_size + 4.0f * u : 0.0f;
  const float gap = 3.0f * u;
  const char *version = "V1";
  float size = style.points * u;
  float version_size = size * 0.60f;
  BLF_size(font, size);
  float text_width = BLF_width(font, label, length);
  BLF_size(font, version_size);
  float version_width = BLF_width(font, version, strlen(version));
  const float available = std::max(1.0f, BLI_rcti_size_x(&bounds) - 14.0f * u - leading - gap);
  if (text_width + version_width > available) {
    const float fit = available / (text_width + version_width);
    size *= fit;
    version_size *= fit;
    BLF_size(font, size);
    text_width = BLF_width(font, label, length);
    BLF_size(font, version_size);
    version_width = BLF_width(font, version, strlen(version));
  }
  const float left = (bounds.xmin + bounds.xmax - leading - text_width - gap - version_width) *
                     0.5f;
  const float cy = BLI_rcti_cent_y_fl(&bounds);
  const float alpha = disabled ? 0.5f : 1.0f;

  MIXAR_THEME_LOAD(start, CinemaPillLabel);
  MIXAR_THEME_LOAD(end, CinemaPillLabelOn);
  for (int i = 0; i < 4; i++) {
    start[i] += (end[i] - start[i]) * selected * 0.45f;
  }

  const GPUBlend old_blend = GPU_blend_get();
  int old_scissor[4];
  GPU_scissor_get(old_scissor);
  const int x0 = std::max(bounds.xmin, old_scissor[0]);
  const int y0 = std::max(bounds.ymin, old_scissor[1]);
  GPU_scissor(x0, y0,
              std::max(0, std::min(bounds.xmax, old_scissor[0] + old_scissor[2]) - x0),
              std::max(0, std::min(bounds.ymax, old_scissor[1] + old_scissor[3]) - y0));
  GPU_blend(GPU_BLEND_ALPHA);

  if (has_icon) {
    /* The icon sits at the ramp's start; the marker takes its end. */
    uchar icon_color[4];
    for (int i = 0; i < 3; i++) {
      icon_color[i] = uchar(std::lround(255.0f * std::clamp(start[i], 0.0f, 1.0f)));
    }
    icon_color[3] = uchar(std::lround(255.0f * std::clamp(start[3], 0.0f, 1.0f) * alpha));
    icon_draw_ex(std::round(left),
                 std::round(cy - icon_size * 0.5f),
                 icon_id, 1.0f, 1.0f, 0.0f, icon_color, false, nullptr, false,
                 icon_size / 16.0f);
  }
  BLF_size(font, size);
  draw_tinted_text(font, label, left + leading, cy, start, end, alpha);
  BLF_size(font, version_size);
  draw_tinted_text(font, version, left + leading + text_width + gap, cy + 4.0f * u, end, end, alpha);

  GPU_blend(old_blend);
  GPU_scissor(old_scissor[0], old_scissor[1], old_scissor[2], old_scissor[3]);
}

}  // namespace blender::ui
