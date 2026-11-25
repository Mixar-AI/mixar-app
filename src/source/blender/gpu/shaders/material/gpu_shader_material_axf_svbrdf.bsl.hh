/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include "gpu_shader_material_interface.bsl.hh"
#include "gpu_shader_math_vector_safe.bsl.hh"

/* EEVEE preview of the AxF SVBRDF BSDF: diffuse + glossy from the preview inputs. Cycles
 * evaluates the measured material exactly; see
 * intern/cycles/kernel/closure/bsdf_axf_svbrdf.h. */
[[node]]
void node_bsdf_axf_svbrdf(float3 /*uv*/,
                          float3 N,
                          float3 /*tangent*/,
                          float4 diffuse_tint,
                          float4 specular_tint,
                          float roughness_scale,
                          float /*normal_strength*/,
                          float4 diffuse_color,
                          float4 specular_color,
                          float roughness,
                          float weight,
                          KernelGlobals &kg,
                          ShadingData &sd,
                          Closure &result)
{
  N = safe_normalize(N);

  ClosureReflection reflection_data;
  reflection_data.N = N;
  reflection_data.roughness = saturate(roughness * max(roughness_scale, 0.0f));
  reflection_data.color = max(specular_color.rgb * specular_tint.rgb, float3(0.0f)) * weight;
  closure_eval(kg, sd, reflection_data);

  ClosureDiffuse diffuse_data;
  diffuse_data.N = N;
  diffuse_data.color = max(diffuse_color.rgb * diffuse_tint.rgb, float3(0.0f)) * weight;
  closure_eval(kg, sd, diffuse_data);

  /* EEVEE accumulates the evaluated closures itself (as the Principled BSDF). */
  result = CLOSURE_DEFAULT;
}
