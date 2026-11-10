/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/**
 * Mixar: lighting of the AxF car paint node in the pipelines that light inside the
 * material shader (forward, and the deferred "hybrid" pass EEVEE uses for materials that
 * need it).
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
 * an ordinary reflection closure.
 */

#pragma once

#ifdef MAT_AXF_LIGHTING

#  include "draw_view.bsl.hh"
#  include "eevee_colorspace_lib.bsl.hh"
#  include "eevee_light_eval.bsl.hh"
#  include "eevee_lightprobe.bsl.hh"
#  include "gpu_shader_material_axf_carpaint_lib.glsl"

namespace eevee::axf {

/* Radiance leaving the surface toward V from one light (Cycles: eval_cos x light). */
float3 light_contribution([[resource_table]] LightEvalData &srt,
                          LightData light,
                          const bool is_directional,
                          sampler2D table,
                          sampler2D flakes,
                          bool has_flakes,
                          AxfParams p,
                          float3 P,
                          float3 Ng,
                          float3 N,
                          float3 V,
                          float2 flake_uv,
                          float flake_strength,
                          float2 texel,
                          ObjectInfos object_infos)
{
  [[resource_table]] ShadowRenderData &srd = srt.shadow_data;
  [[resource_table]] Uniform &uni = srd.uniforms;
  [[resource_table]] const UtilityTexture &util = srt.utility_tx;

  if (!light::light_linking_affects_receiver(light.light_set_membership,
                                             uchar(receiver_light_set_get(object_infos))))
  {
    return float3(0.0f);
  }
  LightVector lv = light_vector_get(light, is_directional, P);
  float attenuation = light_attenuation_surface(light, is_directional, lv);
  attenuation *= light_attenuation_facing(light, lv.L, lv.dist, N, false);
  attenuation *= light.power[LIGHT_DIFFUSE];
  if (attenuation < LIGHT_ATTENUATION_THRESHOLD) {
    return float3(0.0f);
  }

  float shadow = 1.0f;
  if (light.tilemap_index != LIGHT_NO_SHADOW) {
    shadow = shadow_eval(srd,
                         light,
                         is_directional,
                         false,
                         false,
                         texel,
                         Thickness::zero(),
                         P,
                         Ng,
                         N,
                         object_infos.shadow_terminator_normal_offset,
                         object_infos.shadow_terminator_geometry_offset,
                         uni.uniform_buf.shadow.ray_count,
                         uni.uniform_buf.shadow.step_count);
  }
  if (shadow * attenuation < 1e-30f) {
    return float3(0.0f);
  }

  /* Irradiance on a plane facing the light: the cosine lobe integrated over the light's
   * shape about the light direction is (projected) solid angle / pi. */
  LightVertices vertices = light_shape_corners(light, lv);
  float solid_angle = M_PI * light_ltc(util.utility_tx,
                                       light,
                                       lv.L,
                                       V,
                                       lv,
                                       eevee::lut::ltc::identity(),
                                       vertices);
  float3 irradiance = light.color * (solid_angle * attenuation * shadow);
  return axf_eval_cos(table, flakes, has_flakes, p, N, N, flake_uv, flake_strength, V, lv.L) *
         irradiance;
}

bool lighting_eval(sampler2D table,
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
                       float weight,
                       float3 &radiance)
{
  [[resource_table]] const draw::View &views = resource_table_get(draw::View);
  [[resource_table]] LightEvalIterator &lights = resource_table_get(eevee::LightEvalIterator);
  [[resource_table]] const Uniform &uni = resource_table_get(eevee::Uniform);
  /* clang-format off */ /* Multi-line macro breaks error line counting. */
  [[resource_table]] LightprobeRenderData &lightprobes = resource_table_get(eevee::LightprobeRenderData);
  /* clang-format on */
  [[resource_table]] draw::Infos &infos = resource_table_get(draw::Infos);
  [[resource_table]] LightEvalData &srt = lights.inner;
  [[resource_table]] const LightRenderData &light_data = lights.light_data;

  auto &interp_flat = interface_get(eevee_geom_iface_info, interp_flat);
  draw::ID id{interp_flat.resource_id_raw};
  ObjectInfos object_infos = infos.get(id.resource_id<1>());

  const ViewMatrices view = views.get(0);
  const float2 texel = gl_FragCoord.xy;
  const float3 P = g_data.P;
  const float3 Ng = g_data.Ng;
  const float vPz = dot(view.forward(), P) - dot(view.forward(), view.position());
  /* The node's V points from the surface to the eye. */
  AxfParams p = axf_params_load(table);

  float3 direct = float3(0.0f);
  {
    /* EEVEE's light loop (light::foreach_visible), inlined so the BRDF's images stay in
     * scope. */
    const LightCullingData &culling = light_data.light_cull_buf;
    for (uint index = culling.local_lights_len; index < culling.items_count; index++) {
      LightData light = light_data.light_buf[index];
      direct += light_contribution(srt,
                                        light,
                                        true,
                                        table,
                                        flakes,
                                        has_flakes,
                                        p,
                                        P,
                                        Ng,
                                        N,
                                        V,
                                        flake_uv,
                                        flake_strength,
                                        texel,
                                        object_infos);
    }
    uint2 tile_co = uint2(texel / culling.tile_size);
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
        direct += light_contribution(srt,
                                          light,
                                          false,
                                          table,
                                          flakes,
                                          has_flakes,
                                          p,
                                          P,
                                          Ng,
                                          N,
                                          V,
                                          flake_uv,
                                          flake_strength,
                                          texel,
                                          object_infos);
      }
    }
  }
  direct *= tint * weight;

  /* Indirect light on the per-view fit, as EEVEE lights its own closures from probes. */
  LightProbeSample samp = lightprobes.load(texel, P, Ng, V);
  samp.volume_irradiance = spherical_harmonics::clamp_energy(
      samp.volume_irradiance, uni.uniform_buf.clamp.surface_indirect);
  ClosureUndetermined cl_diffuse = closure_new(CLOSURE_BSDF_DIFFUSE_ID);
  cl_diffuse.N = N;
  cl_diffuse.color = float3(1.0f);
  cl_diffuse.weight = 1.0f;
  ClosureUndetermined cl_reflect = closure_new(CLOSURE_BSDF_MICROFACET_GGX_REFLECTION_ID);
  cl_reflect.N = N;
  cl_reflect.color = float3(1.0f);
  cl_reflect.weight = 1.0f;
  cl_reflect.data = float4(roughness, 0.0f, 0.0f, 0.0f);
  float3 indirect =
      diffuse_albedo * lightprobes.eval(samp, cl_diffuse, P, V, Thickness::zero()) +
      specular_albedo * lightprobes.eval(samp, cl_reflect, P, V, Thickness::zero());
  indirect *= max(tint, float3(0.0f)) * base_weight;

  direct = colorspace::brightness_clamp_max(direct, uni.uniform_buf.clamp.surface_direct);
  indirect = colorspace::brightness_clamp_max(indirect, uni.uniform_buf.clamp.surface_indirect);
  radiance = max(direct, float3(0.0f)) * uni.uniform_buf.clamp.direct_scale +
             indirect * uni.uniform_buf.clamp.indirect_scale;
  return true;
}

}  // namespace eevee::axf

bool axf_lighting_eval(sampler2D table,
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
                       float weight,
                       float3 &radiance)
{
  return eevee::axf::lighting_eval(table,
                                   flakes,
                                   has_flakes,
                                   N,
                                   V,
                                   flake_uv,
                                   flake_strength,
                                   diffuse_albedo,
                                   specular_albedo,
                                   roughness,
                                   tint,
                                   base_weight,
                                   weight,
                                   radiance);
}

#endif /* MAT_AXF_LIGHTING */
