/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Paints the Agent island.
 *
 * Shapes come from `agent_ui_layout`; colours and sizes from
 * `agent_ui_theme`. Nothing here re-derives geometry — the hit test reads the
 * same layout struct, and one definition is what keeps a click landing where
 * the pixel it targets was drawn.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"

#include "DNA_screen_types.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"

#include "agent_bubble_intern.hh"
#include "agent_ui_draw.hh"
#include "agent_ui_icons.hh"
#include "agent_ui_layout.hh"
#include "agent_ui_motion.hh"
#include "agent_ui_pill_cat.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* -------------------------------------------------------------------- */
/** \name Shape helpers
 * \{ */

void fill_round(const rctf *rect, const float radius, const float col[4])
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(rect, true, radius, col);
}

void outline_round(const rctf *rect, const float radius, const float col[4])
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(rect, false, radius, col);
}

/**
 * Rounded rect filled with a two-stop ramp along an ARBITRARY axis.
 *
 * `ui::draw_roundbox_4fv_ex` can only shade vertically, and the card's ramp is
 * diagonal — it runs from the card's top-right down and to the left, past the
 * bottom edge. Shading it vertically loses the horizontal falloff entirely,
 * which is most of the effect: at the card's top edge the artboard travels
 * from #072B1B on the left to #2E5630 on the right.
 *
 * So the fill is a triangle fan with per-vertex colour, sampled at
 * t = clamp(dot(p - a, b - a) / |b - a|^2, 0, 1). A raw fan is rasterised with
 * no coverage anti-aliasing, so its rim carries its own half-pixel feather
 * (see `aa` below) — on the card that seam hides under the AA'd border, but
 * the minimised pill's capsule and logo chip have nothing over them and drew
 * visibly stair-stepped without it.
 */
void fill_round_gradient(const rctf *rect,
                         const float radius,
                         const float c0[4],
                         const float c1[4],
                         const float a[2],
                         const float b[2])
{
  const float abx = b[0] - a[0];
  const float aby = b[1] - a[1];
  const float len_sq = abx * abx + aby * aby;
  if (len_sq <= 0.0f) {
    fill_round(rect, radius, c0);
    return;
  }

  /* Corner arcs tessellated FROM the radius rather than at a fixed count: 8
   * segments is fine on a small chip and visibly polygonal on the minimised
   * pill's capsule and logo chip, where the radius runs to tens of pixels. */
  constexpr int ARC_MAX = 32;
  constexpr int RIM_MAX = (ARC_MAX + 1) * 4;

  const float x0 = rect->xmin;
  const float x1 = rect->xmax;
  const float y0 = rect->ymin;
  const float y1 = rect->ymax;
  const float r = std::min(radius, std::min((x1 - x0), (y1 - y0)) * 0.5f);
  const int arc = std::clamp(int(std::ceil(r)), 8, ARC_MAX);

  /* Half-pixel feather. The fan is rasterised without coverage AA, so its rim
   * steps against whatever is behind it — on the minimised pill that is the
   * opaque bed, and the capsule and its logo chip drew visibly stair-stepped
   * (the capsule's faint rim stroke is at alpha 0.14 and covers nothing, and
   * the idle chip carries no stroke at all). So the solid fan is pulled half a
   * pixel INSIDE the nominal edge and a ring of quads carries the colour from
   * there to half a pixel outside at zero alpha, putting the visual edge back
   * exactly where it was with a one-pixel ramp across it. */
  const float aa = (r > 0.5f) ? 0.5f : 0.0f;

  float rim[RIM_MAX][2];
  float nrm[RIM_MAX][2];
  int n = 0;
  /* Corner centres walked ANTICLOCKWISE from bottom-right, each sweeping the
   * quadrant that starts at `base`. Centre order and angle order have to agree
   * — pairing a bottom-left centre with a bottom-right quadrant folds the
   * polygon in on itself and the fill stops covering the card. */
  const float cx[4] = {x1 - r, x1 - r, x0 + r, x0 + r};
  const float cy[4] = {y0 + r, y1 - r, y1 - r, y0 + r};
  for (int corner = 0; corner < 4; corner++) {
    const float base = float(M_PI) * -0.5f + float(corner) * float(M_PI) * 0.5f;
    for (int i = 0; i <= arc; i++) {
      const float ang = base + (float(M_PI) * 0.5f) * (float(i) / float(arc));
      const float cs = std::cos(ang);
      const float sn = std::sin(ang);
      nrm[n][0] = cs;
      nrm[n][1] = sn;
      rim[n][0] = cx[corner] + cs * r;
      rim[n][1] = cy[corner] + sn * r;
      n++;
    }
  }

  auto sample = [&](const float px, const float py, float out[4]) {
    float t = ((px - a[0]) * abx + (py - a[1]) * aby) / len_sq;
    t = std::clamp(t, 0.0f, 1.0f);
    for (int i = 0; i < 4; i++) {
      out[i] = c0[i] + (c1[i] - c0[i]) * t;
    }
  };

  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  const uint col = GPU_vertformat_attr_add(
      format, "color", blender::gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);

  /* The feather only reads as a ramp under alpha blending; callers that paint
   * an opaque bed first (the pill) would otherwise write the zero-alpha outer
   * ring straight into the framebuffer. */
  const GPUBlend blend_prev = GPU_blend_get();
  if (aa > 0.0f) {
    GPU_blend(GPU_BLEND_ALPHA);
  }

  immBegin(GPU_PRIM_TRI_FAN, n + 2);
  float c[4];
  const float mid_x = (x0 + x1) * 0.5f;
  const float mid_y = (y0 + y1) * 0.5f;
  sample(mid_x, mid_y, c);
  immAttr4fv(col, c);
  immVertex2f(pos, mid_x, mid_y);
  for (int i = 0; i < n; i++) {
    sample(rim[i][0], rim[i][1], c);
    immAttr4fv(col, c);
    immVertex2f(pos, rim[i][0] - nrm[i][0] * aa, rim[i][1] - nrm[i][1] * aa);
  }
  /* Close the fan back onto its first rim vertex. */
  sample(rim[0][0], rim[0][1], c);
  immAttr4fv(col, c);
  immVertex2f(pos, rim[0][0] - nrm[0][0] * aa, rim[0][1] - nrm[0][1] * aa);
  immEnd();

  if (aa > 0.0f) {
    immBegin(GPU_PRIM_TRI_STRIP, (n + 1) * 2);
    for (int i = 0; i <= n; i++) {
      const int k = (i == n) ? 0 : i;
      sample(rim[k][0], rim[k][1], c);
      immAttr4fv(col, c);
      immVertex2f(pos, rim[k][0] - nrm[k][0] * aa, rim[k][1] - nrm[k][1] * aa);
      const float fade[4] = {c[0], c[1], c[2], 0.0f};
      immAttr4fv(col, fade);
      immVertex2f(pos, rim[k][0] + nrm[k][0] * aa, rim[k][1] + nrm[k][1] * aa);
    }
    immEnd();
  }

  immUnbindProgram();

  if (aa > 0.0f) {
    GPU_blend(blend_prev);
  }
}

/**
 * The card's border, drawn as a credits meter.
 *
 * A full bright ring means a full allowance; as credits are spent the lit part
 * retreats and the spent part is drawn in a dim green, so the border reads as a
 * percentage strip running around the card rather than as decoration.
 *
 * The ring starts at the top-left corner and runs CLOCKWISE. That start point
 * is deliberate: it is the corner the eye already goes to, so the gap opens
 * where it is legible instead of behind the chip row.
 *
 * `remaining` outside [0,1] means "unknown" and draws the ring whole — an
 * empty-looking border on an account whose balance simply has not loaded yet
 * would read as a rendering bug, not as information.
 */
void draw_card_border_meter(const rctf *rect,
                            const float radius,
                            const float width,
                            const float lit[4],
                            const float spent[4],
                            const float remaining)
{
  if (remaining < 0.0f || remaining >= 1.0f) {
    fill_round(rect, radius, lit);
    return;
  }

  /* Perimeter walked as four straight runs; the corner arcs are short enough at
   * this radius that folding them into the adjacent runs is imperceptible, and
   * it keeps the meter's arithmetic to one dimension. */
  const float w = BLI_rctf_size_x(rect);
  const float h = BLI_rctf_size_y(rect);
  const float total = (w + h) * 2.0f;
  const float lit_len = total * remaining;

  fill_round(rect, radius, spent);

  /* Each run is (start distance along the perimeter, length, rect builder). */
  struct Run {
    float len;
    int axis; /* 0 = along the top, 1 = down the right, 2 = along the bottom, 3 = up the left */
  };
  const Run runs[4] = {{w, 0}, {h, 1}, {w, 2}, {h, 3}};

  float walked = 0.0f;
  for (const Run &run : runs) {
    if (walked >= lit_len) {
      break;
    }
    const float take = std::min(run.len, lit_len - walked);
    const float t = take / run.len;
    rctf seg;
    switch (run.axis) {
      case 0: /* top, left -> right */
        seg.xmin = rect->xmin;
        seg.xmax = rect->xmin + w * t;
        seg.ymin = rect->ymax - width;
        seg.ymax = rect->ymax;
        break;
      case 1: /* right, top -> bottom */
        seg.xmin = rect->xmax - width;
        seg.xmax = rect->xmax;
        seg.ymin = rect->ymax - h * t;
        seg.ymax = rect->ymax;
        break;
      case 2: /* bottom, right -> left */
        seg.xmin = rect->xmax - w * t;
        seg.xmax = rect->xmax;
        seg.ymin = rect->ymin;
        seg.ymax = rect->ymin + width;
        break;
      default: /* left, bottom -> top */
        seg.xmin = rect->xmin;
        seg.xmax = rect->xmin + width;
        seg.ymin = rect->ymin;
        seg.ymax = rect->ymin + h * t;
        break;
    }
    fill_round(&seg, width * 0.5f, lit);
    walked += take;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Text helpers
 *
 * `chat_ui_draw_label` positions by baseline. The island positions almost
 * everything by optical centre instead, so these measure first. Measuring is
 * cheap next to the alternative: the account card learned the hard way that
 * BLF clips without an ellipsis, so a label that outgrows its slot vanishes
 * mid-word with no runtime signal at all.
 * \{ */

int island_font()
{
  return BLF_default();
}

float text_width(const char *text, const float size)
{
  const int font = island_font();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}

/** Draw \a text with its left edge at \a x and its ink centred on \a cy. */
void label_left(const char *text, const float x, const float cy, const float size,
                const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  const int font = island_font();
  BLF_size(font, size);
  /* Blender's widget text pass sets BLF_CLIPPING on the default font and does
   * not always leave it off. Any label drawn afterwards — the placeholder is
   * drawn after the uiBlocks on purpose — then gets clipped to that widget's
   * rect and vanishes silently, which is exactly how it presents: no error,
   * no glyphs. Clear it before every island label. */
  BLF_disable(font, BLF_CLIPPING);

  rcti box;
  BLF_boundbox(font, text, strlen(text), &box);
  const float baseline = cy - float(box.ymin + box.ymax) * 0.5f;

  BLF_color4fv(font, col);
  BLF_position(font, x, baseline, 0.0f);
  BLF_draw(font, text, strlen(text));
}

/** Draw \a text centred on (cx, cy). */
void label_centre(const char *text, const float cx, const float cy, const float size,
                  const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  label_left(text, cx - text_width(text, size) * 0.5f, cy, size, col);
}

/** Draw \a text with its right edge at \a x. */
void label_right(const char *text, const float x, const float cy, const float size,
                 const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  label_left(text, x - text_width(text, size), cy, size, col);
}

/** \} */

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Island
 * \{ */

void agent_ui_draw_status_pill(ARegion *region, const float width,
                               const float height,
                               const AgentIslandState *state)
{
  /* Sized from the WINDOW, not the region: the pill's header region comes back
   * taller than the window it lives in, and centring on the region's height
   * put the label and dot above the visible area while the corner radius blew
   * out into a huge arc. */
  const float w = width;
  const float h = height;
  if (w <= 0.0f || h <= 0.0f) {
    return;
  }

  /* ELONGATED resting pill (aspect says which window shape this is): the
   * minimised bubble's whole identity — dim last-prompt preview + Mixie the
   * cat on a green gradient chip (Frame 1533210248.svg, mascot in
   * agent_ui_pill_cat.cc). When working (busy or active queue jobs), it
   * shows a glowing green pulse animation, animated activity dot, and
   * moving progress dots on the status label. Clicking it expands the
   * island; dragging it moves it (the pill gesture in
   * agent_bubble/ui/operators/bubble_header_drag_op.py). */
  if (w > h * 4.0f) {
    const float u = h / 85.0f; /* design pill is 85 artboard units tall */
    const bool is_working = mixie_cat_is_working(state->cat_activity);
    const double now = BLI_time_now_seconds();
    const float pulse = is_working ?
                            (0.5f + 0.5f * float(std::sin(now * 3.2))) :
                            0.0f;

    rctf pill;
    pill.xmin = 0.0f;
    pill.xmax = w;
    pill.ymin = 0.0f;
    pill.ymax = h;
    const float grad_top[4] = {0.176f, 0.176f, 0.176f, 1.0f};    /* #2D2D2D */
    const float grad_bottom[4] = {0.075f, 0.078f, 0.075f, 1.0f}; /* #131413 */
    GPU_blend(GPU_BLEND_NONE);
    const float pill_grad_a[2] = {w * 0.985f, h};
    const float pill_grad_b[2] = {w * 0.947f, 0.0f};
    fill_round_gradient(&pill, h * 0.5f, grad_top, grad_bottom, pill_grad_a, pill_grad_b);
    GPU_blend(GPU_BLEND_ALPHA);

    if (is_working) {
      /* Breathing glow, INSIDE the edge and under the rim.
       *
       * It used to be the capsule inflated by three units. The pill's window
       * IS the capsule — that is what makes its corners transparent and its
       * hit area exact — so every pixel of an outset halo fell outside the
       * window and was clipped. Measured on the running app: the capsule
       * occupies the same rows in the idle frame and in every busy frame, and
       * the pixel immediately outside it is bare background in all of them.
       * The draw could not produce a pixel, and ran on every frame of every
       * turn to do it. Growing the window is not an option (its size is the
       * seat geometry the pill is anchored and dragged by), so the glow
       * breathes inward. */
      rctf glow = pill;
      const float glow_pad = 3.0f * u;
      glow.xmin += glow_pad;
      glow.ymin += glow_pad;
      glow.xmax -= glow_pad;
      glow.ymax -= glow_pad;
      const float glow_col[4] = {0.0f, 1.0f, 0.549f, 0.05f + 0.10f * pulse};
      outline_round(&glow, (h * 0.5f) - glow_pad, glow_col);

      /* Pulsing animated green rim. */
      const float rim_work[4] = {
          0.10f * (1.0f - pulse),
          1.0f,
          0.549f * pulse + 0.294f * (1.0f - pulse),
          0.30f + 0.35f * pulse};
      outline_round(&pill, h * 0.5f, rim_work);
    }
    else {
      /* Faint rim, brightest toward the top-right like the export's stroke. */
      const float rim[4] = {1.0f, 1.0f, 1.0f, 0.14f};
      outline_round(&pill, h * 0.5f, rim);
    }

    /* Pill behind the logo, right-inset 10.5 units, 85x68. */
    rctf chip;
    chip.xmax = w - 10.5f * u;
    chip.xmin = chip.xmax - 85.0f * u;
    chip.ymin = h * 0.5f - 34.0f * u;
    chip.ymax = h * 0.5f + 34.0f * u;
    const float chip_a[4] = {
        0.125f + (is_working ? 0.05f * pulse : 0.0f),
        0.345f + (is_working ? 0.25f * pulse : 0.0f),
        0.212f + (is_working ? 0.15f * pulse : 0.0f),
        1.0f};
    const float chip_b[4] = {
        0.227f + (is_working ? 0.05f * pulse : 0.0f),
        0.518f + (is_working ? 0.35f * pulse : 0.0f),
        0.341f + (is_working ? 0.20f * pulse : 0.0f),
        1.0f};
    /* Pill behind the logo: right-inset 10.5 units, 85x68. Corner radius matches
     * the minimized bubble capsule (half-height pill radius, concentric with the
     * outer pill). */
    const float chip_r = (chip.ymax - chip.ymin) * 0.5f;
    const float chip_grad_a[2] = {chip.xmax - 7.0f * u, chip.ymax - 14.0f * u};
    const float chip_grad_b[2] = {chip.xmin + 2.0f * u, chip.ymin + 30.0f * u};
    fill_round_gradient(&chip, chip_r, chip_a, chip_b, chip_grad_a, chip_grad_b);

    if (is_working) {
      /* Animated glowing rim around the chip. */
      const float chip_rim[4] = {0.0f, 1.0f, 0.549f, 0.25f + 0.35f * pulse};
      outline_round(&chip, chip_r, chip_rim);
    }

    const MixieCatPose cat_pose = agent_ui_cat_motion_sample(
        region, state->cat_activity, now, state->cat_scene);
    agent_ui_draw_pill_cat(&chip, cat_pose, state->cat_activity);

    /* Preview line: newest user prompt, dim, ellipsised into the space left
     * of the chip. */
    char preview[160];
    BLI_strncpy(preview,
                state->last_prompt[0] ? state->last_prompt : "Ask Mixie anything...",
                sizeof(preview));
    /* One line only — newlines read as garbage glyphs in BLF. */
    for (char *c = preview; *c; c++) {
      if (*c == '\n' || *c == '\r') {
        *c = ' ';
      }
    }
    const float text_size = 27.0f * u;
    const float text_x = 28.0f * u;

    if (is_working) {
      /* Pulsing indicator dot on the left. */
      const float dot_cx = text_x + 5.0f * u;
      const float dot_cy = h * 0.5f;
      const float dot_r = 4.5f * u;

      /* Ripple ring around the dot. */
      const float rip_r = dot_r + 3.5f * u * pulse;
      rctf ripple;
      ripple.xmin = dot_cx - rip_r;
      ripple.xmax = dot_cx + rip_r;
      ripple.ymin = dot_cy - rip_r;
      ripple.ymax = dot_cy + rip_r;
      const float rip_col[4] = {0.0f, 1.0f, 0.549f, (1.0f - pulse) * 0.45f};
      fill_round(&ripple, rip_r, rip_col);

      /* Solid active dot. */
      rctf dot;
      dot.xmin = dot_cx - dot_r;
      dot.xmax = dot_cx + dot_r;
      dot.ymin = dot_cy - dot_r;
      dot.ymax = dot_cy + dot_r;
      const float dot_col[4] = {0.0f, 1.0f, 0.549f, 0.95f};
      fill_round(&dot, dot_r, dot_col);

      /* Trailing dots animation: 0, 1, 2, 3 dots on a 1.6s cycle. */
      const int dot_count = int(fmod(now * 2.5, 4.0));
      char dots[5] = "";
      for (int i = 0; i < dot_count; i++) {
        dots[i] = '.';
      }
      dots[dot_count] = '\0';

      const char *base_status = (state->queue_count > 0 && !state->status_busy) ?
                                    "Generating" :
                                    "Working";
      char label[160];
      if (state->last_prompt[0] != '\0') {
        SNPRINTF(label, "%s%s · %s", base_status, dots, preview);
      }
      else {
        SNPRINTF(label, "%s%s", base_status, dots);
      }

      const float label_x = dot_cx + dot_r + 10.0f * u;
      const float text_max_w = chip.xmin - 16.0f * u - label_x;
      if (text_width(label, text_size) > text_max_w) {
        size_t len = strlen(label);
        while (len > 1) {
          label[--len] = '\0';
          char probe[164];
          SNPRINTF(probe, "%s...", label);
          if (text_width(probe, text_size) <= text_max_w) {
            BLI_strncpy(label, probe, sizeof(label));
            break;
          }
        }
      }
      const float work_col[4] = {0.95f, 0.96f, 0.98f, 1.0f};
      label_left(label, label_x, h * 0.5f, text_size, work_col);
    }
    else {
      const float text_max_w = chip.xmin - 16.0f * u - text_x;
      const float dim_col[4] = {0.62f, 0.62f, 0.62f, 1.0f};
      if (text_width(preview, text_size) > text_max_w) {
        size_t len = strlen(preview);
        while (len > 1) {
          preview[--len] = '\0';
          char probe[164];
          SNPRINTF(probe, "%s...", preview);
          if (text_width(probe, text_size) <= text_max_w) {
            BLI_strncpy(preview, probe, sizeof(preview));
            break;
          }
        }
      }
      label_left(preview, text_x, h * 0.5f, text_size, dim_col);
    }

    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  agent_ui_pill_cat_clear();

  const float surface[4] = AGENT_COL_SURFACE;
  const float accent[4] = AGENT_COL_ACCENT;
  const float dim_dot[4] = {0.076f, 0.219f, 0.132f, 1.0f};
  const float text_dim[4] = AGENT_COL_TEXT_DIM;

  /* The pill owns its whole window, so it is drawn from the region's size
   * rather than the artboard's rect — the window is sized to the artboard's
   * 135x38 and the proportions inside are kept. */
  rctf pill;
  pill.xmin = 0.0f;
  pill.xmax = w;
  pill.ymin = 0.0f;
  pill.ymax = h;

  /* The pill's own unit — its window is force-sized independently of the
   * island, so it carries neither `layout->scale` nor UI_SCALE_FAC's ratio. */
  const float pill_u = h / float(AGENT_PILL_H);
  const float dot_r = AGENT_PILL_DOT_R * pill_u;
  const float dot_cx = w * (float(AGENT_PILL_DOT_CX - AGENT_PILL_X) / float(AGENT_PILL_W));
  rctf dot;
  dot.xmin = dot_cx - dot_r;
  dot.xmax = dot_cx + dot_r;
  dot.ymin = h * 0.5f - dot_r;
  dot.ymax = h * 0.5f + dot_r;

  /* Paint the WHOLE rect opaquely before the capsule. The pill window's
   * buffers otherwise carry transparent pixels that composite as the bare
   * window backdrop — a flat grey that flashed against the capsule whenever a
   * stale buffer was presented. The OS-level corner mask still rounds the
   * window, so the corners never show this fill. */
  const float bed_a = agent_bubble_pill_bed_is_transparent() ? 0.0f : 1.0f;
  const float bed[4] = {0.02f, 0.02f, 0.02f, bed_a};
  GPU_blend(GPU_BLEND_NONE);
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&pill, true, 0.0f, bed);

  GPU_blend(GPU_BLEND_ALPHA);
  fill_round(&pill, h * 0.5f, surface);
  fill_round(&dot, dot_r, state->status_busy ? accent : dim_dot);
  label_left(state->status_text,
             w * (float(AGENT_PILL_LABEL_X - AGENT_PILL_X) / float(AGENT_PILL_W)),
             h * 0.5f,
             AGENT_PILL_FONT * pill_u,
             text_dim);
  GPU_blend(GPU_BLEND_NONE);
}

void agent_ui_draw_island(ARegion *region,
                          const AgentIslandLayout *layout,
                          const AgentIslandState *state)
{
  agent_ui_motion_begin(region);
  if (!layout->valid) {
    agent_ui_motion_end(region);
    return;
  }

  const float u = layout->scale;

  const float surface[4] = AGENT_COL_SURFACE;
  const float border[4] = AGENT_COL_BORDER;
  const float card_top[4] = AGENT_COL_CARD_TOP;
  const float card_bottom[4] = AGENT_COL_CARD_BOTTOM;
  const float accent[4] = AGENT_COL_ACCENT;
  const float glyph[4] = AGENT_COL_GLYPH;
  const float text[4] = AGENT_COL_TEXT;
  const float strong[4] = AGENT_COL_TEXT_STRONG;
  const float text_dim[4] = AGENT_COL_TEXT_DIM;

  GPU_blend(GPU_BLEND_ALPHA);

  /* The status pill is NOT drawn here — it is its own always-on-top window
   * (see agent_ui_draw_status_pill). Drawing it in the island meant a band of
   * opaque black above the tab strip, because the bubble window composites
   * alpha as opaque. */

  /* --- Tab strip --- (none on the Scribble pad; its rects are empty) */
  if (!layout->pad) {
    agent_ui_draw_tab_strip(region, layout, state);
  }

  /* --- Card --- */
  {
    /* Spent portion: the same hue at a fraction of its value, so the ring reads
     * as one strip that has been used up rather than two different borders. */
    const float border_spent[4] = {border[0] * 0.16f, border[1] * 0.16f,
                                   border[2] * 0.16f, 1.0f};
    draw_card_border_meter(&layout->card,
                           AGENT_CARD_RADIUS * u,
                           AGENT_CARD_BORDER * u,
                           border,
                           border_spent,
                           state->credits_remaining);
  }
  fill_round_gradient(&layout->card_fill,
                      AGENT_CARD_RADIUS * u,
                      card_top,
                      card_bottom,
                      layout->card_grad_a,
                      layout->card_grad_b);

  /* Card header row is tab-scoped: the chat's discs / session title / FAQs
   * belong to the Agent tab; other tabs title the card after themselves. */
  const bool agent_tab = layout->tabs[AGENT_TAB_AGENT].active;
  if (agent_tab) {
    /* Header buttons: an accent disc with a lighter glyph on top. */
    float history_fill[4], new_chat_fill[4];
    agent_ui_motion_color(accent, accent,
                          agent_ui_motion_sample(region, AgentIslandControl::History, layout->hdr_history),
                          history_fill);
    agent_ui_motion_color(accent, accent,
                          agent_ui_motion_sample(region, AgentIslandControl::NewChat, layout->hdr_new_chat),
                          new_chat_fill);
    fill_round(&layout->hdr_history,
               BLI_rctf_size_x(&layout->hdr_history) * 0.5f,
               history_fill);
    agent_ui_icon_draw(AGENT_ICON_CLOCK, &layout->hdr_history, glyph, history_fill);

    fill_round(&layout->hdr_new_chat,
               BLI_rctf_size_x(&layout->hdr_new_chat) * 0.5f,
               new_chat_fill);
    agent_ui_icon_draw(AGENT_ICON_PLUS, &layout->hdr_new_chat, glyph, new_chat_fill);

    if (state->ink_visible) {
      /* Scribble text output window over the new chat topbar */
      const float left_limit = layout->hdr_new_chat.xmax + 16.0f * u;
      const float right_limit = layout->hdr_faq.xmin - 16.0f * u;
      const float max_w = right_limit - left_limit;
      const float cx = layout->hdr_title_cx;
      const float cy = layout->hdr_title_y;
      const float win_h = 42.0f * u;

      char disp[512];
      BLI_strncpy(disp,
                  state->input_text[0] ? state->input_text : "Scribble to type...",
                  sizeof(disp));
      for (char *c = disp; *c; c++) {
        if (*c == '\n' || *c == '\r') {
          *c = ' ';
        }
      }

      const float font_size = 18.0f * u;
      const float text_w = text_width(disp, font_size);
      const float pad_x = 18.0f * u;
      const float win_w = std::clamp(text_w + pad_x * 2.0f, 220.0f * u, max_w);

      rctf text_win;
      text_win.xmin = cx - win_w * 0.5f;
      text_win.xmax = cx + win_w * 0.5f;
      text_win.ymin = cy - win_h * 0.5f;
      text_win.ymax = cy + win_h * 0.5f;

      const float win_bg[4] = {0.05f, 0.05f, 0.07f, 0.90f};
      const float win_border[4] = {0.20f, 0.52f, 0.32f, 0.70f};
      fill_round(&text_win, 14.0f * u, win_bg);
      outline_round(&text_win, 14.0f * u, win_border);

      const float max_text_w = win_w - pad_x * 2.0f;
      if (text_width(disp, font_size) > max_text_w) {
        size_t len = strlen(disp);
        while (len > 1) {
          disp[--len] = '\0';
          char probe[516];
          SNPRINTF(probe, "%s...", disp);
          if (text_width(probe, font_size) <= max_text_w) {
            BLI_strncpy(disp, probe, sizeof(disp));
            break;
          }
        }
      }

      const float col_active[4] = {0.96f, 0.97f, 0.98f, 1.0f};
      const float col_dim[4] = {0.50f, 0.50f, 0.50f, 0.80f};
      const float *text_col = state->input_text[0] ? col_active : col_dim;
      label_centre(disp, cx, cy, font_size, text_col);
    }
    else {
      label_centre(state->title,
                   layout->hdr_title_cx,
                   layout->hdr_title_y,
                   AGENT_HDR_TITLE_FONT * u,
                   strong);
    }
    label_right("FAQs",
                layout->hdr_faq.xmax,
                BLI_rctf_cent_y(&layout->hdr_faq),
                AGENT_HDR_FAQ_FONT * u,
                strong);
  }
  else {
    const char *tab_title = "";
    if (layout->tabs[AGENT_TAB_QUEUE].active) {
      tab_title = "Queue";
    }
    else if (layout->tabs[AGENT_TAB_3D].active) {
      tab_title = "3D";
    }
    else if (layout->tabs[AGENT_TAB_MEDIA].active) {
      tab_title = "Media";
    }
    else if (layout->tabs[AGENT_TAB_SPLAT].active) {
      tab_title = "Gaussian Splat";
    }
    else if (layout->tabs[AGENT_TAB_GENERATIONS].active) {
      tab_title = "My Generations";
    }
    label_centre(tab_title,
                 layout->hdr_title_cx,
                 layout->hdr_title_y,
                 AGENT_HDR_TITLE_FONT * u,
                 strong);
  }

  /* --- Inner panel --- */
  fill_round(&layout->panel, AGENT_PANEL_RADIUS * u, surface);

  /* Neither the prompt nor its placeholder is painted here — both belong to
   * the text button the bottom slab lays over the input line, which draws on
   * top of anything the painter puts in the same place. Painting one here as
   * well is what put TWO ghost texts in the card. */

  /* --- Chip row --- */
  agent_ui_draw_chip_row(region, layout, state);
  agent_ui_motion_end(region);

  GPU_blend(GPU_BLEND_NONE);
}

/** \} */

}  // namespace blender
