/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar liquid glass: one drawing kit for every Mixar surface that floats over
 * other content — the agent island, its card and status pill, the viewport
 * agent panel's cards, the Mixar profile cards, menus and popovers, and the
 * Mixie chat.
 *
 * A pane is a tinted silhouette with a soft top gloss and a 1px rim. Where
 * the caller can hand in a blurred backdrop the pane also gets a refraction
 * wash and a travelling specular streak — lighting that needs a frosted bed
 * to catch it. Where it cannot (every Mixar surface today), those two layers
 * stay off and the shape, the rim and the gloss carry the material, so a
 * tinted pane is not dirtied by a diagonal bevel and a sweeping bar.
 *
 * WHY THE BACKDROP IS A CALLER-SUPPLIED TEXTURE
 * The kit can blur a texture, but it cannot capture one. This overlay has no
 * framebuffer-readback path at all (`GPU_framebuffer_blit`,
 * `GPU_texture_copy` and `GPU_framebuffer_read_color` do not exist anywhere in
 * the tree), so nothing can sample what has already been drawn under an
 * arbitrary rect. The one backdrop that IS reachable is a re-render of the 3D
 * viewport into an offscreen, which only the viewport agent panel can do —
 * and it is the panel that owns that offscreen, so it is the panel that hands
 * the texture in. Every other surface passes an empty #MixarGlassSource and
 * gets the tinted pane. The kit never invents a backdrop it cannot get, and
 * `MixarGlassSource{}` is an ordinary, expected input rather than a failure.
 *
 * WHY THE ROLES ARE ENUMERATED
 * The surfaces differ only in palette and in how hard the blur runs, so they
 * are table entries rather than call-site arguments: a surface cannot drift
 * out of the family by passing a slightly different tint, and re-toning the
 * whole UI is one table edit.
 *
 * COORDINATES
 * Everything is region-local px, in the space the caller has already set up
 * (`ED_region_pixelspace`, or a pushed translate for window-space callers).
 * `MixarGlassSource::rect` and the pane rect must share that one space.
 * Callers that draw in window px (the agent bubble pushes
 * `-region->winrct.xmin`) must offset both rects alike.
 */

#pragma once

#include "BLI_rect.h"

namespace blender {
namespace gpu {
class Texture;
}  // namespace gpu

namespace ui {

/**
 * Which surface a pane belongs to. The role picks the palette and the blur
 * strength; nothing else about the drawing depends on it.
 */
enum eMixarGlassRole {
  /** Agent island card, profile cards — the largest panes. */
  MIXAR_GLASS_CARD,
  /** Context menus and popovers over the viewport. */
  MIXAR_GLASS_MENU,
  /** The viewport agent panel's column and its cards. */
  MIXAR_GLASS_PANEL,
  /** The agent island's own backdrop, and Zen topbar / View3D headers. */
  MIXAR_GLASS_ISLAND,
  /** The status pill and its queue badge — smallest radii, neutral tint. */
  MIXAR_GLASS_PILL,
  /** The Mixie chat's bubbles and composer. */
  MIXAR_GLASS_CHAT,
  /** Chips and buttons sitting on a pane: tint, rim, whisper of gloss;
   * no shadow and no specular (must not cast over the host pane). */
  MIXAR_GLASS_CHIP,
  /** The Mixie moodboard's nodes, media frames and floating panels. */
  MIXAR_GLASS_MOODBOARD,
};

/**
 * The palette and metrics of one pane.
 *
 * Every colour states its alpha explicitly: a three-value initialiser
 * zero-fills the fourth and the shape draws invisible (the failure that reads
 * as "the button is missing"). The table carries design px and the accessor
 * scales it, so the numbers here stay comparable to the artboard.
 */
struct MixarGlassTokens {
  /** Bed ramp, top edge to bottom edge, over the backdrop. */
  float tint_top[4];
  float tint_bottom[4];
  /** Unifying wash drawn over a blurred bed; unused with no backdrop. */
  float glaze[4];
  /** Top-edge gloss, fading to the pane's own alpha. */
  float sheen[4];
  /** 1px rim. */
  float rim[4];
  /** Diagonal wash inside the rim: lighter at the top-left. */
  float refract[4];
  /** Drop shadow, drawn under the pane. */
  float shadow[4];
  float radius;
  float rim_width;
  /** Backdrop blur in px. 0 disables blur even when a backdrop is handed in. */
  float blur_radius;
  /** Drop-shadow spread in px. Read only when `shadow[3] > 0`. */
  float shadow_width;
  float sheen_height;
  float specular_width;
  float specular_alpha;
  /** Seconds for the specular streak to cross the pane once. */
  float specular_period;
};

/** Tokens for `role`, metrics already scaled by `UI_SCALE_FAC`. */
MixarGlassTokens mixar_glass_tokens(eMixarGlassRole role);

/**
 * A backdrop the caller already has, in the caller's coordinate space.
 *
 * An empty source (`texture == nullptr`) is valid and common: it means this
 * surface has no reachable backdrop and the kit should draw a tinted pane.
 */
struct MixarGlassSource {
  gpu::Texture *texture = nullptr;
  int width = 0;
  int height = 0;
  /** Region-local px the texture covers. */
  rcti rect = {};

  bool valid() const
  {
    return this->texture != nullptr && this->width > 0 && this->height > 0 &&
           BLI_rcti_size_x(&this->rect) > 0 && BLI_rcti_size_y(&this->rect) > 0;
  }
};

/** A blurred backdrop, owned by the kit until the next prepare or free. */
struct MixarGlassBackdrop {
  gpu::Texture *texture = nullptr;
  rcti rect = {};

  bool valid() const
  {
    return this->texture != nullptr && BLI_rcti_size_x(&this->rect) > 0 &&
           BLI_rcti_size_y(&this->rect) > 0;
  }
};

/**
 * Blur `source` and return the result, or an empty backdrop if there is
 * nothing to blur or the blur chain could not be allocated.
 *
 * Prepare ONCE per redraw and pass the result to every pane over the same
 * backdrop: the chain is shared, so a second prepare at a different size
 * rebuilds it and invalidates the texture the first call returned.
 */
MixarGlassBackdrop mixar_glass_backdrop_prepare(const MixarGlassSource &source, float blur_radius);

/** How to draw one pane. */
struct MixarGlassStyle {
  eMixarGlassRole role = MIXAR_GLASS_CARD;
  /** Px. `< 0` uses the role's radius. */
  float radius = -1.0f;
  /** Multiplied into every layer, so a stuck border reads before it vanishes. */
  float alpha = 1.0f;
  /** Panes on a viewport need one; panes on another pane do not. */
  bool draw_shadow = false;
  bool draw_specular = true;
};

/**
 * Draw one pane. Saves and restores the blend mode and the matrix around
 * itself, so a caller may draw a pane mid-pass.
 */
void mixar_glass_draw(const rcti &rect,
                      const MixarGlassStyle &style,
                      const MixarGlassBackdrop &backdrop = {});

/**
 * Ask the window manager for a translucent window.
 *
 * On macOS and Windows this is what lets a surface that IS its own window (the
 * island, the pill) show anything behind it at all; elsewhere — and on Linux
 * in this checkout, which has no definition of the underlying call — it is a
 * no-op returning false, so callers need no `#ifdef` of their own.
 *
 * This is window-level compositing. On macOS `Mixar_WindowSetBlurBehind`
 * installs AppKit frost as a sibling behind GHOST's Metal view (never as
 * its parent) and lets this window's `CAMetalLayer` composite alpha. The
 * Metal present blit must keep the framebuffer's alpha — forcing it to 1
 * makes the drawable an opaque slab over that sibling. An EDR
 * `RGBA16Float` layer is still composited opaque, so the installer
 * switches that window's `CAMetalLayer` to `BGRA8Unorm` and GHOST
 * rebuilds the present pipeline to match, premultiplying RGB so
 * WindowServer does not treat A=0 as an opaque slab. The flip is
 * re-applied on present while the window is non-opaque. The draw
 * overlay stays `RGBA16Float`. Island region beds clear then REPLACE
 * a wash (`GPU_BLEND_NONE`); dest-over cannot lower dest A=1 and an
 * A=0 fragment does not land on Metal. On Windows `Mixar_WindowSetBlurBehind`
 * installs Desktop Acrylic (Win11) plus a full-window DWM blur-behind, and
 * asks DWM to honour the redirection bitmap's alpha. A pane over such a
 * window still needs the kit's own tint; the painter keeps refraction and
 * the streak off when no GPU backdrop is handed in.
 *
 * \return true if the platform acted on the request.
 */
bool mixar_glass_window_apply_translucency(void *ghostwin, bool enable);

/** Release the shared blur chain. Safe to call at any time. */
void mixar_glass_free();

}  // namespace ui
}  // namespace blender
