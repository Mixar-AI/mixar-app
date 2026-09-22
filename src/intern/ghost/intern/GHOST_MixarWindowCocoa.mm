/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#import <AppKit/AppKit.h>

#include "GHOST_WindowCocoa.hh"

extern "C" void Mixar_WindowClearCloseObservers(NSWindow *window);

/* A checkpoint can close the focused island from inside its text handler.
 * Retire AppKit's text client while the GHOST view is still alive, before
 * disposeWindow releases the view and changes the key window. The glass
 * content view is a wrapper, so resolve the actual client via firstResponder. */
extern "C" void Mixar_WindowPrepareForClose(void *window_handle)
{
  auto *cocoa = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *window = (NSWindow *)cocoa->getViewWindow();
  if (window == nil) {
    return;
  }
  @autoreleasepool {
    Mixar_WindowClearCloseObservers(window);
    NSResponder *responder = window.firstResponder;
    NSTextInputContext *input = nil;
    if ([responder isKindOfClass:[NSView class]]) {
      input = [[(NSView *)responder inputContext] retain];
    }
    [input discardMarkedText];
    [input deactivate];
    [window makeFirstResponder:nil];

    /* Transfer keyboard ownership before destroying the old text client.
     * A pill may be parented to the island; prefer the visible host. */
    if (window.isKeyWindow) {
      NSWindow *host = window.parentWindow;
      while (host.parentWindow != nil) {
        host = host.parentWindow;
      }
      if (host != nil && host.isVisible && host.canBecomeKeyWindow) {
        [host makeKeyWindow];
      }
      else {
        /* resignKeyWindow is a notification hook, not an ownership change.
         * Order out a detached window so AppKit retires its key status before
         * the text client's native view is destroyed. */
        [window orderOut:nil];
      }
    }
    [input release];
  }
}
