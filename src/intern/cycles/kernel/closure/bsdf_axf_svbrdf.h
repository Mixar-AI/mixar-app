/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: Apache-2.0 */

/* X-Rite AxF SVBRDF (Lambert + Ward or GGX, per texel), evaluated exactly as X-Rite's
 * decoder does. Each texel's parameters come from an atlas image written by the Mixar
 * AxF importer (see svm_axf_svbrdf_fetch below); the SVM node resolves the texel, the
 * normal map and the lobe frame, and this closure evaluates
 *
 *   f(l, v) cos = (kd / pi + ks * spec(l, v)) * dot(n, l)
 *
 * about the normal-map normal n (the cosine too), zero unless n.l > 0 and n.v > 0.
 * spec, with h = l + v (unnormalised) and the frame (t, b = n x t, n):
 * - Ward, Geisler-Moroder 2010 (bounded albedo):
 *     exp(-((h.t / ax)^2 + (h.b / ay)^2) / (h.n)^2) / (pi ax ay) * (h.h) / (h.n)^4
 *   and the "Covariance" variant: exp(-s^T S^-1 s) / (pi sqrt(det S)) * (h.h) / (h.n)^4,
 *   s = (h.t, h.b) / h.n, S = [[a^2, b], [b, c^2]];
 * - GGX: D G1(l) G1(v) F / (4 n.l n.v), separable Smith G1, Schlick F with the file's F0.
 * Each of these reproduces X-Rite's own embedded preview of the sample files per pixel
 * (Mixar AxF harness, build-29-10-svbrdf). The diffuse term lives in this closure (not a
 * Cycles diffuse closure) so Cycles' bump-terminator softening never alters it. */

#pragma once

#include "kernel/closure/alloc.h"
#include "kernel/closure/bsdf_util.h"
#include "kernel/sample/mapping.h"
#include "kernel/types.h"

CCL_NAMESPACE_BEGIN

enum AxfSvbrdfModel {
  AXF_SVBRDF_WARD = 0,     /* p0 = alpha along t, p1 = alpha along b. */
  AXF_SVBRDF_WARD_COV = 1, /* p0 = a, p1 = b, p2 = c: S = [[a^2, b], [b, c^2]] in (t, b). */
  AXF_SVBRDF_GGX = 2,      /* p0 = alpha; f0 < 0 means no Fresnel. */
};

struct AxfSvbrdfBsdf {
  SHADER_CLOSURE_BASE;
  float kd_r, kd_g, kd_b; /* Diffuse albedo (linear Rec.709). */
  float ks_r, ks_g, ks_b; /* Specular colour. */
  /* Lobe frame: t = cos(angle) T0 + sin(angle) B0 with (T0, B0) = make_orthonormals(N). */
  float frame_angle;
  float p0, p1, p2; /* Lobe parameters (see AxfSvbrdfModel). */
  float f0;
  int model;
};

static_assert(sizeof(ShaderClosure) >= sizeof(AxfSvbrdfBsdf), "AxfSvbrdfBsdf is too large!");

ccl_device_inline float3 axf_svbrdf_kd(const ccl_private AxfSvbrdfBsdf *bsdf)
{
  return make_float3(bsdf->kd_r, bsdf->kd_g, bsdf->kd_b);
}

ccl_device_inline float3 axf_svbrdf_ks(const ccl_private AxfSvbrdfBsdf *bsdf)
{
  return make_float3(bsdf->ks_r, bsdf->ks_g, bsdf->ks_b);
}

ccl_device_inline void axf_svbrdf_frame(const ccl_private AxfSvbrdfBsdf *bsdf,
                                        ccl_private float3 *t,
                                        ccl_private float3 *b)
{
  float3 T0, B0;
  make_orthonormals(bsdf->N, &T0, &B0);
  *t = cosf(bsdf->frame_angle) * T0 + sinf(bsdf->frame_angle) * B0;
  *b = cross(bsdf->N, *t);
}

/* Angle of a unit tangent t (perpendicular to N) in make_orthonormals(N). */
ccl_device_inline float axf_svbrdf_frame_angle(const float3 N, const float3 t)
{
  float3 T0, B0;
  make_orthonormals(N, &T0, &B0);
  return atan2f(dot(t, B0), dot(t, T0));
}

/* Ward slope distribution exp(-s^T S^-1 s) / (pi sqrt(det S)) at slope s = (sx, sy). */
ccl_device_inline float axf_svbrdf_ward_slope_pdf(const ccl_private AxfSvbrdfBsdf *bsdf,
                                                  const float sx,
                                                  const float sy)
{
  if (bsdf->model == AXF_SVBRDF_WARD) {
    const float ax = bsdf->p0, ay = bsdf->p1;
    const float e = sqr(sx / ax) + sqr(sy / ay);
    return expf(-e) / (M_PI_F * ax * ay);
  }
  const float sxx = sqr(bsdf->p0), sxy = bsdf->p1, syy = sqr(bsdf->p2);
  const float det = sxx * syy - sxy * sxy;
  if (!(det > 0.0f)) {
    return 0.0f;
  }
  const float e = (syy * sx * sx - 2.0f * sxy * sx * sy + sxx * sy * sy) / det;
  return expf(-e) / (M_PI_F * sqrtf(det));
}

ccl_device_inline float axf_svbrdf_ggx_D(const float a2, const float nh)
{
  const float d = nh * nh * (a2 - 1.0f) + 1.0f;
  return a2 / (M_PI_F * d * d);
}

ccl_device_inline float axf_svbrdf_ggx_G1(const float a2, const float c)
{
  return 2.0f * c / (c + sqrtf(a2 + (1.0f - a2) * c * c));
}

/* spec(l, v) (no cosine); l = light, v = view, both above n. */
ccl_device float axf_svbrdf_spec(const ccl_private AxfSvbrdfBsdf *bsdf,
                                 const float3 l,
                                 const float3 v,
                                 const float nl,
                                 const float nv)
{
  const float3 n = bsdf->N;
  const float3 hv = l + v;
  if (bsdf->model == AXF_SVBRDF_GGX) {
    const float3 h = normalize(hv);
    const float nh = dot(n, h);
    const float lh = dot(l, h);
    const float a2 = sqr(bsdf->p0);
    float F = 1.0f;
    if (bsdf->f0 >= 0.0f) {
      const float s = 1.0f - lh;
      const float s2 = s * s;
      F = bsdf->f0 + (1.0f - bsdf->f0) * (s2 * s2 * s);
    }
    return axf_svbrdf_ggx_D(a2, nh) * axf_svbrdf_ggx_G1(a2, nl) * axf_svbrdf_ggx_G1(a2, nv) * F /
           (4.0f * nl * nv);
  }
  float3 t, b;
  axf_svbrdf_frame(bsdf, &t, &b);
  const float hz = dot(hv, n);
  if (hz <= 0.0f) {
    return 0.0f;
  }
  const float sx = dot(hv, t) / hz;
  const float sy = dot(hv, b) / hz;
  const float hz2 = hz * hz;
  return axf_svbrdf_ward_slope_pdf(bsdf, sx, sy) * dot(hv, hv) / (hz2 * hz2);
}

/* Probability of sampling the specular lobe (else cosine-weighted diffuse). */
ccl_device_inline float axf_svbrdf_spec_prob(const ccl_private AxfSvbrdfBsdf *bsdf)
{
  const float wd = average(max(axf_svbrdf_kd(bsdf), zero_float3()));
  float ws = average(max(axf_svbrdf_ks(bsdf), zero_float3()));
  if (bsdf->model == AXF_SVBRDF_GGX && bsdf->f0 >= 0.0f) {
    ws *= bsdf->f0 + (1.0f - bsdf->f0) * 0.1f;
  }
  if (!(wd + ws > 0.0f)) {
    return 0.5f;
  }
  return clamp(ws / (wd + ws), 0.1f, 0.9f);
}

/* Solid-angle density of the sampled half vector h (unit, above n). */
ccl_device float axf_svbrdf_half_pdf(const ccl_private AxfSvbrdfBsdf *bsdf, const float3 h)
{
  const float nh = dot(bsdf->N, h);
  if (nh <= 0.0f) {
    return 0.0f;
  }
  if (bsdf->model == AXF_SVBRDF_GGX) {
    return axf_svbrdf_ggx_D(sqr(bsdf->p0), nh) * nh;
  }
  float3 t, b;
  axf_svbrdf_frame(bsdf, &t, &b);
  const float sx = dot(h, t) / nh;
  const float sy = dot(h, b) / nh;
  /* Slope density -> solid angle: d(omega_h) = d(slope) cos^3(theta_h). */
  return axf_svbrdf_ward_slope_pdf(bsdf, sx, sy) / (nh * nh * nh);
}

ccl_device float axf_svbrdf_pdf(const ccl_private AxfSvbrdfBsdf *bsdf,
                                const float3 wi,
                                const float3 wo)
{
  const float cos_l = dot(bsdf->N, wo);
  if (cos_l <= 0.0f) {
    return 0.0f;
  }
  const float ps = axf_svbrdf_spec_prob(bsdf);
  const float3 h = normalize(wi + wo);
  const float oh = dot(wo, h);
  const float pdf_spec = (oh > 0.0f) ? axf_svbrdf_half_pdf(bsdf, h) / (4.0f * oh) : 0.0f;
  return (1.0f - ps) * cos_l * M_1_PI_F + ps * pdf_spec;
}

/* Best-effort albedo for passes and closure selection (not used for shading). */
ccl_device_inline Spectrum axf_svbrdf_albedo(const ccl_private AxfSvbrdfBsdf *bsdf)
{
  float spec = 1.0f;
  if (bsdf->model == AXF_SVBRDF_GGX && bsdf->f0 >= 0.0f) {
    spec = bsdf->f0 + (1.0f - bsdf->f0) * 0.1f;
  }
  return rgb_to_spectrum(
      max(axf_svbrdf_kd(bsdf) + spec * axf_svbrdf_ks(bsdf), zero_float3()));
}

ccl_device int bsdf_axf_svbrdf_setup(ccl_private AxfSvbrdfBsdf *bsdf)
{
  bsdf->type = CLOSURE_BSDF_AXF_SVBRDF_ID;
  const bool valid = (bsdf->model == AXF_SVBRDF_GGX) ? bsdf->p0 > 0.0f :
                     (bsdf->model == AXF_SVBRDF_WARD) ? (bsdf->p0 > 0.0f && bsdf->p1 > 0.0f) :
                                                         (bsdf->p0 > 0.0f && bsdf->p2 > 0.0f);
  if (!valid) {
    /* A degenerate lobe (zero roughness) keeps only the diffuse part. */
    bsdf->ks_r = bsdf->ks_g = bsdf->ks_b = 0.0f;
    bsdf->model = AXF_SVBRDF_GGX;
    bsdf->p0 = 1.0f;
  }
  bsdf->sample_weight *= average(axf_svbrdf_albedo(bsdf));
  return SD_BSDF | SD_BSDF_HAS_EVAL;
}

ccl_device Spectrum bsdf_axf_svbrdf_eval(const ccl_private ShaderClosure *sc,
                                         const float3 wi,
                                         const float3 wo,
                                         ccl_private float *pdf)
{
  const ccl_private AxfSvbrdfBsdf *bsdf = (const ccl_private AxfSvbrdfBsdf *)sc;
  const float nl = dot(bsdf->N, wo);
  const float nv = dot(bsdf->N, wi);
  if (nl <= 0.0f || nv <= 0.0f) {
    *pdf = 0.0f;
    return zero_spectrum();
  }
  *pdf = axf_svbrdf_pdf(bsdf, wi, wo);
  const float spec = axf_svbrdf_spec(bsdf, wo, wi, nl, nv);
  return rgb_to_spectrum((axf_svbrdf_kd(bsdf) * M_1_PI_F + axf_svbrdf_ks(bsdf) * spec) * nl);
}

ccl_device int bsdf_axf_svbrdf_sample(const ccl_private ShaderClosure *sc,
                                      const float3 Ng,
                                      const float3 wi,
                                      const float2 rand,
                                      ccl_private Spectrum *eval,
                                      ccl_private float3 *wo,
                                      ccl_private float *pdf,
                                      ccl_private float2 *sampled_roughness)
{
  const ccl_private AxfSvbrdfBsdf *bsdf = (const ccl_private AxfSvbrdfBsdf *)sc;
  const float3 N = bsdf->N;
  const float ps = axf_svbrdf_spec_prob(bsdf);
  const float rough = (bsdf->model == AXF_SVBRDF_GGX) ? bsdf->p0 :
                      (bsdf->model == AXF_SVBRDF_WARD) ? sqrtf(bsdf->p0 * bsdf->p1) :
                                                          sqrtf(bsdf->p0 * bsdf->p2);
  *sampled_roughness = make_float2(rough, rough);

  float2 r = rand;
  if (r.x >= ps) {
    r.x = (r.x - ps) / (1.0f - ps);
    float pdf_unused;
    sample_cos_hemisphere(N, r, wo, &pdf_unused);
  }
  else {
    r.x /= ps;
    float3 h;
    if (bsdf->model == AXF_SVBRDF_GGX) {
      const float a2 = sqr(bsdf->p0);
      const float u = fminf(r.x, 1.0f - 1e-7f);
      const float tan2 = a2 * u / (1.0f - u);
      const float cos_t = 1.0f / sqrtf(1.0f + tan2);
      const float sin_t = safe_sqrtf(1.0f - cos_t * cos_t);
      const float phi = M_2PI_F * r.y;
      float3 T, B;
      make_orthonormals(N, &T, &B);
      h = sin_t * cosf(phi) * T + sin_t * sinf(phi) * B + cos_t * N;
    }
    else {
      /* Slope s ~ exp(-s^T S^-1 s): s = L z with L L^T = S, z ~ exp(-|z|^2) / pi. */
      const float rr = sqrtf(-logf(fmaxf(1.0f - r.x, 1e-12f)));
      const float phi = M_2PI_F * r.y;
      const float zx = rr * cosf(phi), zy = rr * sinf(phi);
      float sx, sy;
      if (bsdf->model == AXF_SVBRDF_WARD) {
        sx = bsdf->p0 * zx;
        sy = bsdf->p1 * zy;
      }
      else {
        const float l11 = bsdf->p0;
        const float l21 = bsdf->p1 / bsdf->p0;
        const float l22 = safe_sqrtf(sqr(bsdf->p2) - l21 * l21);
        sx = l11 * zx;
        sy = l21 * zx + l22 * zy;
      }
      float3 t, b;
      axf_svbrdf_frame(bsdf, &t, &b);
      h = normalize(sx * t + sy * b + N);
    }
    *wo = 2.0f * dot(wi, h) * h - wi;
  }

  if (dot(Ng, *wo) <= 0.0f || dot(N, *wo) <= 0.0f) {
    *pdf = 0.0f;
    *eval = zero_spectrum();
    return LABEL_REFLECT | LABEL_GLOSSY;
  }
  *eval = bsdf_axf_svbrdf_eval(sc, wi, *wo, pdf);
  return LABEL_REFLECT | LABEL_GLOSSY;
}

CCL_NAMESPACE_END
