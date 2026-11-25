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
  float attenuation = light_attenuation_surface(light, is_directional, lv);
  attenuation *= light_attenuation_facing(light, lv.L, lv.dist, N, false);
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
  return max(direct, float3(0.0f)) * uni.uniform_buf.clamp.direct_scale +
         indirect * uni.uniform_buf.clamp.indirect_scale;
}

}  // namespace eevee::axf
