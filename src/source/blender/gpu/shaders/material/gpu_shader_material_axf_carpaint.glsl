/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "gpu_shader_material_axf_carpaint_lib.glsl"
#include "gpu_shader_math_vector_safe_lib.glsl"

/* EEVEE preview of the AxF CarPaint2 BSDF: smooth dielectric coat over a glossy +
 * diffuse base. Cycles evaluates the measured material exactly; see
 * intern/cycles/kernel/closure/bsdf_axf_carpaint.h. */
[[node]]
void node_bsdf_axf_carpaint(float3 flake_uv,
                            float3 coat_uv,
                            float3 N,
                            float3 tangent,
                            float4 tint,
                            float flake_strength,
                            float orange_peel,
                            float coat_reflection,
                            float coat_roughness,
                            float4 diffuse_color,
                            float4 specular_color,
                            float roughness,
                            float coat_ior,
                            float weight,
                            Closure &result)
{
  N = safe_normalize(N);
  float3 V = coordinate_incoming(g_data.P);
  float NV = dot(N, V);

  float coat_reflectance = bsdf_lut(NV, 0.0f, max(coat_ior, 1.0f), false).x;
  ClosureReflection coat_data;
  coat_data.N = N;
  coat_data.roughness = saturate(coat_roughness);
  coat_data.color = float3(1.0f);
  coat_data.weight = weight * coat_reflectance * max(coat_reflection, 0.0f);
  closure_eval(coat_data);

  float base_weight = weight * max(1.0f - coat_reflectance, 0.0f);

  ClosureReflection reflection_data;
  reflection_data.N = N;
  reflection_data.roughness = saturate(roughness);
  reflection_data.color = max(specular_color.rgb * tint.rgb, float3(0.0f)) * base_weight;
  reflection_data.weight = 1.0f;
  closure_eval(reflection_data);

  ClosureDiffuse diffuse_data;
  diffuse_data.N = N;
  diffuse_data.color = max(diffuse_color.rgb * tint.rgb, float3(0.0f)) * base_weight;
  diffuse_data.weight = 1.0f;
  closure_eval(diffuse_data);

  result = Closure(0);
}

/* EEVEE path of an imported AxF car paint: smooth dielectric coat over Lambert + GGX
 * whose colours and roughness follow the view angle (the importer's per-view fit of
 * the exact BRDF, modules/axf/core/eevee_fit.py), plus the measured flakes seen at the
 * mirror configuration. fit_lut is 64 x 2: row 0 = (diffuse albedo, roughness),
 * row 1 = (specular albedo, flake gain), texel k at view angle (k + 0.5) / 64 * pi/2. */
[[node]]
void node_bsdf_axf_carpaint_fit(float3 flake_uv,
                                float3 coat_uv,
                                float3 N,
                                float3 tangent,
                                float4 tint,
                                float flake_strength,
                                float orange_peel,
                                float coat_reflection,
                                float coat_roughness,
                                float4 diffuse_color,
                                float4 specular_color,
                                float roughness,
                                float coat_ior,
                                float weight,
                                sampler2D fit_lut,
                                sampler2D table,
                                sampler2D flakes,
                                float has_flakes,
                                Closure &result)
{
  N = safe_normalize(N);
  float3 V = coordinate_incoming(g_data.P);
  float NV = clamp(dot(N, V), 1e-4f, 1.0f);

  float coat_reflectance = bsdf_lut(NV, 0.0f, max(coat_ior, 1.0f), false).x;
  ClosureReflection coat_data;
  coat_data.N = N;
  coat_data.roughness = saturate(coat_roughness);
  coat_data.color = float3(1.0f);
  coat_data.weight = weight * coat_reflectance * max(coat_reflection, 0.0f);
  closure_eval(coat_data);

  float base_weight = weight * max(1.0f - coat_reflectance, 0.0f);
  float theta_v = acos(NV);
  float u = theta_v * AXF_2_PI;
  float4 fit0 = texture(fit_lut, float2(u, 0.25f));
  float4 fit1 = texture(fit_lut, float2(u, 0.75f));

  float3 spec = fit1.rgb;
  if (has_flakes != 0.0f && flake_strength != 0.0f) {
    AxfParams p = axf_params_load(table);
    /* Mirror configuration under the coat: thetaH = 0, thetaD = refracted view angle. */
    float sin_v = sqrt(max(1.0f - NV * NV, 0.0f));
    float th_d = p.refractive ? asin(clamp(sin_v / p.ior, 0.0f, 1.0f)) : theta_v;
    spec += flake_strength * fit1.a * axf_flakes(table, flakes, p, flake_uv.xy, 0.0f, th_d);
  }

  /* Where EEVEE lights inside the material shader, light the base with the measured BRDF
   * per light (as Cycles does) and the fit from the probes, and emit the result. */
  float3 radiance;
  if (axf_lighting_eval(table,
                        flakes,
                        has_flakes != 0.0f,
                        N,
                        V,
                        flake_uv.xy,
                        flake_strength,
                        fit0.rgb,
                        max(spec, float3(0.0f)),
                        saturate(fit0.a),
                        tint.rgb,
                        base_weight,
                        weight,
                        radiance))
  {
    ClosureEmission emission_data;
    emission_data.emission = radiance;
    emission_data.weight = 1.0f;
    closure_eval(emission_data);
    result = Closure(0);
    return;
  }

  ClosureReflection reflection_data;
  reflection_data.N = N;
  reflection_data.roughness = saturate(fit0.a);
  reflection_data.color = max(spec * tint.rgb, float3(0.0f)) * base_weight;
  reflection_data.weight = 1.0f;
  closure_eval(reflection_data);

  ClosureDiffuse diffuse_data;
  diffuse_data.N = N;
  diffuse_data.color = max(fit0.rgb * tint.rgb, float3(0.0f)) * base_weight;
  diffuse_data.weight = 1.0f;
  closure_eval(diffuse_data);

  result = Closure(0);
}
