/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

/* Runtime GLSL goes through Blender's shader preprocessor on every backend.
 * Kept here so the GUI regression scenario can compile and render these exact
 * sources with gpu.shader.create_from_info, including on Windows. */
namespace blender::ui {

constexpr const char *glass_vertex_source = R"GLSL(
void main()
{
  localPos = pos;
  gl_Position = ModelViewProjectionMatrix * vec4(pos, 0.0, 1.0);
}
)GLSL";

constexpr const char *glass_fragment_source = R"GLSL(
vec3 framebufferRGB(vec3 color)
{
  /* Match Blender's built-in UI colours when the framebuffer does sRGB encoding. */
  if (!srgbTarget) {
    return color;
  }
  vec3 c = max(color, vec3(0.0));
  return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c));
}

vec4 over(vec4 foreground, vec4 background)
{
  /* Input colours are straight; intermediate and output colours are premultiplied. */
  return vec4(framebufferRGB(foreground.rgb) * foreground.a, foreground.a) +
         background * (1.0 - foreground.a);
}

void main()
{
  vec2 size = pane.zw - pane.xy;
  vec2 p = localPos - (pane.xy + pane.zw) * 0.5;
  float radius = metrics.x;
  vec2 q = abs(p) - size * 0.5 + radius;
  float distance = length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - radius;
  float aa = max(fwidth(distance), 0.5);
  float coverage = 1.0 - smoothstep(-aa * 0.5, aa * 0.5, distance);
  float y = clamp((localPos.y - pane.y) / size.y, 0.0, 1.0);
  vec4 material = vec4(0.0);

#ifdef GLASS_BACKDROP
  /* Refraction is a small displacement of real content at the curved edge,
   * never a painted diagonal bevel. The rounded mask also clips the bed. */
  vec2 normal = normalize(max(q, vec2(0.0001))) * sign(p);
  float lens = 1.0 - smoothstep(0.0, max(radius, 1.0), -distance);
  vec2 samplePos = localPos + normal * lens * lighting.x;
  vec2 uv = clamp((samplePos - sourceRect.xy) / (sourceRect.zw - sourceRect.xy),
                  vec2(0.0), vec2(1.0));
  material = texture(image, uv);
  material.rgb = framebufferRGB(material.rgb) * material.a;
  material = over(glaze, material);
#endif

  material = over(mix(tintBottom, tintTop, y), material);

  /* Fade the top light inside the SAME silhouette as the body. Drawing a
   * short rounded rectangle with the capsule's full radius leaks at its ends. */
  float topDistance = pane.w - localPos.y;
  float gloss = 1.0 - smoothstep(0.0, max(metrics.z, 0.001), topDistance);
  material = over(vec4(sheen.rgb, sheen.a * gloss * gloss), material);

#ifdef GLASS_BACKDROP
  /* Optional, quiet highlight. No scissor in region coordinates: every
   * layer uses this pane's mask even inside a translated window-space draw. */
  float sweep = abs(localPos.x - pane.x - lighting.w - p.y * 0.404);
  float streak = 1.0 - smoothstep(0.0, max(lighting.z, 0.001), sweep);
  material = over(vec4(sheen.rgb, lighting.y * streak * streak), material);
#endif

  float rimMask = metrics.y > 0.0 ?
      smoothstep(-metrics.y - aa * 0.5, -metrics.y + aa * 0.5, distance) : 0.0;
  /* Subtle opposing edge light; no thick bevel or moving bar on a tint. */
  float edgeLight = mix(0.55, 1.0, y);
  material = over(vec4(rim.rgb, rim.a * rimMask * edgeLight), material);
  fragColor = material * (coverage * metrics.w);
}
)GLSL";

}  // namespace blender::ui
