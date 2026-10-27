/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "gpu_shader_math_vector_safe_lib.glsl"

/* EEVEE preview of the AxF CarPaint2 BSDF: smooth dielectric coat over a glossy +
 * diffuse base. Cycles evaluates the measured material exactly; see
 * intern/cycles/kernel/closure/bsdf_axf_carpaint.h. */
[[node]]
void node_bsdf_axf_carpaint(float3 flake_uv,
                            float3 N,
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
  coat_data.roughness = 0.0f;
  coat_data.color = float3(1.0f);
  coat_data.weight = weight * coat_reflectance;
  closure_eval(coat_data);

  float base_weight = weight * max(1.0f - coat_reflectance, 0.0f);

  ClosureReflection reflection_data;
  reflection_data.N = N;
  reflection_data.roughness = saturate(roughness);
  reflection_data.color = max(specular_color.rgb, float3(0.0f)) * base_weight;
  reflection_data.weight = 1.0f;
  closure_eval(reflection_data);

  ClosureDiffuse diffuse_data;
  diffuse_data.N = N;
  diffuse_data.color = max(diffuse_color.rgb, float3(0.0f)) * base_weight;
  diffuse_data.weight = 1.0f;
  closure_eval(diffuse_data);

  result = Closure(0);
}
