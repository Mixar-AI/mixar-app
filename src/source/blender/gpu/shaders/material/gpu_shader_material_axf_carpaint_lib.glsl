/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/* AxF CarPaint2 data access and BRDF for EEVEE: the same image layout and the same maths
 * as Cycles' intern/cycles/kernel/closure/bsdf_axf_carpaint.h (exact texel addressing,
 * float math), so EEVEE and Cycles read one set of images written by the Mixar importer.
 *
 * table image: parameter texel stream from texel 0 (row-major across the image width),
 * then the colour table in linear Rec.709 from row table_row0. flakes image: flake BTF
 * patches tiled in an atlas, in the stored colour space (the stream carries the matrix). */

#pragma once

#include "gpu_shader_math_constants_lib.glsl"

#define AXF_PARAM_HEADER 7
#define AXF_2_PI 0.636619772367581343076f /* 2/pi */

struct AxfParams {
  float kd;
  float ior;
  bool refractive;
  int n_lobes;
  float3 c;
  float3 m;
  float3 f0;
  int num_theta_f;
  int lut_rows;
  int lut_cols;
  int atlas_cols;
  int patch_w;
  int patch_h;
  int table_w;
  int table_h;
  int table_row0;
  int atlas_w;
  int atlas_h;
  float table_offset;
  float3 flake_m0;
  float3 flake_m1;
  float3 flake_m2;
};

float4 axf_param(sampler2D table, int index)
{
  int w = textureSize(table, 0).x;
  return texelFetch(table, int2(index % w, index / w), 0);
}

AxfParams axf_params_load(sampler2D table)
{
  AxfParams p;
  float4 h0 = axf_param(table, 0);
  float4 h1 = axf_param(table, 1);
  float4 h2 = axf_param(table, 2);
  float4 h3 = axf_param(table, 3);
  p.kd = h0.y;
  p.ior = h0.z;
  p.refractive = h0.w != 0.0f;
  p.n_lobes = min(int(h1.x), 3);
  p.num_theta_f = int(h1.y);
  p.lut_rows = int(h1.z);
  p.lut_cols = int(h1.w);
  p.atlas_cols = int(h2.x);
  p.patch_w = int(h2.y);
  p.patch_h = int(h2.z);
  p.table_w = textureSize(table, 0).x;
  p.table_h = int(h2.w);
  p.table_row0 = int(h3.x);
  p.atlas_w = int(h3.y);
  p.atlas_h = int(h3.z);
  p.table_offset = h3.w;
  p.flake_m0 = axf_param(table, 4).xyz;
  p.flake_m1 = axf_param(table, 5).xyz;
  p.flake_m2 = axf_param(table, 6).xyz;
  p.c = float3(0.0f);
  p.m = float3(1.0f);
  p.f0 = float3(0.0f);
  for (int k = 0; k < p.n_lobes; k++) {
    float4 l = axf_param(table, AXF_PARAM_HEADER + k);
    p.c[k] = l.x;
    p.m[k] = l.y;
    p.f0[k] = l.z;
  }
  return p;
}

/* Unpolarised dielectric Fresnel reflectance from outside (n = 1) into ior. */
float axf_fresnel(float cos_i, float ior)
{
  float ci = clamp(cos_i, 0.0f, 1.0f);
  float st = sqrt(max(1.0f - ci * ci, 0.0f)) / ior;
  float ct = sqrt(max(1.0f - st * st, 0.0f));
  float rs = (ci - ior * ct) / (ci + ior * ct);
  float rp = (ct - ior * ci) / (ct + ior * ci);
  return 0.5f * (rs * rs + rp * rp);
}

/* Refract a direction pointing away from the surface into the coat (eta = 1 / ior). */
float3 axf_refract(float3 w, float3 N, float eta)
{
  float c = dot(w, N);
  float3 t = (w - c * N) * eta;
  float ct = sqrt(max(1.0f - eta * eta * (1.0f - c * c), 0.0f));
  return normalize(t + ct * N);
}

/* Bilinear colour table lookup, texel i at (i + offset) / n of [0, pi/2], clamped. */
float3 axf_table(sampler2D table, AxfParams p, float thD, float thH)
{
  int nw = p.table_w;
  int nh = p.table_h;
  float x = clamp(thH * AXF_2_PI * float(nw) - p.table_offset, 0.0f, float(nw - 1));
  float y = clamp(thD * AXF_2_PI * float(nh) - p.table_offset, 0.0f, float(nh - 1));
  int x0 = clamp(int(floor(x)), 0, nw - 1);
  int y0 = clamp(int(floor(y)), 0, nh - 1);
  int x1 = min(x0 + 1, nw - 1);
  int y1 = min(y0 + 1, nh - 1);
  float fx = (x >= float(nw - 1)) ? 0.0f : clamp(x - floor(x), 0.0f, 1.0f);
  float fy = (y >= float(nh - 1)) ? 0.0f : clamp(y - floor(y), 0.0f, 1.0f);
  int r0 = p.table_row0;
  float3 v00 = texelFetch(table, int2(x0, r0 + y0), 0).rgb;
  float3 v01 = texelFetch(table, int2(x1, r0 + y0), 0).rgb;
  float3 v10 = texelFetch(table, int2(x0, r0 + y1), 0).rgb;
  float3 v11 = texelFetch(table, int2(x1, r0 + y1), 0).rgb;
  return (1.0f - fy) * ((1.0f - fx) * v00 + fx * v01) + fy * ((1.0f - fx) * v10 + fx * v11);
}

float3 axf_flake_corner(sampler2D table, sampler2D flakes, AxfParams p, float2 uv, int hi, int di)
{
  if (di < 0 || di >= p.lut_rows || hi < 0 || hi >= p.lut_cols) {
    return float3(0.0f);
  }
  int i = di * p.lut_cols + hi;
  float4 t = axf_param(table, AXF_PARAM_HEADER + p.n_lobes + i / 4);
  int lane = i % 4;
  int patch_index = int((lane == 0) ? t.x : (lane == 1) ? t.y : (lane == 2) ? t.z : t.w);
  if (patch_index < 0) {
    return float3(0.0f);
  }
  float2 f = uv - floor(uv);
  int xi = min(int(floor(f.x * float(p.patch_w))), p.patch_w - 1);
  int yi = min(int(floor(f.y * float(p.patch_h))), p.patch_h - 1);
  int ax = (patch_index % p.atlas_cols) * p.patch_w + xi;
  int ay = (patch_index / p.atlas_cols) * p.patch_h + yi;
  return texelFetch(flakes, int2(ax, ay), 0).rgb;
}

/* Flake BTF (linear Rec.709): bilinear in (thetaF = thetaH, thetaI = thetaD) bins of
 * width (pi/2) / num_theta_f, bin k at k * width. */
float3 axf_flakes(sampler2D table, sampler2D flakes, AxfParams p, float2 uv, float thH, float thD)
{
  if (p.num_theta_f <= 0 || p.atlas_w <= 0 || p.atlas_h <= 0) {
    return float3(0.0f);
  }
  float n = float(p.num_theta_f);
  float bh = n * (thH * AXF_2_PI);
  float bd = n * (thD * AXF_2_PI);
  int h0 = int(floor(bh));
  int d0 = int(floor(bd));
  float wh = bh - float(h0);
  float wd = bd - float(d0);
  float3 c00 = axf_flake_corner(table, flakes, p, uv, h0, d0);
  float3 c10 = axf_flake_corner(table, flakes, p, uv, h0 + 1, d0);
  float3 c01 = axf_flake_corner(table, flakes, p, uv, h0, d0 + 1);
  float3 c11 = axf_flake_corner(table, flakes, p, uv, h0 + 1, d0 + 1);
  float3 e = (1.0f - wd) * ((1.0f - wh) * c00 + wh * c10) + wd * ((1.0f - wh) * c01 + wh * c11);
  return float3(dot(p.flake_m0, e), dot(p.flake_m1, e), dot(p.flake_m2, e));
}

/* The CPA2 base BSDF times the light cosine (Cycles' axf_carpaint_eval_cos without the
 * clear coat mirror, which EEVEE draws as its own closure). V = view, L = light, both
 * pointing away from the surface; Nc = clear coat normal. Flakes are radiance per unit
 * normal irradiance and take no cosine. */
float3 axf_eval_cos(sampler2D table,
                    sampler2D flakes,
                    bool has_flakes,
                    AxfParams p,
                    float3 N,
                    float3 Nc,
                    float2 flake_uv,
                    float flake_strength,
                    float3 V,
                    float3 L)
{
  if (dot(N, V) <= 0.0f || dot(N, L) <= 0.0f) {
    return float3(0.0f);
  }
  float3 l = L;
  float3 v = V;
  if (p.refractive) {
    float eta = 1.0f / p.ior;
    l = axf_refract(L, Nc, eta);
    v = axf_refract(V, Nc, eta);
  }
  float3 h = normalize(l + v);
  float nh = dot(N, h);
  float nl = dot(N, l);
  float nv = dot(N, v);
  float vh = clamp(dot(h, v), 1e-6f, 1.0f);
  float thH = atan(length(cross(N, h)), max(nh, 0.0f));
  float thD = atan(length(cross(h, v)), vh);

  float nhc = clamp(nh, 1e-6f, 1.0f);
  float cos2 = nhc * nhc;
  float G = min(1.0f, min(2.0f * nhc * nv / vh, 2.0f * nhc * nl / vh));
  float ct = 0.0f;
  for (int k = 0; k < p.n_lobes; k++) {
    if (p.c[k] <= 0.0f) {
      continue;
    }
    float m2 = p.m[k] * p.m[k];
    float D = exp((cos2 - 1.0f) / (cos2 * m2)) / (m2 * cos2 * cos2);
    float s = 1.0f - vh;
    float s2 = s * s;
    float F = p.f0[k] + (1.0f - p.f0[k]) * (s2 * s2 * s);
    ct += p.c[k] * D * F;
  }
  ct *= G / (M_PI * max(nv * nl, 1e-12f));

  float3 T = axf_table(table, p, thD, thH);
  float t = (1.0f - axf_fresnel(dot(Nc, L), p.ior)) * (1.0f - axf_fresnel(dot(Nc, V), p.ior));
  float3 result = T * (p.kd * M_1_PI + ct) * (t * dot(N, L));
  if (has_flakes) {
    result += flake_strength * axf_flakes(table, flakes, p, flake_uv, thH, thD);
  }
  return result;
}
