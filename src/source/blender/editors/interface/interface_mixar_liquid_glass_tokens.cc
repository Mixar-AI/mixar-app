/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar liquid glass: the material table behind `ED_mixar_glass.hh`. Read that
 * header first — it states what a pane is made of and why the surfaces are a
 * table rather than call-site arguments. The blur and the window request are
 * in `interface_mixar_liquid_glass.cc`; the painter is
 * `interface_mixar_liquid_glass_draw.cc`.
 *
 * This file is separate because a row per surface is prose-heavy: the numbers
 * are the material, and the comments beside them are the only record of which
 * call-site colour each one stands in for. That is enough text to push the kit
 * past the repo's file-size limit on its own, and the table has no GPU calls
 * in it, so it is also the cleanest seam in the module.
 */

#include <algorithm>

#include "BLI_utildefines.h"

#include "DNA_theme_types.h"
#include "DNA_userdef_types.h"

#include "ED_mixar_glass.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {
namespace ui {

namespace {

/* -------------------------------------------------------------------- */
/** \name Tokens
 * \{ */

/**
 * Design px, alphas explicit on every colour.
 *
 * A three-value initialiser zero-fills the fourth and the shape draws
 * invisible — the failure reads as "the button is missing", not as a colour
 * bug — so every entry spells its alpha out even when it is 0.
 *
 * These are the TRANSLUCENT variants and the material metrics; neither the
 * opaque design-system palette (`interface_mixar_palette.hh`) nor the island's
 * pane vocabulary (`agent_ui_pane_kit.hh`) carries an alpha ramp, a rim, a
 * sheen, a specular or a shadow, and a material cannot be assembled out of
 * opaque chips. The RGBs are those tables' colours where a pane has an opaque
 * counterpart: CARD and ISLAND take the agent surface's near-black with a
 * whisper of green (the artboard's saturated green ramp as a *glass tint*
 * read as a plastic header; the neon meter is the card's green), MENU, CHAT
 * and MOODBOARD the neutral dark surfaces, PANEL the Parallel Agents card's
 * own near-black bed with that card's resting border green as its rim (the
 * card's green wash is painted at its call site: it is a horizontal ramp, and
 * this row's bed is vertical), PILL the brand green with the brightest rim in
 * the family (it is the smallest pane, so the rim is most of what identifies
 * it), CHIP tint + rim + a whisper of gloss (no shadow, no specular), so it
 * can sit on a pane without casting its own material.
 *
 * `PILL.radius` is deliberately larger than any pill: the painter clamps a
 * radius to half the short side, which is exactly the capsule rule, so one
 * number covers every pill height (the same 999 as the palette's
 * `MX_R_PILL`).
 */
const MixarGlassTokens g_glass_tokens[] = {
    /* MIXAR_GLASS_CARD — dark glass, not the artboard's saturated green ramp.
     * That ramp as a pane tint plus the sheen read as a plastic header; the
     * controls already carry the green. A whisper of green in the
     * bed keeps it in the family without flooding the card. */
    {
        /* tint_top      */ {0.090f, 0.120f, 0.100f, 0.16f},
        /* tint_bottom   */ {0.040f, 0.055f, 0.048f, 0.24f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.22f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.07f},
        /* rim           */ {0.294f, 0.596f, 0.376f, 0.22f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.10f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.40f},
        /* radius        */ 12.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 18.0f,
        /* shadow_width  */ 8.0f,
        /* sheen_height  */ 12.0f,
        /* specular_width*/ 26.0f,
        /* specular_alpha*/ 0.10f,
        /* specular_period*/ 6.0f,
        /* fallback_alpha */ 0.82f,
    },
    /* MIXAR_GLASS_MENU */
    {
        /* tint_top      */ {0.086f, 0.086f, 0.090f, 0.88f},
        /* tint_bottom   */ {0.047f, 0.047f, 0.051f, 0.94f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.22f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.07f},
        /* rim           */ {0.255f, 0.255f, 0.255f, 0.45f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.10f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.45f},
        /* radius        */ 8.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 14.0f,
        /* shadow_width  */ 7.0f,
        /* sheen_height  */ 14.0f,
        /* specular_width*/ 18.0f,
        /* specular_alpha*/ 0.06f,
        /* specular_period*/ 7.0f,
        /* fallback_alpha */ 0.94f,
    },
    /* MIXAR_GLASS_PANEL — the Parallel Agents card. Its own near-black, barely
     * lifted at the top, and the card's RESTING border green: the running
     * border is brighter and is painted at the call site, where the agent's
     * status lives — the same split the PILL row makes with its working rim.
     * The card's green wash is horizontal and stays at the call site too,
     * because this row's tint bed is a vertical ramp. */
    {
        /* tint_top      */ {0.055f, 0.071f, 0.063f, 0.66f},
        /* tint_bottom   */ {0.043f, 0.055f, 0.047f, 0.78f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.18f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.06f},
        /* rim           */ {0.180f, 0.478f, 0.278f, 0.55f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.09f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.30f},
        /* radius        */ 10.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 24.0f,
        /* shadow_width  */ 9.0f,
        /* sheen_height  */ 16.0f,
        /* specular_width*/ 22.0f,
        /* specular_alpha*/ 0.06f,
        /* specular_period*/ 8.0f,
        /* fallback_alpha */ 0.82f,
    },
    /* MIXAR_GLASS_ISLAND — same dark glass as CARD; this row is the window
     * backdrop when a surface paints the island's own chrome, not the card. */
    {
        /* tint_top      */ {0.086f, 0.110f, 0.094f, 0.16f},
        /* tint_bottom   */ {0.035f, 0.047f, 0.040f, 0.24f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.20f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.06f},
        /* rim           */ {0.294f, 0.596f, 0.376f, 0.18f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.08f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.42f},
        /* radius        */ 14.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 16.0f,
        /* shadow_width  */ 10.0f,
        /* sheen_height  */ 12.0f,
        /* specular_width*/ 28.0f,
        /* specular_alpha*/ 0.09f,
        /* specular_period*/ 6.0f,
        /* fallback_alpha */ 0.82f,
    },
    /* MIXAR_GLASS_PILL — radius clamped to half the short side, i.e. a capsule.
     * The tint is NEUTRAL, not the card's green: the resting capsule is the two
     * greys of its own artboard (#2D2D2D over #131413), so the alphas carry the
     * see-through and the hue stays grey. The rim is the pill's resting rim
     * (white at 0.14, `grad_*`'s own stroke); the WORKING rim is green and
     * pulses, so it is repainted at the call site where the pulse lives. */
    {
        /* tint_top      */ {0.176f, 0.176f, 0.176f, 0.16f},
        /* tint_bottom   */ {0.075f, 0.078f, 0.075f, 0.24f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.24f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.14f},
        /* rim           */ {1.000f, 1.000f, 1.000f, 0.14f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.20f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.38f},
        /* radius        */ 999.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 12.0f,
        /* shadow_width  */ 5.0f,
        /* sheen_height  */ 12.0f,
        /* specular_width*/ 14.0f,
        /* specular_alpha*/ 0.12f,
        /* specular_period*/ 5.0f,
        /* fallback_alpha */ 0.74f,
    },
    /* MIXAR_GLASS_CHAT */
    {
        /* tint_top      */ {0.114f, 0.114f, 0.118f, 0.80f},
        /* tint_bottom   */ {0.071f, 0.071f, 0.075f, 0.88f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.20f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.07f},
        /* rim           */ {0.255f, 0.255f, 0.255f, 0.35f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.10f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.32f},
        /* radius        */ 10.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 16.0f,
        /* shadow_width  */ 7.0f,
        /* sheen_height  */ 16.0f,
        /* specular_width*/ 20.0f,
        /* specular_alpha*/ 0.07f,
        /* specular_period*/ 7.0f,
        /* fallback_alpha */ 0.88f,
    },
    /* MIXAR_GLASS_CHIP — tint, rim and a whisper of gloss; no shadow, no
     * specular, because a chip sits ON a pane and may not cast its own. */
    {
        /* tint_top      */ {0.114f, 0.114f, 0.114f, 0.90f},
        /* tint_bottom   */ {0.114f, 0.114f, 0.114f, 0.90f},
        /* glaze         */ {0.000f, 0.000f, 0.000f, 0.00f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.05f},
        /* rim           */ {0.255f, 0.255f, 0.255f, 0.30f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.06f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.00f},
        /* radius        */ 8.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 8.0f,
        /* shadow_width  */ 0.0f,
        /* sheen_height  */ 8.0f,
        /* specular_width*/ 0.0f,
        /* specular_alpha*/ 0.00f,
        /* specular_period*/ 0.0f,
        /* fallback_alpha */ 0.90f,
    },
    /* MIXAR_GLASS_MOODBOARD — everything the Mixie moodboard floats over its
     * own canvas: inference nodes, asset cards, the media frame behind an
     * imported image and the screen-space panels. The bed is the moodboard's
     * own card grey (the panel and the node card had drifted to two slightly
     * different darks; they share this one now), and the rim is their RESTING
     * border — a SELECTED node brightens it to 0.92 and only the call site
     * knows which nodes are selected. No moving specular: graph navigation
     * already supplies motion, and its material should remain quiet. */
    {
        /* tint_top      */ {0.105f, 0.105f, 0.110f, 0.86f},
        /* tint_bottom   */ {0.078f, 0.078f, 0.082f, 0.92f},
        /* glaze         */ {0.071f, 0.071f, 0.071f, 0.20f},
        /* sheen         */ {1.000f, 1.000f, 1.000f, 0.07f},
        /* rim           */ {0.380f, 0.390f, 0.420f, 0.58f},
        /* refract       */ {1.000f, 1.000f, 1.000f, 0.10f},
        /* shadow        */ {0.000f, 0.000f, 0.000f, 0.35f},
        /* radius        */ 12.0f,
        /* rim_width     */ 1.0f,
        /* blur_radius   */ 20.0f,
        /* shadow_width  */ 8.0f,
        /* sheen_height  */ 18.0f,
        /* specular_width*/ 0.0f,
        /* specular_alpha*/ 0.00f,
        /* specular_period*/ 0.0f,
        /* fallback_alpha */ 0.92f,
    },
};

static_assert(ARRAY_SIZE(g_glass_tokens) == size_t(MIXAR_GLASS_MOODBOARD) + 1u,
              "Every role needs a row: the enum and the table are read together.");

/** \} */

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Public API
 * \{ */

MixarGlassTokens mixar_glass_tokens(const eMixarGlassRole role)
{
  const int index = std::clamp(int(role), 0, int(MIXAR_GLASS_MOODBOARD));
  MixarGlassTokens tokens = g_glass_tokens[index];
  const float scale = UI_SCALE_FAC;
  tokens.radius *= scale;
  tokens.rim_width *= scale;
  tokens.blur_radius *= scale;
  tokens.shadow_width *= scale;
  tokens.sheen_height *= scale;
  tokens.specular_width *= scale;
  /* `specular_alpha` and `specular_period` are not lengths — one is an alpha,
   * the other is seconds — so the UI scale must not touch them. */
  return tokens;
}

/** \} */

}  // namespace ui
}  // namespace blender
