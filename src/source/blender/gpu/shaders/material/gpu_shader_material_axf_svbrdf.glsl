/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "gpu_shader_math_vector_safe_lib.glsl"

/* EEVEE preview of the AxF SVBRDF BSDF: diffuse + glossy from the preview inputs. Cycles
 * evaluates the measured material exactly; see
 * intern/cycles/kernel/closure/bsdf_axf_svbrdf.h. */
[[node]]
void node_bsdf_axf_svbrdf(float3 uv,
                          float3 N,
                          float3 tangent,
                          float4 diffuse_tint,
                          float4 specular_tint,
                          float roughness_scale,
                          float normal_strength,
                          float4 diffuse_color,
                          float4 specular_color,
                          float roughness,
                          float weight,
                          Closure &result)
{
  N = safe_normalize(N);

  ClosureReflection reflection_data;
  reflection_data.N = N;
  reflection_data.roughness = saturate(roughness * max(roughness_scale, 0.0f));
  reflection_data.color = max(specular_color.rgb * specular_tint.rgb, float3(0.0f)) * weight;
  reflection_data.weight = 1.0f;
  closure_eval(reflection_data);

  ClosureDiffuse diffuse_data;
  diffuse_data.N = N;
  diffuse_data.color = max(diffuse_color.rgb * diffuse_tint.rgb, float3(0.0f)) * weight;
  diffuse_data.weight = 1.0f;
  closure_eval(diffuse_data);

  result = Closure(0);
}
