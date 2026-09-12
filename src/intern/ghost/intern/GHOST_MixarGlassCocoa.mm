/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Native frost behind Mixar's island / pill windows.
 *
 * AppKit owns the effect's view hierarchy: CocoaMetalView is the glass
 * contentView, while GHOST retains the same Metal view/context throughout.
 * NSVisualEffectView provides behind-window frost on older macOS versions.
 * Only this window's Metal layer presents alpha; other windows keep HDR.
 */

#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/message.h>
#import <objc/runtime.h>

#include "GHOST_MixarGlassCocoa.hh"

/* GHOST's CocoaMetalView hard-codes isOpaque=YES. AppKit then skips the
 * native backdrop and WindowServer may treat the presented drawable as a
 * solid plane. Follow the window: island/pill set opaque=NO. */
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
const void *kMixarMetalHostKey = &kMixarMetalHostKey;

NSView *mixar_metal_host(NSWindow *win)
{
  NSView *host = objc_getAssociatedObject(win, kMixarMetalHostKey);
  return host != nil ? host : win.contentView;
}

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

  /* Regular keeps the floating controls legible over a changing scene. */
  mixar_msg_set_llong(glass, "setStyle:", 0);
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
  if (!metal.opaque && metal.pixelFormat == MTLPixelFormatBGRA8Unorm) {
    return;
  }
  metal.opaque = NO;
  /* RGBA16Float + EDR is composited as an opaque slab even with alpha in
   * the drawable and even if the view's alphaValue is lowered. Island and
   * pill do not need HDR: switch this layer to BGRA8 so WindowServer
   * honours per-pixel alpha over the native glass. GHOST rebuilds the
   * present pipeline to match the new format on the next swap. */
  metal.wantsExtendedDynamicRangeContent = NO;
  metal.framebufferOnly = NO;
  metal.pixelFormat = MTLPixelFormatBGRA8Unorm;
  mixar_set_layer_colorspace(metal, kCGColorSpaceSRGB);
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

bool mixar_install_glass(NSWindow *win)
{
  if (mixar_glass_get(win) != nil) {
    return true;
  }
  NSView *host = win.contentView;
  if (host == nil || mixar_metal_layer_of(host) == nil) {
    return false;
  }
  const CGFloat radius = host.layer.cornerRadius;
  NSView *glass = mixar_make_glass(host.frame);
  if (glass == nil) {
    return false;
  }
  mixar_style_glass(glass, radius);
  /* Retain the original GPU view across NSWindow's content replacement.
   * GHOST's metal_view_ and drawing context continue to point to this view. */
  objc_setAssociatedObject(win, kMixarMetalHostKey, host, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
  NSResponder *responder = [win.firstResponder retain];
  win.contentView = glass;
  host.frame = glass.bounds;
  host.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
  const SEL setter = sel_registerName("setContentView:");
  if ([glass respondsToSelector:setter]) {
    reinterpret_cast<void (*)(id, SEL, id)>(objc_msgSend)(glass, setter, host);
  }
  else {
    [glass addSubview:host];
  }
  mixar_glass_set(win, glass);
  [glass layoutSubtreeIfNeeded];
  [win makeFirstResponder:responder];
  [responder release];
  [glass release];
  mixar_allow_metal_alpha(host);
  return true;
}

void mixar_remove_glass(NSWindow *win)
{
  NSView *glass = mixar_glass_get(win);
  NSView *host = mixar_metal_host(win);
  if (glass != nil) {
    NSResponder *responder = [win.firstResponder retain];
    const NSRect bounds = glass.bounds;
    /* Both associated objects stay alive until NSWindow owns the host again. */
    win.contentView = host;
    host.frame = bounds;
    [win makeFirstResponder:responder];
    [responder release];
    mixar_glass_set(win, nil);
    objc_setAssociatedObject(win, kMixarMetalHostKey, nil, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
  }
  mixar_restore_metal_opaque(host);
}

}  // namespace

void Mixar_CocoaGlassAllowMetalAlpha(NSView *host)
{
  mixar_allow_metal_alpha(host);
}

bool Mixar_CocoaGlassSetEnabled(NSWindow *win, const bool enable)
{
  if (win == nil) {
    return false;
  }
  @autoreleasepool {
    if (enable) {
      if (!mixar_install_glass(win)) {
        return false;
      }
      win.opaque = NO;
      win.backgroundColor = [NSColor clearColor];
      mixar_allow_metal_alpha(mixar_metal_host(win));
    }
    else {
      mixar_remove_glass(win);
      win.opaque = YES;
      win.backgroundColor = [NSColor windowBackgroundColor];
    }
    return !enable || (mixar_glass_get(win) != nil &&
                       mixar_metal_layer_of(mixar_metal_host(win)) != nil);
  }
}

void Mixar_CocoaGlassSyncRadius(NSWindow *win, const float radius)
{
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    NSView *glass = mixar_glass_get(win);
    if (glass != nil) {
      const CGFloat clamped = (radius < 0.0f) ? 0.0 : CGFloat(radius);

      mixar_style_glass(glass, clamped);
      NSView *host = mixar_metal_host(win);
      host.layer.cornerRadius = clamped;
      host.layer.masksToBounds = (clamped > 0.0);
    }
    if (!win.opaque && win.contentView != nil) {
      mixar_allow_metal_alpha(mixar_metal_host(win));
    }
  }
}
