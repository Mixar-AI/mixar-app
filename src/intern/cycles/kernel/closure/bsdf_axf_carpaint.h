/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: Apache-2.0 */

/* X-Rite AxF CarPaint2 (CPA2) BSDF, evaluated exactly as X-Rite's decoder does.
 *
 *   f(wi, wo) = (1 - F(nc.wi)) (1 - F(nc.wo)) * T(thetaD, thetaH) * (kd / pi + CT)
 *               + BTF(thetaH, thetaD, uv) / cos(theta_light)
 *
 * at the directions refracted by the clear coat about its normal nc, plus (in a
 * separate closure) the coat's mirror reflection about nc. CT = sum_k c_k exp(-tan^2 /
 * m_k^2) / (m_k^2 cos^4) Schlick(F0_k) G_ct / (pi nv nl). thetaH = angle(n, h'),
 * thetaD = angle(h', w'), against the base normal n. The coat normal nc comes from the
 * AxF clear coat normal map (orange peel) when the file has one, else nc = n.
 * The flake BTF is radiance per unit normal irradiance, measured through the coat: it
 * takes no coat transmission and no cosine (X-Rite's own previews reproduce per pixel
 * only this way).
 *
 * All material data lives in images written by the Mixar AxF importer:
 * - table image (float RGBA): starts with a texel stream of parameters at row 0
 *   (see AXF_PARAM_* below), then the BRDF colour table in linear Rec.709 from row
 *   table_row0 (row = thetaD bin, column = thetaH bin; image width = thetaH bins);
 * - flakes image (float RGBA): the flake BTF patches tiled in an atlas, stored
 *   exactly as in the AxF (sRGB primaries, E white); the parameters carry the 3x3
 *   matrix to Rec.709;
 * - coat normal image (float RGBA, optional): the clear coat normal map, xyz in the
 *   (tangent, bitangent, normal) frame of its texture coordinates.
 * Lookups use exact texel addressing and float math on every device, so the result
 * does not depend on hardware texture filtering.
 *
 * Reference implementation and proof: the Mixar AxF harness (axf_cpa2.py), which
 * reproduces X-Rite's own preview render of the material. */

#pragma once

#include "kernel/closure/alloc.h"
#include "kernel/closure/bsdf_util.h"
#include "kernel/image.h"
#include "kernel/sample/mapping.h"
#include "kernel/types.h"

CCL_NAMESPACE_BEGIN

#define AXF_MAX_LOBES 3
#define AXF_MAX_LUT 64

struct AxfCarPaintBsdf {
  SHADER_CLOSURE_BASE;
  float u, v;              /* Flake coordinates, in flake patch units. */
  int table_id, flakes_id; /* Kernel image ids. */
  int table_w, image_h;    /* Table image size in texels. */
  float sample_alpha;      /* Beckmann alpha used to importance sample the lobe. */
  float nc_x, nc_y, nc_z;  /* Clear coat normal (world space; = N without a coat map). */
};

static_assert(sizeof(ShaderClosure) >= sizeof(AxfCarPaintBsdf), "AxfCarPaintBsdf is too large!");

struct AxfCarPaintParams {
  float kd, ior;
  bool refractive;
  int n_lobes;
  float c[AXF_MAX_LOBES], m[AXF_MAX_LOBES], f0[AXF_MAX_LOBES];
  int num_theta_f, lut_rows, lut_cols;
  int atlas_cols, patch_w, patch_h, table_h, table_row0, atlas_w, atlas_h;
  float3 flake_m0, flake_m1, flake_m2; /* Rows of the flake colour matrix. */
};

/* Parameter texel stream (row 0, column 0, row-major across the image width):
 * 0: (version, kd, ior, refractive)
 * 1: (n_lobes, num_theta_f, lut_rows, lut_cols)
 * 2: (atlas_cols, patch_w, patch_h, table_h)
 * 3: (table_row0, atlas_w, atlas_h, 0)
 * 4..6: flake colour matrix rows (stored RGB -> linear Rec.709)
 * 7..7+n_lobes-1: (c, m, F0, 0)
 * then ceil(lut_rows * lut_cols / 4) texels of LUT entries (patch index, or -1). */
#define AXF_PARAM_HEADER 7

ccl_device_inline float4 axf_texel(KernelGlobals kg,
                                   ccl_private ShaderData *sd,
                                   const int id,
                                   const int x,
                                   const int y,
                                   const int w,
                                   const int h)
{
#if defined(__KERNEL_OPTIX__) && !defined(__SVM__)
  /* OptiX OSL kernels are built without SVM and without the image lookup. Only SVM creates
   * this closure (OSL compiles a stand-in), so it never runs there. */
  (void)kg, (void)sd, (void)id, (void)x, (void)y, (void)w, (void)h;
  return zero_float4();
#else
  const float2 co = make_float2((float(x) + 0.5f) / float(w), (float(y) + 0.5f) / float(h));
  return kernel_image_interp(kg, sd, id, dual2(co));
#endif
}

ccl_device_inline float4 axf_param(KernelGlobals kg,
                                   ccl_private ShaderData *sd,
                                   const ccl_private AxfCarPaintBsdf *bsdf,
                                   const int index)
{
  const int w = bsdf->table_w;
  return axf_texel(kg, sd, bsdf->table_id, index % w, index / w, w, bsdf->image_h);
}

ccl_device void axf_load_params(KernelGlobals kg,
                                ccl_private ShaderData *sd,
                                const ccl_private AxfCarPaintBsdf *bsdf,
                                ccl_private AxfCarPaintParams *p)
{
  const float4 h0 = axf_param(kg, sd, bsdf, 0);
  const float4 h1 = axf_param(kg, sd, bsdf, 1);
  const float4 h2 = axf_param(kg, sd, bsdf, 2);
  p->kd = h0.y;
  p->ior = h0.z;
  p->refractive = h0.w != 0.0f;
  p->n_lobes = min(int(h1.x), AXF_MAX_LOBES);
  p->num_theta_f = int(h1.y);
  p->lut_rows = int(h1.z);
  p->lut_cols = int(h1.w);
  p->atlas_cols = int(h2.x);
  p->patch_w = int(h2.y);
  p->patch_h = int(h2.z);
  p->table_h = int(h2.w);
  const float4 h3 = axf_param(kg, sd, bsdf, 3);
  p->table_row0 = int(h3.x);
  p->atlas_w = int(h3.y);
  p->atlas_h = int(h3.z);
  p->flake_m0 = make_float3(axf_param(kg, sd, bsdf, 4));
  p->flake_m1 = make_float3(axf_param(kg, sd, bsdf, 5));
  p->flake_m2 = make_float3(axf_param(kg, sd, bsdf, 6));
  for (int k = 0; k < p->n_lobes; k++) {
    const float4 l = axf_param(kg, sd, bsdf, AXF_PARAM_HEADER + k);
    p->c[k] = l.x;
    p->m[k] = l.y;
    p->f0[k] = l.z;
  }
}

ccl_device_inline int axf_lut(KernelGlobals kg,
                              ccl_private ShaderData *sd,
                              const ccl_private AxfCarPaintBsdf *bsdf,
                              const ccl_private AxfCarPaintParams *p,
                              const int row,
                              const int col)
{
  const int i = row * p->lut_cols + col;
  const float4 t = axf_param(kg, sd, bsdf, AXF_PARAM_HEADER + p->n_lobes + i / 4);
  const int lane = i % 4;
  const float v = (lane == 0) ? t.x : (lane == 1) ? t.y : (lane == 2) ? t.z : t.w;
  return int(v);
}

/* Unpolarised dielectric Fresnel reflectance from outside (n=1) into ior. */
ccl_device_inline float axf_fresnel(const float cos_i, const float ior)
{
  const float ci = clamp(cos_i, 0.0f, 1.0f);
  const float st = safe_sqrtf(1.0f - ci * ci) / ior;
  const float ct = safe_sqrtf(1.0f - st * st);
  const float rs = (ci - ior * ct) / (ci + ior * ct);
  const float rp = (ct - ior * ci) / (ct + ior * ci);
  return 0.5f * (rs * rs + rp * rp);
}

/* Refract a direction pointing away from the surface into the coat (eta = 1/ior). */
ccl_device_inline float3 axf_refract(const float3 w, const float3 N, const float eta)
{
  const float c = dot(w, N);
  const float3 t = (w - c * N) * eta;
  const float ct = safe_sqrtf(1.0f - eta * eta * (1.0f - c * c));
  return normalize(t + ct * N);
}

/* Clear coat normal from the coat normal map at coat coordinates uv (map tile units,
 * u along columns, v along rows): bilinear between texel centres in float math, wrapping;
 * the map's xyz is in the frame (T, N x T, N) of the coordinates. */
ccl_device float3 axf_coat_normal(KernelGlobals kg,
                                  ccl_private ShaderData *sd,
                                  const int id,
                                  const int w,
                                  const int h,
                                  const float3 uv,
                                  const float3 N,
                                  const float3 tangent)
{
  const float x = (uv.x - floorf(uv.x)) * float(w) - 0.5f;
  const float y = (uv.y - floorf(uv.y)) * float(h) - 0.5f;
  const float fx = x - floorf(x);
  const float fy = y - floorf(y);
  int x0 = int(floorf(x)) % w;
  int y0 = int(floorf(y)) % h;
  x0 = (x0 < 0) ? x0 + w : x0;
  y0 = (y0 < 0) ? y0 + h : y0;
  const int x1 = (x0 + 1) % w;
  const int y1 = (y0 + 1) % h;
  const float3 v00 = make_float3(axf_texel(kg, sd, id, x0, y0, w, h));
  const float3 v01 = make_float3(axf_texel(kg, sd, id, x1, y0, w, h));
  const float3 v10 = make_float3(axf_texel(kg, sd, id, x0, y1, w, h));
  const float3 v11 = make_float3(axf_texel(kg, sd, id, x1, y1, w, h));
  const float3 t = (1.0f - fy) * ((1.0f - fx) * v00 + fx * v01) +
                   fy * ((1.0f - fx) * v10 + fx * v11);

  float3 T = tangent - dot(tangent, N) * N;
  if (len_squared(T) < 1e-12f) {
    float3 B;
    make_orthonormals(N, &T, &B);
  }
  T = normalize(T);
  const float3 B = cross(N, T);
  return safe_normalize_fallback(t.x * T + t.y * B + t.z * N, N);
}

/* Bilinear lookup of the colour table, texel i at i / n of [0, pi/2] (as the flake bins),
 * clamped at the last texel. This addressing reproduces X-Rite's own preview render to
 * float precision; i / (n - 1) (Unity HDRP) is off by up to 1 %. */
ccl_device float3 axf_table(KernelGlobals kg,
                            ccl_private ShaderData *sd,
                            const ccl_private AxfCarPaintBsdf *bsdf,
                            const ccl_private AxfCarPaintParams *p,
                            const float thD,
                            const float thH)
{
  const int nw = bsdf->table_w;
  const int nh = p->table_h;
  const float x = fminf(thH * M_2_PI_F * float(nw), float(nw - 1)); /* column = thetaH */
  const float y = fminf(thD * M_2_PI_F * float(nh), float(nh - 1)); /* row = thetaD */
  const int x0 = clamp(int(floorf(x)), 0, nw - 1);
  const int y0 = clamp(int(floorf(y)), 0, nh - 1);
  const int x1 = min(x0 + 1, nw - 1);
  const int y1 = min(y0 + 1, nh - 1);
  const float fx = (x >= float(nw - 1)) ? 0.0f : clamp(x - floorf(x), 0.0f, 1.0f);
  const float fy = (y >= float(nh - 1)) ? 0.0f : clamp(y - floorf(y), 0.0f, 1.0f);
  const int id = bsdf->table_id;
  const int rows = bsdf->image_h;
  const int r0 = p->table_row0;
  const float3 v00 = make_float3(axf_texel(kg, sd, id, x0, r0 + y0, nw, rows));
  const float3 v01 = make_float3(axf_texel(kg, sd, id, x1, r0 + y0, nw, rows));
  const float3 v10 = make_float3(axf_texel(kg, sd, id, x0, r0 + y1, nw, rows));
  const float3 v11 = make_float3(axf_texel(kg, sd, id, x1, r0 + y1, nw, rows));
  return (1.0f - fy) * ((1.0f - fx) * v00 + fx * v01) + fy * ((1.0f - fx) * v10 + fx * v11);
}

/* Nearest-texel fetch from one flake patch in the atlas (stored colour space). */
ccl_device float3 axf_flake_texel(KernelGlobals kg,
                                  ccl_private ShaderData *sd,
                                  const ccl_private AxfCarPaintBsdf *bsdf,
                                  const ccl_private AxfCarPaintParams *p,
                                  const int patch)
{
  const float fu = bsdf->u - floorf(bsdf->u);
  const float fv = bsdf->v - floorf(bsdf->v);
  const int xi = min(int(floorf(fu * float(p->patch_w))), p->patch_w - 1);
  const int yi = min(int(floorf(fv * float(p->patch_h))), p->patch_h - 1);
  const int ax = (patch % p->atlas_cols) * p->patch_w + xi;
  const int ay = (patch / p->atlas_cols) * p->patch_h + yi;
  return make_float3(axf_texel(kg, sd, bsdf->flakes_id, ax, ay, p->atlas_w, p->atlas_h));
}

ccl_device float3 axf_flake_corner(KernelGlobals kg,
                                   ccl_private ShaderData *sd,
                                   const ccl_private AxfCarPaintBsdf *bsdf,
                                   const ccl_private AxfCarPaintParams *p,
                                   const int hi,
                                   const int di)
{
  if (di < 0 || di >= p->lut_rows || hi < 0 || hi >= p->lut_cols) {
    return zero_float3();
  }
  const int patch = axf_lut(kg, sd, bsdf, p, di, hi);
  if (patch < 0) {
    return zero_float3();
  }
  return axf_flake_texel(kg, sd, bsdf, p, patch);
}

/* Flake BTF: bilinear in (thetaF = thetaH, thetaI = thetaD) bins of width
 * (pi/2) / num_theta_f, bin k at k * width (no half-bin offset). */
ccl_device float3 axf_flakes(KernelGlobals kg,
                             ccl_private ShaderData *sd,
                             const ccl_private AxfCarPaintBsdf *bsdf,
                             const ccl_private AxfCarPaintParams *p,
                             const float thH,
                             const float thD)
{
  /* Version 1 parameter streams (imported before the atlas size moved into the stream)
   * carry no atlas size: render without flakes rather than read out of range. */
  if (bsdf->flakes_id == KERNEL_IMAGE_NONE || p->num_theta_f <= 0 || p->atlas_w <= 0 ||
      p->atlas_h <= 0)
  {
    return zero_float3();
  }
  const float n = float(p->num_theta_f);
  const float bh = n * (thH * M_2_PI_F);
  const float bd = n * (thD * M_2_PI_F);
  const int h0 = int(floorf(bh));
  const int d0 = int(floorf(bd));
  const float wh = bh - float(h0);
  const float wd = bd - float(d0);
  const float3 c00 = axf_flake_corner(kg, sd, bsdf, p, h0, d0);
  const float3 c10 = axf_flake_corner(kg, sd, bsdf, p, h0 + 1, d0);
  const float3 c01 = axf_flake_corner(kg, sd, bsdf, p, h0, d0 + 1);
  const float3 c11 = axf_flake_corner(kg, sd, bsdf, p, h0 + 1, d0 + 1);
  const float3 rgb_e = (1.0f - wd) * ((1.0f - wh) * c00 + wh * c10) +
                       wd * ((1.0f - wh) * c01 + wh * c11);
  return make_float3(dot(p->flake_m0, rgb_e), dot(p->flake_m1, rgb_e), dot(p->flake_m2, rgb_e));
}

/* The full CPA2 BSDF times the light cosine (what eval returns), wi = view, wo = light. */
ccl_device float3 axf_carpaint_eval_cos(KernelGlobals kg,
                                    ccl_private ShaderData *sd,
                                    const ccl_private AxfCarPaintBsdf *bsdf,
                                    const ccl_private AxfCarPaintParams *p,
                                    const float3 wi,
                                    const float3 wo)
{
  const float3 N = bsdf->N;
  const float3 Nc = make_float3(bsdf->nc_x, bsdf->nc_y, bsdf->nc_z);
  if (dot(N, wi) <= 0.0f || dot(N, wo) <= 0.0f) {
    return zero_float3();
  }

  /* The coat refracts (and transmits) about its own normal; the base is evaluated
   * against the base normal. */
  float3 l = wo;
  float3 v = wi;
  if (p->refractive) {
    const float eta = 1.0f / p->ior;
    l = axf_refract(wo, Nc, eta);
    v = axf_refract(wi, Nc, eta);
  }
  const float3 h = normalize(l + v);
  const float nh = dot(N, h);
  const float nl = dot(N, l);
  const float nv = dot(N, v);
  const float vh = clamp(dot(h, v), 1e-6f, 1.0f);
  /* atan2 of (|cross|, dot) stays accurate near 0 degrees, where acos (especially GPU
   * fast-math acos) loses precision; the flake bins are linear in these angles. */
  const float thH = atan2f(len(cross(N, h)), fmaxf(nh, 0.0f));
  const float thD = atan2f(len(cross(h, v)), vh);

  /* Multi-lobe Cook-Torrance as defined by X-Rite (no 1/pi in D, pi in the denominator). */
  const float nhc = clamp(nh, 1e-6f, 1.0f);
  const float cos2 = nhc * nhc;
  const float G = fminf(1.0f, fminf(2.0f * nhc * nv / vh, 2.0f * nhc * nl / vh));
  float ct = 0.0f;
  for (int k = 0; k < p->n_lobes; k++) {
    if (p->c[k] <= 0.0f) {
      continue;
    }
    const float m2 = p->m[k] * p->m[k];
    const float D = expf((cos2 - 1.0f) / (cos2 * m2)) / (m2 * cos2 * cos2);
    const float s = 1.0f - vh;
    const float s2 = s * s;
    const float F = p->f0[k] + (1.0f - p->f0[k]) * (s2 * s2 * s);
    ct += p->c[k] * D * F;
  }
  ct *= G / (M_PI_F * fmaxf(nv * nl, 1e-12f));

  const float3 T = axf_table(kg, sd, bsdf, p, thD, thH);
  /* Clear coat transmission in and out (no solid angle compression). */
  const float t = (1.0f - axf_fresnel(dot(Nc, wo), p->ior)) *
                  (1.0f - axf_fresnel(dot(Nc, wi), p->ior));
  return T * (p->kd * M_1_PI_F + ct) * (t * dot(N, wo)) + axf_flakes(kg, sd, bsdf, p, thH, thD);
}

/* Sampling: one-sample mixture of a cosine lobe, a uniform hemisphere (the flake BTF
 * has no cosine, so cosine sampling alone is noisy at grazing light) and a Beckmann
 * half-vector lobe. */
#define AXF_P_COS 0.45f
#define AXF_P_UNIFORM 0.1f
ccl_device_inline float axf_beckmann_D(const float alpha, const float cos_h)
{
  if (cos_h <= 0.0f) {
    return 0.0f;
  }
  const float c2 = cos_h * cos_h;
  const float a2 = alpha * alpha;
  return expf((c2 - 1.0f) / (c2 * a2)) / (M_PI_F * a2 * c2 * c2);
}

ccl_device float axf_carpaint_pdf(const ccl_private AxfCarPaintBsdf *bsdf,
                                  const float3 wi,
                                  const float3 wo)
{
  const float3 N = bsdf->N;
  const float cos_l = dot(N, wo);
  if (cos_l <= 0.0f) {
    return 0.0f;
  }
  const float pdf_cos = cos_l * M_1_PI_F;
  const float pdf_uniform = M_1_2PI_F;
  const float3 h = normalize(wi + wo);
  const float oh = dot(wo, h);
  float pdf_spec = 0.0f;
  if (oh > 0.0f) {
    const float nh = dot(N, h);
    pdf_spec = axf_beckmann_D(bsdf->sample_alpha, nh) * nh / (4.0f * oh);
  }
  return AXF_P_COS * pdf_cos + AXF_P_UNIFORM * pdf_uniform +
         (1.0f - AXF_P_COS - AXF_P_UNIFORM) * pdf_spec;
}

/* Best-effort albedo for passes and closure selection (not used for shading):
 * coat transmission x colour table at the mirror configuration x (kd + 4 sum c F),
 * since X-Rite's CT lobe integrates to about 4 c F (the flake BTF is left out). */
ccl_device Spectrum axf_carpaint_albedo(KernelGlobals kg,
                                        ccl_private ShaderData *sd,
                                        const ccl_private AxfCarPaintBsdf *bsdf,
                                        const ccl_private AxfCarPaintParams *p)
{
  const float cos_v = clamp(dot(bsdf->N, sd->wi), 0.0f, 1.0f);
  const float eta = p->refractive ? 1.0f / p->ior : 1.0f;
  const float cos_vr = safe_sqrtf(1.0f - eta * eta * (1.0f - cos_v * cos_v));
  const float thD = atan2f(safe_sqrtf(1.0f - cos_vr * cos_vr), cos_vr);
  float spec = 0.0f;
  for (int k = 0; k < p->n_lobes; k++) {
    const float s = 1.0f - cos_vr;
    const float s2 = s * s;
    spec += 4.0f * fmaxf(p->c[k], 0.0f) * (p->f0[k] + (1.0f - p->f0[k]) * (s2 * s2 * s));
  }
  const float t_v = 1.0f - axf_fresnel(cos_v, p->ior);
  /* Cosine-weighted mean coat transmission over incoming light directions. */
  const float t_l = 1.0f - fresnel_dielectric_Fss(p->ior);
  const float3 T = axf_table(kg, sd, bsdf, p, thD, 0.0f);
  return rgb_to_spectrum(max(T * (p->kd + spec) * (t_v * t_l), zero_float3()));
}

ccl_device int bsdf_axf_carpaint_setup(KernelGlobals kg,
                                       ccl_private ShaderData *sd,
                                       ccl_private AxfCarPaintBsdf *bsdf)
{
  bsdf->type = CLOSURE_BSDF_AXF_CARPAINT_ID;
  if (bsdf->table_id == KERNEL_IMAGE_NONE || bsdf->table_w == 0) {
    bsdf->type = CLOSURE_NONE_ID;
    bsdf->sample_weight = 0.0f;
    return 0;
  }
  AxfCarPaintParams p;
  axf_load_params(kg, sd, bsdf, &p);
  /* The refractive coat widens the lobe seen from outside by about the IOR. */
  float alpha = 0.3f;
  float best = -1.0f;
  for (int k = 0; k < p.n_lobes; k++) {
    if (p.c[k] > best) {
      best = p.c[k];
      alpha = p.m[k] * (p.refractive ? p.ior : 1.0f);
    }
  }
  bsdf->sample_alpha = clamp(alpha, 0.02f, 1.0f);
  bsdf->sample_weight *= average(axf_carpaint_albedo(kg, sd, bsdf, &p));
  return SD_BSDF | SD_BSDF_HAS_EVAL;
}

ccl_device Spectrum bsdf_axf_carpaint_eval(KernelGlobals kg,
                                           ccl_private ShaderData *sd,
                                           const ccl_private ShaderClosure *sc,
                                           const float3 wi,
                                           const float3 wo,
                                           ccl_private float *pdf)
{
  const ccl_private AxfCarPaintBsdf *bsdf = (const ccl_private AxfCarPaintBsdf *)sc;
  const float cos_l = dot(bsdf->N, wo);
  if (cos_l <= 0.0f || dot(bsdf->N, wi) <= 0.0f) {
    *pdf = 0.0f;
    return zero_spectrum();
  }
  *pdf = axf_carpaint_pdf(bsdf, wi, wo);
  AxfCarPaintParams p;
  axf_load_params(kg, sd, bsdf, &p);
  return rgb_to_spectrum(axf_carpaint_eval_cos(kg, sd, bsdf, &p, wi, wo));
}

ccl_device int bsdf_axf_carpaint_sample(KernelGlobals kg,
                                        ccl_private ShaderData *sd,
                                        const ccl_private ShaderClosure *sc,
                                        const float3 Ng,
                                        const float3 wi,
                                        const float2 rand,
                                        ccl_private Spectrum *eval,
                                        ccl_private float3 *wo,
                                        ccl_private float *pdf,
                                        ccl_private float2 *sampled_roughness)
{
  const ccl_private AxfCarPaintBsdf *bsdf = (const ccl_private AxfCarPaintBsdf *)sc;
  const float3 N = bsdf->N;
  *sampled_roughness = make_float2(bsdf->sample_alpha, bsdf->sample_alpha);

  float2 r = rand;
  if (r.x < AXF_P_COS) {
    r.x /= AXF_P_COS;
    float pdf_unused;
    sample_cos_hemisphere(N, r, wo, &pdf_unused);
  }
  else if (r.x < AXF_P_COS + AXF_P_UNIFORM) {
    r.x = (r.x - AXF_P_COS) / AXF_P_UNIFORM;
    float pdf_unused;
    sample_uniform_hemisphere(N, r, wo, &pdf_unused);
  }
  else {
    r.x = (r.x - AXF_P_COS - AXF_P_UNIFORM) / (1.0f - AXF_P_COS - AXF_P_UNIFORM);
    const float a = bsdf->sample_alpha;
    const float tan2 = -a * a * logf(fmaxf(1.0f - r.x, 1e-12f));
    const float cos_t = 1.0f / sqrtf(1.0f + tan2);
    const float sin_t = safe_sqrtf(1.0f - cos_t * cos_t);
    const float phi = M_2PI_F * r.y;
    float3 T, B;
    make_orthonormals(N, &T, &B);
    const float3 h = sin_t * cosf(phi) * T + sin_t * sinf(phi) * B + cos_t * N;
    *wo = 2.0f * dot(wi, h) * h - wi;
  }

  if (dot(Ng, *wo) <= 0.0f || dot(N, *wo) <= 0.0f) {
    *pdf = 0.0f;
    *eval = zero_spectrum();
    return LABEL_REFLECT | LABEL_GLOSSY;
  }
  *eval = bsdf_axf_carpaint_eval(kg, sd, sc, wi, *wo, pdf);
  return LABEL_REFLECT | LABEL_GLOSSY;
}

CCL_NAMESPACE_END
