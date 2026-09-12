/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/* Execute the real native glass host without a Blender process. */
#import <AppKit/AppKit.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/message.h>
#include <cassert>
#include "GHOST_MixarGlassCocoa.hh"

@interface CocoaMetalView : NSView
@end
@implementation CocoaMetalView
- (BOOL)acceptsFirstResponder { return YES; }
@end

static NSWindow *make_window(bool metal)
{
  NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 320, 180)
                                              styleMask:NSWindowStyleMaskBorderless
                                                backing:NSBackingStoreBuffered
                                                  defer:NO];
  window.releasedWhenClosed = NO;
  if (metal) {
    CocoaMetalView *host = [[CocoaMetalView alloc] initWithFrame:window.contentView.bounds];
    host.wantsLayer = YES;
    CAMetalLayer *layer = [CAMetalLayer layer];
    layer.device = MTLCreateSystemDefaultDevice();
    layer.pixelFormat = MTLPixelFormatRGBA16Float;
    layer.opaque = YES;
    host.layer = layer;
    window.contentView = host;
    [host release];
  }
  return window;
}

int main()
{
  @autoreleasepool {
    [NSApplication sharedApplication];
    NSWindow *untouched = make_window(true);
    NSView *untouched_host = untouched.contentView;
    NSWindow *no_metal = make_window(false);
    NSView *plain = no_metal.contentView;
    assert(!Mixar_CocoaGlassSetEnabled(no_metal, true));
    assert(no_metal.contentView == plain && no_metal.opaque);

    NSWindow *window = make_window(true);
    NSView *host = window.contentView;
    CAMetalLayer *metal = (CAMetalLayer *)host.layer;
    [window makeFirstResponder:host];
    for (int cycle = 0; cycle < 3; cycle++) {
      assert(Mixar_CocoaGlassSetEnabled(window, true));
      NSView *glass = window.contentView;
      assert(glass != host && host.window == window);
      assert([host isDescendantOf:glass] && window.firstResponder == host);
      assert(!window.opaque && window.backgroundColor.alphaComponent == 0);
      assert(!metal.opaque && metal.pixelFormat == MTLPixelFormatBGRA8Unorm);
      const SEL getter = sel_registerName("contentView");
      if ([glass respondsToSelector:getter]) {
        assert(reinterpret_cast<id (*)(id, SEL)>(objc_msgSend)(glass, getter) == host);
      }
      assert(Mixar_CocoaGlassSetEnabled(window, true));
      assert(window.contentView == glass);  // no duplicate effect/container
      [window setContentSize:NSMakeSize(480 + cycle * 20, 240)];
      [glass layoutSubtreeIfNeeded];
      assert(NSEqualSizes(host.frame.size, glass.bounds.size));
      Mixar_CocoaGlassSyncRadius(window, 24);
      assert(host.layer.cornerRadius == 24);
      assert(Mixar_CocoaGlassSetEnabled(window, false));
      assert(window.contentView == host && host.window == window);
      assert(window.firstResponder == host && window.opaque && metal.opaque);
      assert(metal.pixelFormat == MTLPixelFormatRGBA16Float);
    }
    assert(untouched.contentView == untouched_host && untouched.opaque);
    assert(((CAMetalLayer *)untouched_host.layer).pixelFormat == MTLPixelFormatRGBA16Float);
    for (NSWindow *w in @[window, untouched, no_metal]) {
      [w close];
      [w release];
    }
  }
  puts("native glass host: enable/resize/disable/recreate/opaque isolation passed");
}
