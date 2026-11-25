/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/**
 * Mixar: lighting of the AxF car paint node in the pipelines that light inside the
 * material shader (`use_forward_lighting`: forward, and the deferred "hybrid" pass EEVEE
 * uses for materials that need Shader to RGB, which the node requests).
 *
 * Direct light: every light that reaches the pixel (same culling, attenuation, light
 * linking and shadows as EEVEE's own light loop) is evaluated with the measured CarPaint2
 * BRDF itself, the same maths as Cycles' closure (gpu_shader_material_axf_carpaint_lib),
 * at the direction to the light. The light's size enters as its solid angle (EEVEE's LTC
 * integral of a cosine lobe around the light direction), so small and distant lights are
 * exact and large area lights are approximated by their centre direction.
 *
 * Indirect light (world, sphere and volume probes): the per-view fit (diffuse albedo,
 * GGX specular albedo + roughness) through EEVEE's probe evaluation, as the fitted
 * closures would receive it.
 *
 * The result is returned as radiance and emitted by the node; the clear coat mirror stays
 * an ordinary reflection closure. eevee_nodetree_lib.bsl.hh implements the material
 * interface's axf_lighting_eval (gpu_shader_material_interface.bsl.hh) on top of this.
 */

#pragma once

#include "eevee_colorspace_lib.bsl.hh"
#include "eevee_light_data.bsl.hh"
#include "eevee_light_eval.bsl.hh"
#include "eevee_light_iter.bsl.hh"
#include "eevee_lightprobe.bsl.hh"
#include "eevee_uniform.bsl.hh"
#include "gpu_shader_codegen_lib.glsl"
#include "gpu_shader_material_axf_carpaint_lib.bsl.hh"
#include "gpu_shader_math_spherical_harmonics.bsl.hh"

namespace eevee::axf {

/* What the light loop needs about the shaded point. */
struct Receiver {
  float3 P;
  float3 Ng;
  float2 texel;
  uchar light_set;
  float terminator_normal_offset;
  float terminator_geometry_offset;
  int ray_count;
  int ray_step_count;
};

/* Samples per side of the grid an area light is integrated over, chosen by how large the
 * light looks from the shaded point (its half extent over its distance, in radians): below
 * AXF_AREA_SMALL the centre direction is exact enough (one evaluation), below
 * AXF_AREA_MEDIUM a 2 x 2 grid, otherwise 4 x 4 (16 evaluations). */
#define AXF_AREA_GRID_MAX 4
#define AXF_AREA_SMALL 0.03f
#define AXF_AREA_MEDIUM 0.15f

/* Shirley-Chiu concentric map of [-1, 1]^2 onto the unit disk (area preserving). */
float2 area_square_to_disk(float2 s)
{
  if (s.x == 0.0f && s.y == 0.0f) {
    return float2(0.0f);
  }
  float r, phi;
  if (abs(s.x) > abs(s.y)) {
    r = s.x;
    phi = (M_PI / 4.0f) * (s.y / s.x);
  }
  else {
    r = s.y;
    phi = (M_PI / 2.0f) - (M_PI / 4.0f) * (s.x / s.y);
  }
  return r * float2(cos(phi), sin(phi));
}

/* Radiance leaving the surface toward V from one light (Cycles: eval_cos x light). */
float3 light_contribution(LightEvalData &srt,
                          LightData light,
                          const bool is_directional,
                          sampler2D table,
                          sampler2D flakes,
                          bool has_flakes,
                          AxfParams p,
                          Receiver rcv,
                          float3 N,
                          float3 V,
                          float2 flake_uv,
                          float flake_strength)
{
  if (!light::light_linking_affects_receiver(light.light_set_membership, rcv.light_set)) {
    return float3(0.0f);
  }
  LightVector lv = LightVector::get(light, is_directional, rcv.P);
  /* Area lights are integrated over their surface below, sample by sample, so each sample
   * meets the surface's horizon on its own; the whole-light horizon fade would cut the
   * light off as soon as its centre went below the horizon (a hard terminator). */
  const float area_extent = (!is_directional && is_area_light(light.type)) ?
                                max(light.area.size.x, light.area.size.y) / max(lv.dist, 1e-6f) :
                                0.0f;
  const bool integrate_area = area_extent >= AXF_AREA_SMALL;
  float attenuation = light_attenuation_surface(light, is_directional, lv);
  if (!integrate_area) {
    attenuation *= light_attenuation_facing(light, lv.L, lv.dist, N, false);
  }
  attenuation *= light::power_get(light, LIGHT_DIFFUSE);
  if (attenuation < LIGHT_ATTENUATION_THRESHOLD) {
    return float3(0.0f);
  }

  float shadow = 1.0f;
  if (light.tilemap_index != LIGHT_NO_SHADOW) {
    shadow = shadow_eval(srt.shadow_data,
                         light,
                         is_directional,
                         false,
                         false,
                         rcv.texel,
                         Thickness::zero(),
                         rcv.P,
                         rcv.Ng,
                         N,
                         rcv.terminator_normal_offset,
                         rcv.terminator_geometry_offset,
                         1.0f,
                         rcv.ray_count,
                         rcv.ray_step_count);
  }
  if (shadow * attenuation < 1e-30f) {
    return float3(0.0f);
  }

  if (integrate_area) {
    /* Rectangle / ellipse: Lo = Le * sum_k eval_cos(w_k) dOmega_k over a stratified grid on
     * the light's surface (Cycles integrates the same BRDF over the light by sampling).
     * dOmega_k = A_k |cos(light normal, w_k)| / d_k^2. */
    const float3 Px = light.x_axis();
    const float3 Py = light.y_axis();
    const float3 Nl = cross(Px, Py);
    const float2 size = light.area.size; /* Half extents. */
    const bool ellipse = light.type == LIGHT_ELLIPSE;
    const int grid = area_extent < AXF_AREA_MEDIUM ? 2 : AXF_AREA_GRID_MAX;
    const float cell_area = (ellipse ? M_PI : 4.0f) * size.x * size.y / float(grid * grid);
    const float3 center = light.position();
    float3 sum = float3(0.0f);
    for (int j = 0; j < grid; j++) {
      for (int i = 0; i < grid; i++) {
        float2 s = (float2(i, j) + 0.5f) * (2.0f / float(grid)) - 1.0f;
        if (ellipse) {
          s = area_square_to_disk(s);
        }
        const float3 to_light = center + Px * (s.x * size.x) + Py * (s.y * size.y) - rcv.P;
        const float d2 = max(dot(to_light, to_light), 1e-12f);
        const float3 L = to_light * inversesqrt(d2);
        const float d_omega = cell_area * abs(dot(L, Nl)) / d2;
        sum += axf_eval_cos(table, flakes, has_flakes, p, N, N, flake_uv, flake_strength, V, L) *
               d_omega;
      }
    }
    return sum * light.color * (attenuation * shadow);
  }

  /* Irradiance on a plane facing the light: the cosine lobe integrated over the light's
   * shape about the light direction is (projected) solid angle / pi. */
  const UtilityTexture &util = srt.utility_tx;
  LightShape shape = LightShape::get(light, lv);
  float solid_angle = M_PI *
                      ltc::evaluate(util.utility_tx, light, shape, lv, LTCData::identity(lv.L, V));
  float3 irradiance = light.color * (solid_angle * attenuation * shadow);
  return axf_eval_cos(table, flakes, has_flakes, p, N, N, flake_uv, flake_strength, V, lv.L) *
         irradiance;
}

/* vPz: linear view depth of P (light culling z-bin). V points from the surface to the eye.
 * Returns the radiance toward V. */
float3 lighting_eval(LightEvalIterator &lights,
                     const Uniform &uni,
                     const LightprobeRenderData &lightprobes,
                     Receiver rcv,
                     float vPz,
                     sampler2D table,
                     sampler2D flakes,
                     bool has_flakes,
                     float3 N,
                     float3 V,
                     float2 flake_uv,
                     float flake_strength,
                     float3 diffuse_albedo,
                     float3 specular_albedo,
                     float roughness,
                     float3 tint,
                     float base_weight,
                     float weight)
{
  LightEvalData &srt = lights.inner;
  const LightRenderData &light_data = lights.light_data;
  AxfParams p = axf_params_load(table);

  float3 direct = float3(0.0f);
  {
    /* EEVEE's light loop (light::foreach_visible), inlined so the BRDF's images stay in
     * scope. */
    const LightCullingData &culling = light_data.light_cull_buf;
    for (uint index = culling.local_lights_len; index < culling.items_count; index++) {
      LightData light = light_data.light_buf[index];
      direct += light_contribution(
          srt, light, true, table, flakes, has_flakes, p, rcv, N, V, flake_uv, flake_strength);
    }
    uint2 tile_co = uint2(rcv.texel / culling.tile_size);
    uint tile_word_offset = (tile_co.x + tile_co.y * culling.tile_x_len) * culling.tile_word_len;
    int zbin_index = light::culling_z_to_zbin(culling.zbin_scale, culling.zbin_bias, vPz);
    zbin_index = clamp(zbin_index, 0, CULLING_ZBIN_COUNT - 1);
    uint zbin_data = light_data.light_zbin_buf[zbin_index];
    uint min_index = zbin_data & 0xFFFFu;
    uint max_index = zbin_data >> 16u;
    uint word_min = min_index >> 5u;
    uint word_max = max_index >> 5u;
    for (uint word_idx = word_min; word_idx <= word_max; word_idx++) {
      uint word = light_data.light_tile_buf[tile_word_offset + word_idx];
      word &= light::zbin_mask(word_idx, min_index, max_index);
      int bit_index;
      while ((bit_index = findLSB(word)) != -1) {
        word &= ~1u << uint(bit_index);
        uint index = word_idx * 32u + uint(bit_index);
        LightData light = light_data.light_buf[index];
        direct += light_contribution(
            srt, light, false, table, flakes, has_flakes, p, rcv, N, V, flake_uv, flake_strength);
      }
    }
  }
  direct *= tint * weight;

  /* Indirect light on the per-view fit, as EEVEE lights its own closures from probes. */
  LightProbeSample samp = lightprobes.load(rcv.texel, rcv.P, rcv.Ng, V);
  samp.volume_irradiance = spherical_harmonics::clamp_energy(
      samp.volume_irradiance, uni.uniform_buf.clamp.surface_indirect);
  ClosureUndetermined cl_diffuse = closure_new(CLOSURE_BSDF_DIFFUSE_ID);
  cl_diffuse.N = N;
  cl_diffuse.color = float3(1.0f);
  ClosureUndetermined cl_reflect = closure_new(CLOSURE_BSDF_MICROFACET_GGX_REFLECTION_ID);
  cl_reflect.N = N;
  cl_reflect.color = float3(1.0f);
  cl_reflect.data = float4(roughness, 0.0f, 0.0f, 0.0f);
  float3 indirect =
      diffuse_albedo * lightprobes.eval(samp, cl_diffuse, rcv.P, V, Thickness::zero()) +
      specular_albedo * lightprobes.eval(samp, cl_reflect, rcv.P, V, Thickness::zero());
  indirect *= max(tint, float3(0.0f)) * base_weight;

  direct = colorspace::brightness_clamp_max(direct, uni.uniform_buf.clamp.surface_direct);
  indirect = colorspace::brightness_clamp_max(indirect, uni.uniform_buf.clamp.surface_indirect);
  /* No clamp at zero: a paint outside Rec.709 has negative channels, and Cycles keeps them
   * (clamping brightened ext_blue by up to 9 %). */
  return direct * uni.uniform_buf.clamp.direct_scale +
         indirect * uni.uniform_buf.clamp.indirect_scale;
}

}  // namespace eevee::axf
