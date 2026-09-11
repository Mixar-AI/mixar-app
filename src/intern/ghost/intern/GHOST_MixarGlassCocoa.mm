/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Native frost behind Mixar's island / pill windows.
 *
 * AppKit's glass (`NSGlassEffectView` on macOS 26, `NSVisualEffectView`
 * earlier) has to sit BEHIND the GPU view as a sibling in the theme frame.
 * Parenting it under CocoaMetalView or wrapping `contentView` tears
 * GHOST's Metal context. This file never does those. The host is tracked
 * with an associated object, not a view identifier.
 *
 * Transparent GPU pixels only composite over that sibling when THIS window's
 * `CAMetalLayer` is non-opaque. The flag is flipped on the island/pill layer
 * alone, never walked across the process.
 */

#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/message.h>
#import <objc/runtime.h>

#include "GHOST_MixarGlassCocoa.hh"

/* GHOST's CocoaMetalView hard-codes isOpaque=YES. AppKit then skips the
 * frost sibling and WindowServer may treat the presented drawable as a
 * solid plane. Follow the window: island/pill set opaque=NO. */
@interface MixarGlassLensView : NSView
@end

@implementation MixarGlassLensView
- (BOOL)isOpaque
{
  return NO;
}
@end

@interface CocoaMetalView : NSView
@end

@implementation CocoaMetalView (MixarTranslucency)
- (BOOL)isOpaque
{
  NSWindow *win = self.window;
  return (win == nil) ? YES : win.opaque;
}
@end

namespace {

const void *kMixarGlassKey = &kMixarGlassKey;

NSView *mixar_glass_get(NSWindow *win)
{
  return objc_getAssociatedObject(win, kMixarGlassKey);
}

void mixar_glass_set(NSWindow *win, NSView *glass)
{
  objc_setAssociatedObject(win, kMixarGlassKey, glass, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
}

void mixar_msg_set_double(id obj, const char *name, const double value)
{
  const SEL sel = sel_registerName(name);
  if ([obj respondsToSelector:sel]) {
    reinterpret_cast<void (*)(id, SEL, double)>(objc_msgSend)(obj, sel, value);
  }
}

void mixar_msg_set_llong(id obj, const char *name, const long long value)
{
  const SEL sel = sel_registerName(name);
  if ([obj respondsToSelector:sel]) {
    reinterpret_cast<void (*)(id, SEL, long long)>(objc_msgSend)(obj, sel, value);
  }
}

void mixar_give_glass_a_lens(NSView *glass)
{
  /* NSGlassEffectView frosts its contentView. An empty glass sibling is
   * a hole — Clear especially. The lens is a new NSView owned by the
   * glass, never the window contentView and never CocoaMetalView. */
  const SEL setter = sel_registerName("setContentView:");
  const SEL getter = sel_registerName("contentView");
  if (![glass respondsToSelector:setter]) {
    return;
  }
  if ([glass respondsToSelector:getter]) {
    const id existing = reinterpret_cast<id (*)(id, SEL)>(objc_msgSend)(glass, getter);
    if (existing != nil) {
      return;
    }
  }
  MixarGlassLensView *lens = [[MixarGlassLensView alloc] initWithFrame:glass.bounds];
  lens.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
  reinterpret_cast<void (*)(id, SEL, id)>(objc_msgSend)(glass, setter, lens);
  [lens release];
}

void mixar_style_glass(NSView *glass, const CGFloat radius)
{
  glass.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
  glass.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];

  mixar_msg_set_double(glass, "setCornerRadius:", double(radius));
  if (![glass respondsToSelector:sel_registerName("setCornerRadius:")]) {
    glass.wantsLayer = YES;
    glass.layer.cornerRadius = radius;
    glass.layer.masksToBounds = (radius > 0.0);
  }

  /* Regular is the liquid-glass material. Clear is an empty hole once
   * Metal pixels carry alpha. No tintColor — a dark tint is another slab. */
  mixar_msg_set_llong(glass, "setStyle:", 0);
  mixar_give_glass_a_lens(glass);
  /* Private lensing: no-op on the visual-effect fallback. */
  mixar_msg_set_llong(glass, "set_contentLensing:", 1);
}

NSView *mixar_make_glass(const NSRect frame)
{
  Class glass_cls = NSClassFromString(@"NSGlassEffectView");
  if (glass_cls != nil) {
    return [[glass_cls alloc] initWithFrame:frame];
  }

  NSVisualEffectView *visual = [[NSVisualEffectView alloc] initWithFrame:frame];
  visual.blendingMode = NSVisualEffectBlendingModeBehindWindow;
  visual.material = NSVisualEffectMaterialUnderWindowBackground;
  visual.state = NSVisualEffectStateActive;
  visual.emphasized = NO;
  return visual;
}

void mixar_set_layer_colorspace(CAMetalLayer *metal, CFStringRef name)
{
  CGColorSpaceRef colorspace = CGColorSpaceCreateWithName(name);
  metal.colorspace = colorspace;
  CGColorSpaceRelease(colorspace);
}

CAMetalLayer *mixar_metal_layer_of(NSView *host)
{
  if (host == nil) {
    return nil;
  }
  CALayer *layer = host.layer;
  if ([layer isKindOfClass:[CAMetalLayer class]]) {
    return (CAMetalLayer *)layer;
  }
  /* GHOST assigns the Metal layer onto CocoaMetalView; do not walk the
   * process, only this view's own layer tree. */
  for (CALayer *sub in layer.sublayers) {
    if ([sub isKindOfClass:[CAMetalLayer class]]) {
      return (CAMetalLayer *)sub;
    }
  }
  return nil;
}

void mixar_allow_metal_alpha(NSView *host)
{
  CAMetalLayer *metal = mixar_metal_layer_of(host);
  if (metal == nil) {
    return;
  }
  metal.opaque = NO;
  /* RGBA16Float + EDR is composited as an opaque slab even with alpha in
   * the drawable and even if the view's alphaValue is lowered. Island and
   * pill do not need HDR: switch this layer to BGRA8 so WindowServer
   * honours per-pixel alpha over the frost sibling. GHOST rebuilds the
   * present pipeline to match the new format on the next swap. */
  metal.wantsExtendedDynamicRangeContent = NO;
  metal.framebufferOnly = NO;
  metal.pixelFormat = MTLPixelFormatBGRA8Unorm;
  mixar_set_layer_colorspace(metal, kCGColorSpaceSRGB);
  metal.drawableSize = metal.drawableSize;
  host.alphaValue = 1.0;
}

void mixar_restore_metal_opaque(NSView *host)
{
  CAMetalLayer *metal = mixar_metal_layer_of(host);
  if (metal != nil) {
    metal.opaque = YES;
    metal.wantsExtendedDynamicRangeContent = YES;
    metal.framebufferOnly = YES;
    metal.pixelFormat = MTLPixelFormatRGBA16Float;
    mixar_set_layer_colorspace(metal, kCGColorSpaceExtendedSRGB);
  }
  host.alphaValue = 1.0;
}

void mixar_install_glass(NSWindow *win)
{
  NSView *host = win.contentView;
  if (host == nil || mixar_glass_get(win) != nil) {
    return;
  }
  /* Theme-frame sibling. No superview means the window is not in the
   * hierarchy yet — wrapping contentView would detach the Metal view. */
  NSView *container = host.superview;
  if (container == nil) {
    return;
  }

  const CGFloat radius = (host.layer != nil) ? host.layer.cornerRadius : 0.0;
  NSView *glass = mixar_make_glass(host.frame);
  mixar_style_glass(glass, radius);
  [container addSubview:glass positioned:NSWindowBelow relativeTo:host];
  mixar_glass_set(win, glass);
  [glass release];
  mixar_allow_metal_alpha(host);
}

void mixar_remove_glass(NSWindow *win)
{
  NSView *glass = mixar_glass_get(win);
  if (glass != nil) {
    [glass removeFromSuperview];
    mixar_glass_set(win, nil);
  }
  if (win.contentView != nil) {
    mixar_restore_metal_opaque(win.contentView);
  }
}

}  // namespace

void Mixar_CocoaGlassAllowMetalAlpha(NSView *host)
{
  mixar_allow_metal_alpha(host);
}

void Mixar_CocoaGlassSetEnabled(NSWindow *win, const bool enable)
{
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    if (enable) {
      win.opaque = NO;
      win.backgroundColor = [NSColor clearColor];
      mixar_install_glass(win);
      /* Frost needs a superview; Metal alpha does not. The island's
       * corners are already punched by the window mask — without this
       * the CAMetalLayer stays opaque and the card interior is a slab. */
      if (win.contentView != nil) {
        mixar_allow_metal_alpha(win.contentView);
      }
    }
    else {
      mixar_remove_glass(win);
      win.opaque = YES;
      win.backgroundColor = [NSColor windowBackgroundColor];
    }
  }
}

void Mixar_CocoaGlassSyncRadius(NSWindow *win, const float radius)
{
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    NSView *glass = mixar_glass_get(win);
    /* First SetBlurBehind can run before the Metal view is in the theme
     * frame. Rounding the window is a later call, and by then the host
     * has a superview — install then rather than leaving frost missing. */
    if (glass == nil && !win.opaque) {
      mixar_install_glass(win);
      glass = mixar_glass_get(win);
    }
    if (glass != nil) {
      const CGFloat clamped = (radius < 0.0f) ? 0.0 : CGFloat(radius);
      mixar_style_glass(glass, clamped);
    }
    if (!win.opaque && win.contentView != nil) {
      mixar_allow_metal_alpha(win.contentView);
    }
  }
}
