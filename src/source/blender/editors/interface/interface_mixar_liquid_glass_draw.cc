/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * One rounded mask for the tint, frost, light and rim on all GPU backends.
 * The material composites in premultiplied alpha and fades as a whole.
 */

#include <algorithm>
#include <cmath>

#include "BLI_rect.h"
#include "BLI_time.h"
#include "DNA_userdef_types.h"
#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_shader.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"
#include "UI_interface_c.hh"
#include "ED_mixar_glass.hh"

#include "gpu_shader_create_info.hh"
#include "interface_mixar_glass_shader.hh"

namespace blender::ui {
namespace {

gpu::Shader *glass_shaders[2] = {};

gpu::Shader *glass_shader_get(const bool backdrop)
{
  gpu::Shader *&shader = glass_shaders[int(backdrop)];
  if (shader != nullptr) {
    return shader;
  }
  using namespace gpu::shader;
  StageInterfaceInfo iface("mixar_glass_iface");
  iface.no_perspective(Type::float2_t, "localPos");
  ShaderCreateInfo info("mixar_glass");
  info.vertex_in(0, Type::float2_t, "pos");
  info.vertex_out(iface);
  info.fragment_out(0, Type::float4_t, "fragColor");
  info.push_constant(Type::float4x4_t, "ModelViewProjectionMatrix");
  info.push_constant(Type::bool_t, "srgbTarget");
  for (const char *name : {"pane", "metrics", "tintTop", "tintBottom", "sheen", "rim"}) {
    info.push_constant(Type::float4_t, name);
  }
  if (backdrop) {
    info.define("GLASS_BACKDROP");
    info.sampler(0, ImageType::Float2D, "image");
    for (const char *name : {"sourceRect", "glaze", "lighting"}) {
      info.push_constant(Type::float4_t, name);
    }
  }
  info.vertex_source_generated = glass_vertex_source;
  info.fragment_source_generated = glass_fragment_source;
  shader = GPU_shader_create_from_info_python(reinterpret_cast<GPUShaderCreateInfo *>(&info));
  return shader;
}

}  // namespace

void mixar_glass_shader_free()
{
  for (gpu::Shader *&shader : glass_shaders) {
    if (shader != nullptr) {
      GPU_shader_free(shader);
      shader = nullptr;
    }
  }
}

void mixar_glass_draw(const rcti &rect,
                      const MixarGlassStyle &style,
                      const MixarGlassBackdrop &backdrop)
{
  const int width = BLI_rcti_size_x(&rect);
  const int height = BLI_rcti_size_y(&rect);
  if (width <= 0 || height <= 0 || !std::isfinite(style.alpha) || style.alpha <= 0.0f) {
    return;
  }
  const MixarGlassTokens t = mixar_glass_tokens(style.role);
  const float alpha = std::clamp(style.alpha, 0.0f, 1.0f);
  const float radius = std::clamp(style.radius >= 0.0f ? style.radius : t.radius,
                                 0.0f,
                                 std::min(width, height) * 0.5f);
  rctf box;
  BLI_rctf_rcti_copy(&box, &rect);
  const GPUBlend blend_prev = GPU_blend_get();
  GPU_matrix_push_projection();
  GPU_matrix_push();

  if (style.draw_shadow && t.shadow[3] > 0.0f) {
    draw_roundbox_corner_set(CNR_ALL);
    draw_dropshadow(&box, radius, t.shadow_width, 1.0f, t.shadow[3] * alpha);
  }

  gpu::Shader *shader = glass_shader_get(backdrop.valid());
  if (shader != nullptr) {
    GPU_blend(GPU_BLEND_ALPHA_PREMULT);
    GPUVertFormat *format = immVertexFormat();
    const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
    immBindShader(shader);
    immUniform4f("pane", box.xmin, box.ymin, box.xmax, box.ymax);
    immUniform4f("metrics", radius, style.draw_rim ? t.rim_width : 0.0f,
                 std::min(t.sheen_height, float(height) * 0.28f), alpha);
    const float floor = backdrop.valid() ? 0.0f : t.fallback_alpha;
    const float top[4] = {t.tint_top[0], t.tint_top[1], t.tint_top[2],
                          style.draw_tint ? std::max(t.tint_top[3], floor) : 0.0f};
    const float bottom[4] = {t.tint_bottom[0], t.tint_bottom[1], t.tint_bottom[2],
                             style.draw_tint ? std::max(t.tint_bottom[3], floor) : 0.0f};
    immUniform4fv("tintTop", top);
    immUniform4fv("tintBottom", bottom);
    immUniform4fv("sheen", t.sheen);
    immUniform4fv("rim", t.rim);
    if (backdrop.valid()) {
      immUniform4f("sourceRect", float(backdrop.rect.xmin), float(backdrop.rect.ymin),
                   float(backdrop.rect.xmax), float(backdrop.rect.ymax));
      immUniform4fv("glaze", t.glaze);
      const float phase = (style.draw_specular && t.specular_period > 0.0f) ?
          float(std::fmod(BLI_time_now_seconds() / double(t.specular_period), 1.0)) : 0.0f;
      immUniform4f("lighting", t.refract[3] * radius * 0.3f,
                   style.draw_specular ? t.specular_alpha : 0.0f,
                   t.specular_width, -t.specular_width + phase * (width + 2 * t.specular_width));
      GPUSamplerState sampler = GPUSamplerState::default_sampler();
      sampler.filtering = GPU_SAMPLER_FILTERING_LINEAR;
      immBindTextureSampler("image", backdrop.texture, sampler);
    }
    /* One pixel outside the bounds lets the shader anti-alias the outer edge. */
    immRectf(pos, box.xmin - 1.0f, box.ymin - 1.0f, box.xmax + 1.0f, box.ymax + 1.0f);
    immUnbindProgram();
  }
  else {
    /* A shader failure must leave readable, shaped chrome. */
    float fallback[4] = {t.tint_bottom[0], t.tint_bottom[1], t.tint_bottom[2], alpha};
    draw_roundbox_corner_set(CNR_ALL);
    draw_roundbox_4fv(&box, true, radius, fallback);
  }
  GPU_matrix_pop();
  GPU_matrix_pop_projection();
  GPU_blend(blend_prev);
}

}  // namespace blender::ui
