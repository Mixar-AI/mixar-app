/* SPDX-FileCopyrightText: 2001-2002 NaN Holding BV. All rights reserved.
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "GHOST_SystemCocoa.hh"

#include "GHOST_EventButton.hh"
#include "GHOST_EventCursor.hh"
#include "GHOST_EventDragnDrop.hh"
#include "GHOST_EventKey.hh"
#include "GHOST_EventString.hh"
#include "GHOST_EventTrackpad.hh"
#include "GHOST_EventWheel.hh"
#include "GHOST_TimerManager.hh"
#include "GHOST_TimerTask.hh"
#include "GHOST_WindowCocoa.hh"
#include "GHOST_WindowManager.hh"

/* Don't generate OpenGL deprecation warning. This is a known thing, and is not something easily
 * solvable in a short term. */
#ifdef __clang__
#  pragma clang diagnostic ignored "-Wdeprecated-declarations"
#endif

#ifdef WITH_METAL_BACKEND
#  include "GHOST_ContextMTL.hh"
#endif

#ifdef WITH_VULKAN_BACKEND
#  include "GHOST_ContextVK.hh"
#endif

#ifdef WITH_INPUT_NDOF
#  include "GHOST_NDOFManagerCocoa.hh"
#endif

#include "AssertMacros.h"

#import <Cocoa/Cocoa.h>

/* For the currently not ported to Cocoa keyboard layout functions (64bit & 10.6 compatible) */
#include <Carbon/Carbon.h>

#include <sys/sysctl.h>
#include <sys/time.h>
#include <sys/types.h>

#include <dispatch/dispatch.h>
#include <mach/mach_time.h>

/* --------------------------------------------------------------------
 * Keymaps, mouse converters.
 */

static GHOST_TButton convertButton(int button)
{
  switch (button) {
    case 0:
      return GHOST_kButtonMaskLeft;
    case 1:
      return GHOST_kButtonMaskRight;
    case 2:
      return GHOST_kButtonMaskMiddle;
    case 3:
      return GHOST_kButtonMaskButton4;
    case 4:
      return GHOST_kButtonMaskButton5;
    case 5:
      return GHOST_kButtonMaskButton6;
    case 6:
      return GHOST_kButtonMaskButton7;
    default:
      return GHOST_kButtonMaskLeft;
  }
}

/**
 * Converts Mac raw-key codes (same for Cocoa & Carbon)
 * into GHOST key codes
 * \param rawCode: The raw physical key code
 * \param recvChar: the character ignoring modifiers (except for shift)
 * \return Ghost key code
 */
static GHOST_TKey convertKey(int rawCode, unichar recvChar)
{
  // printf("\nrecvchar %c 0x%x",recvChar,recvChar);
  switch (rawCode) {
    /* Physical key-codes: (not used due to map changes in international keyboards). */
#if 0
    case kVK_ANSI_A:    return GHOST_kKeyA;
    case kVK_ANSI_B:    return GHOST_kKeyB;
    case kVK_ANSI_C:    return GHOST_kKeyC;
    case kVK_ANSI_D:    return GHOST_kKeyD;
    case kVK_ANSI_E:    return GHOST_kKeyE;
    case kVK_ANSI_F:    return GHOST_kKeyF;
    case kVK_ANSI_G:    return GHOST_kKeyG;
    case kVK_ANSI_H:    return GHOST_kKeyH;
    case kVK_ANSI_I:    return GHOST_kKeyI;
    case kVK_ANSI_J:    return GHOST_kKeyJ;
    case kVK_ANSI_K:    return GHOST_kKeyK;
    case kVK_ANSI_L:    return GHOST_kKeyL;
    case kVK_ANSI_M:    return GHOST_kKeyM;
    case kVK_ANSI_N:    return GHOST_kKeyN;
    case kVK_ANSI_O:    return GHOST_kKeyO;
    case kVK_ANSI_P:    return GHOST_kKeyP;
    case kVK_ANSI_Q:    return GHOST_kKeyQ;
    case kVK_ANSI_R:    return GHOST_kKeyR;
    case kVK_ANSI_S:    return GHOST_kKeyS;
    case kVK_ANSI_T:    return GHOST_kKeyT;
    case kVK_ANSI_U:    return GHOST_kKeyU;
    case kVK_ANSI_V:    return GHOST_kKeyV;
    case kVK_ANSI_W:    return GHOST_kKeyW;
    case kVK_ANSI_X:    return GHOST_kKeyX;
    case kVK_ANSI_Y:    return GHOST_kKeyY;
    case kVK_ANSI_Z:    return GHOST_kKeyZ;
#endif
    /* Numbers keys: mapped to handle some international keyboard (e.g. French). */
    case kVK_ANSI_1:
      return GHOST_kKey1;
    case kVK_ANSI_2:
      return GHOST_kKey2;
    case kVK_ANSI_3:
      return GHOST_kKey3;
    case kVK_ANSI_4:
      return GHOST_kKey4;
    case kVK_ANSI_5:
      return GHOST_kKey5;
    case kVK_ANSI_6:
      return GHOST_kKey6;
    case kVK_ANSI_7:
      return GHOST_kKey7;
    case kVK_ANSI_8:
      return GHOST_kKey8;
    case kVK_ANSI_9:
      return GHOST_kKey9;
    case kVK_ANSI_0:
      return GHOST_kKey0;

    case kVK_ANSI_Keypad0:
      return GHOST_kKeyNumpad0;
    case kVK_ANSI_Keypad1:
      return GHOST_kKeyNumpad1;
    case kVK_ANSI_Keypad2:
      return GHOST_kKeyNumpad2;
    case kVK_ANSI_Keypad3:
      return GHOST_kKeyNumpad3;
    case kVK_ANSI_Keypad4:
      return GHOST_kKeyNumpad4;
    case kVK_ANSI_Keypad5:
      return GHOST_kKeyNumpad5;
    case kVK_ANSI_Keypad6:
      return GHOST_kKeyNumpad6;
    case kVK_ANSI_Keypad7:
      return GHOST_kKeyNumpad7;
    case kVK_ANSI_Keypad8:
      return GHOST_kKeyNumpad8;
    case kVK_ANSI_Keypad9:
      return GHOST_kKeyNumpad9;
    case kVK_ANSI_KeypadDecimal:
      return GHOST_kKeyNumpadPeriod;
    case kVK_ANSI_KeypadEnter:
      return GHOST_kKeyNumpadEnter;
    case kVK_ANSI_KeypadPlus:
      return GHOST_kKeyNumpadPlus;
    case kVK_ANSI_KeypadMinus:
      return GHOST_kKeyNumpadMinus;
    case kVK_ANSI_KeypadMultiply:
      return GHOST_kKeyNumpadAsterisk;
    case kVK_ANSI_KeypadDivide:
      return GHOST_kKeyNumpadSlash;
    case kVK_ANSI_KeypadClear:
      return GHOST_kKeyUnknown;

    case kVK_F1:
      return GHOST_kKeyF1;
    case kVK_F2:
      return GHOST_kKeyF2;
    case kVK_F3:
      return GHOST_kKeyF3;
    case kVK_F4:
      return GHOST_kKeyF4;
    case kVK_F5:
      return GHOST_kKeyF5;
    case kVK_F6:
      return GHOST_kKeyF6;
    case kVK_F7:
      return GHOST_kKeyF7;
    case kVK_F8:
      return GHOST_kKeyF8;
    case kVK_F9:
      return GHOST_kKeyF9;
    case kVK_F10:
      return GHOST_kKeyF10;
    case kVK_F11:
      return GHOST_kKeyF11;
    case kVK_F12:
      return GHOST_kKeyF12;
    case kVK_F13:
      return GHOST_kKeyF13;
    case kVK_F14:
      return GHOST_kKeyF14;
    case kVK_F15:
      return GHOST_kKeyF15;
    case kVK_F16:
      return GHOST_kKeyF16;
    case kVK_F17:
      return GHOST_kKeyF17;
    case kVK_F18:
      return GHOST_kKeyF18;
    case kVK_F19:
      return GHOST_kKeyF19;
    case kVK_F20:
      return GHOST_kKeyF20;

    case kVK_UpArrow:
      return GHOST_kKeyUpArrow;
    case kVK_DownArrow:
      return GHOST_kKeyDownArrow;
    case kVK_LeftArrow:
      return GHOST_kKeyLeftArrow;
    case kVK_RightArrow:
      return GHOST_kKeyRightArrow;

    case kVK_Return:
      return GHOST_kKeyEnter;
    case kVK_Delete:
      return GHOST_kKeyBackSpace;
    case kVK_ForwardDelete:
      return GHOST_kKeyDelete;
    case kVK_Escape:
      return GHOST_kKeyEsc;
    case kVK_Tab:
      return GHOST_kKeyTab;
    case kVK_Space:
      return GHOST_kKeySpace;

    case kVK_Home:
      return GHOST_kKeyHome;
    case kVK_End:
      return GHOST_kKeyEnd;
    case kVK_PageUp:
      return GHOST_kKeyUpPage;
    case kVK_PageDown:
      return GHOST_kKeyDownPage;
#if 0
    /* These constants with "ANSI" in the name are labeled according to the key position on an
     * ANSI-standard US keyboard. Therefore they may not match the physical key label on other
     * keyboard layouts. */
    case kVK_ANSI_Minus:        return GHOST_kKeyMinus;
    case kVK_ANSI_Equal:        return GHOST_kKeyEqual;
    case kVK_ANSI_Comma:        return GHOST_kKeyComma;
    case kVK_ANSI_Period:       return GHOST_kKeyPeriod;
    case kVK_ANSI_Slash:        return GHOST_kKeySlash;
    case kVK_ANSI_Semicolon:    return GHOST_kKeySemicolon;
    case kVK_ANSI_Quote:        return GHOST_kKeyQuote;
    case kVK_ANSI_Backslash:    return GHOST_kKeyBackslash;
    case kVK_ANSI_LeftBracket:  return GHOST_kKeyLeftBracket;
    case kVK_ANSI_RightBracket: return GHOST_kKeyRightBracket;
    case kVK_ANSI_Grave:        return GHOST_kKeyAccentGrave;
    case kVK_ISO_Section:       return GHOST_kKeyUnknown;
#endif
    case kVK_VolumeUp:
    case kVK_VolumeDown:
    case kVK_Mute:
      return GHOST_kKeyUnknown;

    default: {
      /* Alphanumerical or punctuation key that is remappable in international keyboards. */
      if ((recvChar >= 'A') && (recvChar <= 'Z')) {
        return (GHOST_TKey)(recvChar - 'A' + GHOST_kKeyA);
      }

      if ((recvChar >= 'a') && (recvChar <= 'z')) {
        return (GHOST_TKey)(recvChar - 'a' + GHOST_kKeyA);
      }
      else {
        /* Leopard and Snow Leopard 64bit compatible API. */
        const TISInputSourceRef kbdTISHandle = TISCopyCurrentKeyboardLayoutInputSource();
        /* The keyboard layout. */
        const CFDataRef uchrHandle = static_cast<CFDataRef>(
            TISGetInputSourceProperty(kbdTISHandle, kTISPropertyUnicodeKeyLayoutData));
        CFRelease(kbdTISHandle);

        /* Get actual character value of the "remappable" keys in international keyboards,
         * if keyboard layout is not correctly reported (e.g. some non Apple keyboards in Tiger),
         * then fall back on using the received #charactersIgnoringModifiers. */
        if (uchrHandle) {
          UInt32 deadKeyState = 0;
          UniCharCount actualStrLength = 0;

          UCKeyTranslate((UCKeyboardLayout *)CFDataGetBytePtr(uchrHandle),
                         rawCode,
                         kUCKeyActionDown,
                         0,
                         LMGetKbdType(),
                         kUCKeyTranslateNoDeadKeysMask,
                         &deadKeyState,
                         1,
                         &actualStrLength,
                         &recvChar);
        }

        switch (recvChar) {
          case '-':
            return GHOST_kKeyMinus;
          case '+':
            return GHOST_kKeyPlus;
          case '=':
            return GHOST_kKeyEqual;
          case ',':
            return GHOST_kKeyComma;
          case '.':
            return GHOST_kKeyPeriod;
          case '/':
            return GHOST_kKeySlash;
          case ';':
            return GHOST_kKeySemicolon;
          case '\'':
            return GHOST_kKeyQuote;
          case '\\':
            return GHOST_kKeyBackslash;
          case '[':
            return GHOST_kKeyLeftBracket;
          case ']':
            return GHOST_kKeyRightBracket;
          case '`':
          case '<': /* The position of '`' is equivalent to this symbol in the French layout. */
            return GHOST_kKeyAccentGrave;
          default:
            return GHOST_kKeyUnknown;
        }
      }
    }
  }
  return GHOST_kKeyUnknown;
}

/* --------------------------------------------------------------------
 * Utility functions.
 */

#define FIRSTFILEBUFLG 512
static bool g_hasFirstFile = false;
static char g_firstFileBuf[FIRSTFILEBUFLG];

/* TODO: Need to investigate this.
 * Function called too early in creator.c to have g_hasFirstFile == true */
extern "C" int GHOST_HACK_getFirstFile(char buf[FIRSTFILEBUFLG])
{
  if (g_hasFirstFile) {
    memcpy(buf, g_firstFileBuf, FIRSTFILEBUFLG);
    buf[FIRSTFILEBUFLG - 1] = '\0';
    return 1;
  }
  return 0;
}

/* --------------------------------------------------------------------
 * Mixar — chromeless / floating-bubble window styling
 *
 * Strips the macOS title bar and the three traffic-light buttons
 * (close / minimize / zoom) from a window after creation. Used by
 * the Agent Bubble editor (SPACE_AGENT_BUBBLE) so its tear-off
 * window reads as a true floating popup rather than a second main
 * window.
 *
 * Defined here (rather than in a fresh overlay file) because:
 *   1. GHOST_SystemCocoa.mm is already overlaid in src/, so adding
 *      the function avoids touching the build system / introducing a
 *      new translation unit that CMake wouldn't see.
 *   2. The function only needs GHOST_WindowCocoa::getViewWindow(),
 *      which is public, so we can poke the NSWindow directly without
 *      patching the Cocoa window class itself.
 *
 * Caller declares a matching `extern "C"` prototype — see
 * src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc.
 *
 * The window_handle argument is wmWindow.ghostwin (a void *
 * upcast of GHOST_WindowCocoa *), not a Python object. Pass nullptr
 * is a no-op.
 */
/* Force-resize an NSWindow to a specific content size in AppKit points,
 * bypassing contentMinSize. Used after WM_window_open to override
 * Blender's internal size clamping (std::max with {200,150}) and the
 * default contentMinSize {320,240} that GHOST sets on every window —
 * both of which keep the Agent Bubble window from opening at the
 * compact dimensions we want.
 *
 * Lowers contentMinSize to the requested size as a side-effect so
 * subsequent user resize doesn't immediately snap back to the old
 * minimum. */
extern "C" void Mixar_WindowForceSize(void *window_handle, int width, int height)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }

  @autoreleasepool {
    if ([win inLiveResize]) {
      return;
    }

    /* Drop contentMinSize and raise contentMaxSize so setFrame can
     * resize the window freely, past any existing constraints. */
    win.contentMinSize = NSMakeSize(100, 100);
    win.contentMaxSize = NSMakeSize(CGFLOAT_MAX, CGFLOAT_MAX);
    win.maxSize = NSMakeSize(CGFLOAT_MAX, CGFLOAT_MAX);

    NSRect frame = win.frame;
    /* setFrame takes outer (chrome-inclusive) size; convert from the
     * desired content size. With our chromeless treatment the title
     * bar height is effectively zero, so content ≈ frame, but the
     * conversion is correct regardless. */
    NSRect content_rect = NSMakeRect(0, 0, width, height);
    NSRect new_frame_size = [win frameRectForContentRect:content_rect];

    /* Anchor at the existing BOTTOM-left. NSWindow.frame.origin is in
     * Y-up screen coords with origin at the screen's bottom-left, so
     * keeping origin.y constant means the window's bottom edge stays
     * put — increasing height extends the window UPWARD (top moves
     * up), shrinking height pulls the top down toward the bottom.
     *
     * That's exactly the gesture model the bubble's header drag wants:
     * drag the header UP → window grows UP → header follows the
     * cursor. Top-left anchoring (the previous behaviour) felt
     * inverted: drag-up shrunk the visible header.
     *
     * Width still anchors at left (origin.x stays). */
    frame.size.width = new_frame_size.size.width;
    frame.size.height = new_frame_size.size.height;

    [win setFrame:frame display:YES animate:NO];
  }
}


/* Apply rounded corners to an NSWindow's content view layer.
 *
 * Used by the Agent Bubble's chromeless tear-off window so it reads
 * as a soft floating popup rather than a hard rectangular window.
 *
 * Pass radius = 0 to revert to square corners. Negative values are
 * clamped to 0.
 *
 * Implementation notes:
 *   * Sets `wantsLayer = YES` on the content view so it has a backing
 *     CALayer to round.
 *   * Sets `masksToBounds = YES` so child draws are clipped to the
 *     rounded rectangle (otherwise the editor draws over the corners
 *     and they look square).
 *   * Makes the window `opaque = NO` and gives it a clear background
 *     so the area outside the rounded rect renders transparent
 *     instead of as the OS window background colour.
 *
 * Caveat: with Metal/OpenGL views, the root layer is the Metal /
 * GL surface rather than a plain CALayer, so cornerRadius applies
 * to the surface bounds. macOS handles this correctly for both
 * — the content gets clipped to the rounded rect.
 */
static NSMutableDictionary *s_mixar_parent_observers_by_child = nil;

static NSValue *mixar_observer_key_for_child(NSWindow *child)
{
  return [NSValue valueWithNonretainedObject:child];
}

static void mixar_clear_parent_observers_for_child(NSWindow *child)
{
  if (child == nil || s_mixar_parent_observers_by_child == nil) {
    return;
  }
  NSValue *key = mixar_observer_key_for_child(child);
  NSArray *tokens = [s_mixar_parent_observers_by_child objectForKey:key];
  if (tokens == nil) {
    return;
  }
  NSNotificationCenter *centre = [NSNotificationCenter defaultCenter];
  for (id token in tokens) {
    [centre removeObserver:token];
  }
  [s_mixar_parent_observers_by_child removeObjectForKey:key];
}

static void mixar_store_parent_observers_for_child(NSWindow *child, NSArray *tokens)
{
  if (child == nil || tokens == nil) {
    return;
  }
  if (s_mixar_parent_observers_by_child == nil) {
    s_mixar_parent_observers_by_child = [[NSMutableDictionary alloc] init];
  }
  [s_mixar_parent_observers_by_child setObject:tokens
                                        forKey:mixar_observer_key_for_child(child)];
}

/* Identifier string set on the Agent Bubble + pill NSWindows so
 * hasDialogWindow() can exempt them from the modal-dialog gate that
 * BlenderWindow.canBecomeKeyWindow enforces.  See
 * Mixar_WindowMarkAsFloatingDock below. */
static NSString *const kMixarFloatingDockIdentifier = @"mixar_floating_dock";
static NSInteger s_mixar_floating_dock_suppression_depth = 0;
static NSMutableArray<NSWindow *> *s_mixar_suppressed_floating_docks = nil;

/* Force a full Blender redraw for the given NSWindow.
 *
 * Problem: when a window becomes visible after being hidden (orderOut
 * during pill-minimize, or alpha=0 during splash suppress), the user
 * sees stale framebuffer content until Blender redraws.
 *
 * windowDidExpose: is unreliable on modern macOS buffered windows.
 * GHOST_kEventWindowUpdate (the event it posts) only triggers
 * NC_WINDOW — not enough for the bubble's space type.
 *
 * Dragging fixes the stale content because windowDidResize: posts
 * GHOST_kEventWindowSize, which triggers the full NC_SCREEN|NA_EDITED
 * + NC_WINDOW|NA_EDITED refresh.  We replicate that here by calling
 * the delegate's windowDidResize: directly.
 *
 * Additionally, we invalidate the GHOST OpenGL/Metal rendering view
 * (a subview of contentView — NOT the contentView itself) and
 * schedule a delayed re-invalidation to cover edge cases where
 * Blender hasn't finished preparing the content at the first trigger. */
static void mixar_force_window_redraw(NSWindow *win)
{
  if (win == nil) {
    return;
  }

  /* 1. Post GHOST_kEventWindowSize via the delegate — same event that
   *    dragging produces, triggers full NC_SCREEN + NC_WINDOW refresh. */
  id delegate = [win delegate];
  if (delegate != nil && [delegate respondsToSelector:@selector(windowDidResize:)]) {
    NSNotification *note = [NSNotification notificationWithName:NSWindowDidResizeNotification
                                                         object:win];
    [delegate windowDidResize:note];
  }

  /* 2. Invalidate the GHOST rendering view (OpenGL or Metal subview).
   *    contentView.needsDisplay alone doesn't propagate to the
   *    rendering subview, so walk the subview tree. */
  NSView *contentView = [win contentView];
  for (NSView *subview in [contentView subviews]) {
    [subview setNeedsDisplay:YES];
  }

  /* 3. Schedule a second invalidation after ~100 ms to catch cases
   *    where Blender hadn't finished preparing content at step 2.
   *    The block retains `win` so it stays valid across the delay. */
  dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(100 * NSEC_PER_MSEC)),
                 dispatch_get_main_queue(),
                 ^{
                   if (win == nil || ![win isVisible]) {
                     return;
                   }
                   for (NSView *subview in [[win contentView] subviews]) {
                     [subview setNeedsDisplay:YES];
                   }
                 });
}


/* If floating-dock suppression is active AND the given NSWindow is
 * tagged as a floating dock, hide it and add it to the suppressed list
 * so Mixar_FloatingDocksRestoreAfterModal will re-show it later.
 *
 * Uses alpha + ignoresMouseEvents instead of orderOut because
 * orderOut on a child window DETACHES it from its parent — the
 * bubble would lose its addChildWindow relationship with the host
 * and fall behind the main window on the next click.
 *
 * Returns true if the window was suppressed. */
static bool mixar_suppress_floating_dock_if_needed(NSWindow *win)
{
  if (win == nil || s_mixar_floating_dock_suppression_depth <= 0) {
    return false;
  }
  if (![win.identifier isEqualToString:kMixarFloatingDockIdentifier]) {
    return false;
  }
  if (s_mixar_suppressed_floating_docks == nil) {
    s_mixar_suppressed_floating_docks = [[NSMutableArray alloc] init];
  }
  if (![s_mixar_suppressed_floating_docks containsObject:win]) {
    [s_mixar_suppressed_floating_docks addObject:win];
  }
  [win setAlphaValue:0.0];
  [win setIgnoresMouseEvents:YES];
  return true;
}


/* Make `child_handle` a child window of `parent_handle` so its
 * position tracks the parent's frame automatically — when the user
 * drags the parent, the child follows; when the parent closes, the
 * child closes too.
 *
 * Used to attach the Agent Bubble's floating status pill to the
 * main bubble window so they read as a single moving unit even
 * though they are two separate NSWindows.
 *
 * NSWindowAbove keeps the child always rendered above the parent in
 * the window stack — important so the pill sits visibly above the
 * bubble rather than disappearing behind it after focus changes. */
extern "C" void Mixar_WindowSetParent(void *child_handle, void *parent_handle)
{
  if (child_handle == nullptr || parent_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *child_cocoa = static_cast<GHOST_WindowCocoa *>(child_handle);
  GHOST_WindowCocoa *parent_cocoa = static_cast<GHOST_WindowCocoa *>(parent_handle);
  NSWindow *child = (NSWindow *)child_cocoa->getViewWindow();
  NSWindow *parent = (NSWindow *)parent_cocoa->getViewWindow();
  if (child == nil || parent == nil) {
    return;
  }
  @autoreleasepool {
    mixar_clear_parent_observers_for_child(child);
    [parent addChildWindow:child ordered:NSWindowAbove];
    /* addChildWindow:ordered:NSWindowAbove implicitly shows the child.
     * If a modal is active, suppress the dock immediately. */
    mixar_suppress_floating_dock_if_needed(child);

    /* macOS child windows track the parent's POSITION (origin) but
     * NOT its SIZE. So when the user drags the parent's top edge
     * upward to grow it taller, the parent's height changes but the
     * child stays at its old origin — the floating pill ends up
     * overlapping or hidden behind the bubble's new top.
     *
     * To keep the pill anchored to the parent's TOP-LEFT regardless
     * of resize, AND to update at the same vsync as the parent's
     * move (the auto-track via addChildWindow can lag visibly
     * during fast drags, leaving the pill trailing the bubble),
     * register observers for BOTH NSWindowDidResizeNotification AND
     * NSWindowDidMoveNotification on the parent and reposition the
     * child on every change. The 6 px gap mirrors
     * AGENT_BUBBLE_PILL_GAP in space_agent_bubble.cc — keep in sync.
     *
     * Observer tokens are replaced every time the parent relationship
     * changes, so repeated minimise/restore cycles do not accumulate
     * stale blocks with old offsets. */
    /* Coalescing flag: when a dispatch_async is already pending for this
     * parent-child pair, skip further queuing to avoid a pile-up of near-
     * identical repositions during live resize (one per pixel delta). */
    __block BOOL reposition_pending = NO;

    void (^apply_reposition)(void) = ^{
      reposition_pending = NO;
      if (![parent isVisible] || ![child isVisible]) {
        return;
      }
      NSRect parent_frame = parent.frame;
      NSPoint new_origin;
      new_origin.x = parent_frame.origin.x;
      new_origin.y = parent_frame.origin.y + parent_frame.size.height + 6;
      [child setFrameOrigin:new_origin];
    };
    void (^reposition)(NSNotification *) = ^(NSNotification *note) {
      if ([note.name isEqualToString:NSWindowDidResizeNotification] && [parent inLiveResize]) {
        if (!reposition_pending) {
          reposition_pending = YES;
          dispatch_async(dispatch_get_main_queue(), apply_reposition);
        }
        return;
      }
      apply_reposition();
    };
    /* During live resize, move the child on the next main-queue tick instead of
     * re-entering AppKit geometry updates from inside the resize notification. */
    NSNotificationCenter *centre = [NSNotificationCenter defaultCenter];
    id resize_token = [centre addObserverForName:NSWindowDidResizeNotification
                                          object:parent
                                           queue:[NSOperationQueue mainQueue]
                                      usingBlock:reposition];
    id end_resize_token = [centre addObserverForName:NSWindowDidEndLiveResizeNotification
                                              object:parent
                                               queue:[NSOperationQueue mainQueue]
                                          usingBlock:reposition];
    id move_token = [centre addObserverForName:NSWindowDidMoveNotification
                                        object:parent
                                         queue:[NSOperationQueue mainQueue]
                                     usingBlock:reposition];
    mixar_store_parent_observers_for_child(child, @[ resize_token, end_resize_token, move_token ]);
  }
}


/* Position `child_handle` immediately above the top-left of
 * `parent_handle`'s frame, with optional pixel offsets. NSWindow
 * coordinates are Y-up (origin at bottom-left of the screen), so
 * "above" means origin.y = parent_top, where parent_top =
 * parent.frame.origin.y + parent.frame.size.height.
 *
 * offset_x shifts horizontally (positive = right), offset_y shifts
 * vertically away from the parent (positive = further up). */
extern "C" void Mixar_WindowPositionAboveParent(void *child_handle,
                                                void *parent_handle,
                                                int offset_x,
                                                int offset_y)
{
  if (child_handle == nullptr || parent_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *child_cocoa = static_cast<GHOST_WindowCocoa *>(child_handle);
  GHOST_WindowCocoa *parent_cocoa = static_cast<GHOST_WindowCocoa *>(parent_handle);
  NSWindow *child = (NSWindow *)child_cocoa->getViewWindow();
  NSWindow *parent = (NSWindow *)parent_cocoa->getViewWindow();
  if (child == nil || parent == nil) {
    return;
  }
  @autoreleasepool {
    NSRect parent_frame = parent.frame;
    NSRect child_frame = child.frame;
    NSPoint origin;
    origin.x = parent_frame.origin.x + offset_x;
    /* Stack child immediately above the parent: parent's top edge +
     * gap, leaving room for the child's own height. */
    origin.y = parent_frame.origin.y + parent_frame.size.height + offset_y;
    (void)child_frame;  /* setFrameOrigin handles size implicitly */
    [child setFrameOrigin:origin];
  }
}


/* Toggle hidesOnDeactivate on a window. When YES, AppKit
 * automatically orderOut's the window when its application
 * deactivates (user alt-tabs to another app) and orderFront's it
 * back when the app reactivates.
 *
 * Used together with NSFloatingWindowLevel: the floating level
 * keeps the bubble above all normal Mixar windows while Mixar is
 * active, and hidesOnDeactivate hides it when the user switches
 * to another application — without this, the floating level kept
 * the bubble visible above other apps' windows too, which was
 * exactly the cross-app leak the user reported. */
extern "C" void Mixar_WindowSetHidesOnDeactivate(void *window_handle, bool hides)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    [win setHidesOnDeactivate:hides];
  }
}


/* Pin a window to its owning Space so it never leaks onto another
 * Space (macOS virtual desktop / full-screen app).
 *
 * The bug this fixes: when Mixar's main window is full-screen it lives
 * in its own dedicated Space. The Agent Bubble + pill are floating
 * child windows of that main window. With the default collection
 * behaviour AppKit treats these small auxiliary windows as eligible to
 * appear on whatever Space is currently active — so the moment the
 * user swipes to another Space (the three-finger gesture / Mission
 * Control), the bubble "comes out of Mixar" and renders on top of the
 * window in that other Space.
 *
 * The fix is two flags working together:
 *   - NSWindowCollectionBehaviorManaged ties the window to a single
 *     Space (it participates in Spaces / Exposé normally and does NOT
 *     follow the user to other Spaces).
 *   - NSWindowCollectionBehaviorFullScreenAuxiliary lets the window be
 *     shown alongside a full-screen window — without it, a child of a
 *     full-screen parent gets stranded on the non-full-screen desktop
 *     Space instead of accompanying the parent into full screen.
 *
 * We explicitly clear CanJoinAllSpaces / MoveToActiveSpace (the two
 * behaviours that make a window appear everywhere / chase the active
 * Space) in case AppKit set them implicitly for the borderless dock. */
extern "C" void Mixar_WindowBindToParentSpace(void *window_handle)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    NSWindowCollectionBehavior behavior = [win collectionBehavior];
    behavior &= ~(NSWindowCollectionBehaviorCanJoinAllSpaces |
                  NSWindowCollectionBehaviorMoveToActiveSpace |
                  NSWindowCollectionBehaviorTransient);
    behavior |= NSWindowCollectionBehaviorManaged |
                NSWindowCollectionBehaviorFullScreenAuxiliary;
    [win setCollectionBehavior:behavior];
  }
}


/* Keep the bubble above Mixar's own windows.
 *
 * On macOS, the addChildWindow:ordered:NSWindowAbove relationship
 * (set by Mixar_WindowSetParent) already ensures the bubble renders
 * above its parent.  We intentionally do NOT use NSFloatingWindowLevel
 * because that elevates the window above ALL normal-level windows in
 * the entire system — causing the bubble to overlay other apps' windows
 * when the user drags them alongside Mixar, and to cover Blender's
 * own splash screen (which is at NSNormalWindowLevel).
 *
 * This function is a no-op on macOS; the child-window ordering is
 * sufficient.  On Win32, the HWND_TOP + owner relationship handles
 * the equivalent. */
extern "C" void Mixar_WindowSetFloatingLevel(void *window_handle)
{
  /* No-op: rely on addChildWindow ordering instead of window levels. */
  (void)window_handle;
}


/* Hide an NSWindow without destroying it (orderOut). The window
 * remembers its frame and child relationships; a subsequent
 * makeKeyAndOrderFront: brings it back at the same position. Used
 * by the bubble's minimize button so the bubble can be re-shown
 * later without reconstructing it from scratch. */
extern "C" void Mixar_WindowOrderOut(void *window_handle)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    [win orderOut:nil];
  }
}


/* Show an NSWindow that was previously orderOut-ed and make it key.
 * Startup/modal code that must not affect focus uses
 * Mixar_WindowOrderFrontNoActivate below. */
extern "C" void Mixar_WindowOrderFront(void *window_handle)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    /* If a modal (splash screen, quit dialog) is active and this window
     * is a floating dock, keep it hidden — the restore callback will
     * re-show it when the modal closes. Without this, the bubble pops
     * up on top of the splash screen during startup autoshow. */
    if (mixar_suppress_floating_dock_if_needed(win)) {
      return;
    }
    [win makeKeyAndOrderFront:nil];
    /* makeKeyAndOrderFront does not generate a
     * GHOST_kEventWindowUpdate, unlike Win32's ShowWindow which posts
     * WM_PAINT.  Post the event explicitly via the window delegate so
     * Blender redraws on the next event-loop iteration. */
    mixar_force_window_redraw(win);
  }
}

extern "C" void Mixar_WindowOrderFrontNoActivate(void *window_handle)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    if (mixar_suppress_floating_dock_if_needed(win)) {
      return;
    }
    [win orderFrontRegardless];
  }
}


/* Make a window the key window (receives keyboard events). Used to
 * transfer focus back to the host viewport after showing the bubble. */
extern "C" void Mixar_WindowMakeKey(void *window_handle)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    [win makeKeyWindow];
  }
}


/* Detach a child window from its parent. Used before minimising
 * the bubble so the pill stays visible (otherwise AppKit would
 * orderOut the child along with the parent). The caller can later
 * re-attach via Mixar_WindowSetParent. */
extern "C" void Mixar_WindowDetachFromParent(void *child_handle, void *parent_handle)
{
  if (child_handle == nullptr || parent_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *child_cocoa = static_cast<GHOST_WindowCocoa *>(child_handle);
  GHOST_WindowCocoa *parent_cocoa = static_cast<GHOST_WindowCocoa *>(parent_handle);
  NSWindow *child = (NSWindow *)child_cocoa->getViewWindow();
  NSWindow *parent = (NSWindow *)parent_cocoa->getViewWindow();
  if (child == nil || parent == nil) {
    return;
  }
  @autoreleasepool {
    mixar_clear_parent_observers_for_child(child);
    [parent removeChildWindow:child];
  }
}


/* Snap a window to the bottom-centre of the main screen's visible
 * area (excluding menu bar and Dock). Used when the bubble
 * minimises so the pill jumps to a predictable position the user
 * can click to restore.
 *
 * margin_bottom is the gap (in AppKit points) between the bottom
 * of the window and the bottom of the screen's visible frame. */
/* Anchor `child` at the centre-bottom of `parent`'s frame and KEEP
 * IT THERE across every parent move and resize, including drags
 * across monitors with different DPI / origin.
 *
 * Why we can't just use addChildWindow alone: AppKit's child-window
 * mechanism translates the child's origin when the parent moves,
 * but the translation isn't reliable when the parent crosses a
 * screen boundary (the user reported the pill "changed its place"
 * after dragging Mixar to another monitor — same-monitor drags were
 * fine). It also doesn't reposition on resize: the child's origin
 * stays put while the parent grows, and the relative offset to
 * centre-bottom drifts.
 *
 * Solution: addChildWindow for ordering + close-with-parent
 * lifecycle, then attach NSWindowDidMoveNotification AND
 * NSWindowDidResizeNotification observers that re-compute and apply
 * the centre-bottom origin from the parent's CURRENT frame on every
 * change. The observer fires after AppKit's own translation, so the
 * explicit setFrameOrigin overrides any AppKit drift.
 *
 * margin_bottom: gap (in AppKit points) between the bottom of the
 * child and the bottom of the parent's frame.
 *
 * The observer is never explicitly removed; AppKit cleans it up
 * when the parent window deallocates. Acceptable leak vs the
 * complexity of tracking & removing observers across the
 * minimise→restore→re-minimise lifecycle. */
extern "C" void Mixar_WindowAnchorAtParentCentreBottom(void *child_handle,
                                                        void *parent_handle,
                                                        int margin_bottom)
{
  if (child_handle == nullptr || parent_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *child_cocoa = static_cast<GHOST_WindowCocoa *>(child_handle);
  GHOST_WindowCocoa *parent_cocoa = static_cast<GHOST_WindowCocoa *>(parent_handle);
  NSWindow *child = (NSWindow *)child_cocoa->getViewWindow();
  NSWindow *parent = (NSWindow *)parent_cocoa->getViewWindow();
  if (child == nil || parent == nil) {
    return;
  }
  @autoreleasepool {
    mixar_clear_parent_observers_for_child(child);
    [parent addChildWindow:child ordered:NSWindowAbove];

    const CGFloat margin_cg = (CGFloat)margin_bottom;

    /* Observer tokens are replaced every time the anchor target
     * changes, so old centre-bottom anchors do not keep firing after
     * minimise/restore cycles. */
    __block BOOL reposition_pending = NO;

    void (^apply_reposition)(void) = ^{
      reposition_pending = NO;
      if (![parent isVisible] || ![child isVisible]) {
        return;
      }
      NSRect parent_frame = parent.frame;
      NSRect child_frame = child.frame;
      NSPoint origin;
      origin.x = parent_frame.origin.x +
                 (parent_frame.size.width - child_frame.size.width) / 2.0;
      origin.y = parent_frame.origin.y + margin_cg;
      [child setFrameOrigin:origin];
    };
    void (^reposition)(NSNotification *) = ^(NSNotification *note) {
      if ([note.name isEqualToString:NSWindowDidResizeNotification] && [parent inLiveResize]) {
        if (!reposition_pending) {
          reposition_pending = YES;
          dispatch_async(dispatch_get_main_queue(), apply_reposition);
        }
        return;
      }
      apply_reposition();
    };

    /* During live resize, move the child on the next main-queue tick instead of
     * re-entering AppKit geometry updates from inside the resize notification. */
    NSNotificationCenter *centre = [NSNotificationCenter defaultCenter];
    id move_token = [centre addObserverForName:NSWindowDidMoveNotification
                                        object:parent
                                         queue:[NSOperationQueue mainQueue]
                                     usingBlock:reposition];
    id resize_token = [centre addObserverForName:NSWindowDidResizeNotification
                                          object:parent
                                           queue:[NSOperationQueue mainQueue]
                                      usingBlock:reposition];
    id end_resize_token = [centre addObserverForName:NSWindowDidEndLiveResizeNotification
                                              object:parent
                                               queue:[NSOperationQueue mainQueue]
                                          usingBlock:reposition];
    mixar_store_parent_observers_for_child(child, @[ move_token, resize_token, end_resize_token ]);

    /* Apply once immediately so the child is at the right place even
     * if no move/resize event fires before the user looks. */
    reposition(nil);
  }
}


/* Like Mixar_WindowSetParent but WITHOUT the
 * NSWindowDidResizeNotification observer that pulls the child to
 * "above the parent's top-left". Kept for legacy callers that need
 * the parent-child lifecycle without any auto-positioning. */
extern "C" void Mixar_WindowSetParentPlain(void *child_handle, void *parent_handle)
{
  if (child_handle == nullptr || parent_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *child_cocoa = static_cast<GHOST_WindowCocoa *>(child_handle);
  GHOST_WindowCocoa *parent_cocoa = static_cast<GHOST_WindowCocoa *>(parent_handle);
  NSWindow *child = (NSWindow *)child_cocoa->getViewWindow();
  NSWindow *parent = (NSWindow *)parent_cocoa->getViewWindow();
  if (child == nil || parent == nil) {
    return;
  }
  @autoreleasepool {
    mixar_clear_parent_observers_for_child(child);
    [parent addChildWindow:child ordered:NSWindowAbove];
    /* addChildWindow:ordered:NSWindowAbove implicitly shows the child.
     * If a modal is active, suppress the dock immediately. */
    mixar_suppress_floating_dock_if_needed(child);

    /* Maintain the child's current offset from the parent on moves and
     * resizes. Live resize updates are deferred onto the main queue so
     * they track continuously without re-entering AppKit geometry changes
     * from inside the resize notification. */
    NSRect parent_frame0 = parent.frame;
    NSRect child_frame0 = child.frame;
    __block CGFloat dx = child_frame0.origin.x - parent_frame0.origin.x;
    __block CGFloat dy = child_frame0.origin.y - parent_frame0.origin.y;

    __block BOOL reposition_pending = NO;

    void (^apply_reposition)(void) = ^{
      reposition_pending = NO;
      if (![parent isVisible] || ![child isVisible] || [parent isMiniaturized]) {
        return;
      }
      NSRect pf = parent.frame;
      NSRect cf = child.frame;
      CGFloat new_x = pf.origin.x + dx;
      CGFloat new_y = pf.origin.y + dy;
      /* Clamp child inside parent bounds so the bubble stays visible
       * when the parent shrinks (e.g. minimise to scaled-down view).
       * macOS Y is bottom-up: origin is at the bottom-left corner. */
      if (new_x + cf.size.width > pf.origin.x + pf.size.width)
        new_x = pf.origin.x + pf.size.width - cf.size.width;
      if (new_y + cf.size.height > pf.origin.y + pf.size.height)
        new_y = pf.origin.y + pf.size.height - cf.size.height;
      if (new_x < pf.origin.x) new_x = pf.origin.x;
      if (new_y < pf.origin.y) new_y = pf.origin.y;
      /* Update offsets so subsequent repositions stay clamped. */
      dx = new_x - pf.origin.x;
      dy = new_y - pf.origin.y;
      NSPoint new_origin;
      new_origin.x = new_x;
      new_origin.y = new_y;
      [child setFrameOrigin:new_origin];
    };
    void (^reposition)(NSNotification *) = ^(NSNotification *note) {
      if ([note.name isEqualToString:NSWindowDidResizeNotification] && [parent inLiveResize]) {
        if (!reposition_pending) {
          reposition_pending = YES;
          dispatch_async(dispatch_get_main_queue(), apply_reposition);
        }
        return;
      }
      apply_reposition();
    };
    NSNotificationCenter *centre = [NSNotificationCenter defaultCenter];
    id move_token = [centre addObserverForName:NSWindowDidMoveNotification
                                        object:parent
                                         queue:[NSOperationQueue mainQueue]
                                    usingBlock:reposition];
    id resize_token = [centre addObserverForName:NSWindowDidResizeNotification
                                          object:parent
                                           queue:[NSOperationQueue mainQueue]
                                      usingBlock:reposition];
    id end_resize_token = [centre addObserverForName:NSWindowDidEndLiveResizeNotification
                                              object:parent
                                               queue:[NSOperationQueue mainQueue]
                                          usingBlock:reposition];
    mixar_store_parent_observers_for_child(child, @[ move_token, resize_token, end_resize_token ]);
  }
}


/* Snap `child` to the centre-bottom of `parent`'s frame (NOT the
 * screen). Used to anchor the agent bubble's status pill inside
 * Mixar's main window when the bubble is minimised, so the pill
 * tracks Mixar's window position when the user drags it.
 *
 * margin_bottom is the gap (in AppKit points) between the bottom
 * of the child and the bottom of the parent's frame. */
extern "C" void Mixar_WindowSnapToCentreBottomOfWindow(void *child_handle,
                                                        void *parent_handle,
                                                        int margin_bottom)
{
  if (child_handle == nullptr || parent_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *child_cocoa = static_cast<GHOST_WindowCocoa *>(child_handle);
  GHOST_WindowCocoa *parent_cocoa = static_cast<GHOST_WindowCocoa *>(parent_handle);
  NSWindow *child = (NSWindow *)child_cocoa->getViewWindow();
  NSWindow *parent = (NSWindow *)parent_cocoa->getViewWindow();
  if (child == nil || parent == nil) {
    return;
  }
  @autoreleasepool {
    NSRect parent_frame = [parent frame];
    NSRect child_frame = [child frame];
    NSPoint origin;
    origin.x = parent_frame.origin.x +
               (parent_frame.size.width - child_frame.size.width) / 2.0;
    origin.y = parent_frame.origin.y + (CGFloat)margin_bottom;
    [child setFrameOrigin:origin];
  }
}


/* Animate `child`'s frame to a new (size, position) computed from
 * `parent`'s frame so it lands at the centre-bottom of the parent
 * with the given dimensions. Used by the bubble minimise op so the
 * pill GLIDES from above the bubble's top-left down to the host's
 * centre-bottom, growing from SMALL to LARGE size in the process,
 * instead of snapping in one frame.
 *
 * NSAnimationContext + the animator proxy interpolates the frame
 * on the main run loop at vsync. Animating BOTH origin and size
 * via setFrame:display: keeps the resize and the slide perfectly
 * in lockstep. */
extern "C" void Mixar_WindowAnimateFrameToCentreBottomOfWindow(
    void *child_handle,
    void *parent_handle,
    int new_width,
    int new_height,
    int margin_bottom,
    float duration)
{
  if (child_handle == nullptr || parent_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *child_cocoa = static_cast<GHOST_WindowCocoa *>(child_handle);
  GHOST_WindowCocoa *parent_cocoa = static_cast<GHOST_WindowCocoa *>(parent_handle);
  NSWindow *child = (NSWindow *)child_cocoa->getViewWindow();
  NSWindow *parent = (NSWindow *)parent_cocoa->getViewWindow();
  if (child == nil || parent == nil) {
    return;
  }
  @autoreleasepool {
    NSRect parent_frame = [parent frame];
    NSRect target;
    target.size.width = (CGFloat)new_width;
    target.size.height = (CGFloat)new_height;
    target.origin.x = parent_frame.origin.x +
                      (parent_frame.size.width - target.size.width) / 2.0;
    target.origin.y = parent_frame.origin.y + (CGFloat)margin_bottom;

    [NSAnimationContext beginGrouping];
    [[NSAnimationContext currentContext] setDuration:(CGFloat)duration];
    [[child animator] setFrame:target display:YES];
    [NSAnimationContext endGrouping];
  }
}


/* Animate `window`'s alpha to `target_alpha` over `duration` seconds.
 * Used to fade the bubble out during the minimise glide so it
 * dissolves while the pill takes its place at the centre-bottom. */
extern "C" void Mixar_WindowAnimateAlphaTo(
    void *window_handle, float target_alpha, float duration)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    [NSAnimationContext beginGrouping];
    [[NSAnimationContext currentContext] setDuration:(CGFloat)duration];
    [[win animator] setAlphaValue:(CGFloat)target_alpha];
    [NSAnimationContext endGrouping];
  }
}


/* Compute the maximum height (in points) that `window_handle` can
 * grow to without its TOP edge crossing the screen's visible-frame
 * top minus `reserve_top` points.
 *
 * Used by the agent-bubble expand op when growing the bubble: the
 * bubble is bottom-anchored, so growing extends the top upward. If
 * the bubble is already near the screen top there's no room for
 * the standard expanded size — we cap the growth to leave room for
 * the floating status pill (which sits above the bubble's top
 * edge) so it stays visible inside the screen instead of getting
 * clipped or overlapping the bubble's chrome.
 *
 * Returns 0 if the window or screen can't be queried — caller
 * should treat that as "no constraint, use the requested height". */
extern "C" int Mixar_WindowGetMaxHeightToScreenTop(
    void *window_handle, int reserve_top)
{
  if (window_handle == nullptr) {
    return 0;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return 0;
  }
  @autoreleasepool {
    NSScreen *screen = [win screen];
    if (screen == nil) {
      screen = [NSScreen mainScreen];
    }
    if (screen == nil) {
      return 0;
    }
    NSRect screen_frame = [screen visibleFrame];
    NSRect win_frame = [win frame];
    /* Max top edge the window is allowed to reach. */
    CGFloat max_top = screen_frame.origin.y + screen_frame.size.height -
                      (CGFloat)reserve_top;
    /* Bottom edge stays put when growing (bottom-anchored). */
    CGFloat bottom = win_frame.origin.y;
    CGFloat max_height = max_top - bottom;
    if (max_height < 0) {
      return 0;
    }
    return (int)max_height;
  }
}


/* Read a window's content view PIXEL dimensions (not points).
 *
 * Why this matters: NSWindow's frame is in POINTS — on Retina, a
 * 160-point window is 320 actual pixels. Blender's wmWindow.sizex
 * is in PIXELS (it's set from GHOST_GetClientBounds which uses
 * convertRectToBacking under the hood). So when our pill_set_size
 * helper writes w->sizex = 160 (points) on Retina, Blender's
 * subsequent layout pass uses HALF the actual width, the HEADER
 * region's winrct lands at the wrong width, and the
 * separator_spacer sandwich centres content against the wrong
 * axis — giving the user's "pill not centred when minimised"
 * symptom.
 *
 * Reads convertRectToBacking on the contentView's bounds, which
 * is exactly what GHOST does when reporting window dimensions to
 * Blender. */
extern "C" void Mixar_WindowGetContentPixelSize(
    void *window_handle, int *r_width, int *r_height)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    NSView *content = win.contentView;
    if (content == nil) {
      if (r_width) *r_width = 0;
      if (r_height) *r_height = 0;
      return;
    }
    NSRect bounds = [content bounds];
    NSRect backing = [content convertRectToBacking:bounds];
    if (r_width) *r_width = (int)backing.size.width;
    if (r_height) *r_height = (int)backing.size.height;
  }
}


/* Run a callback on the main queue after `delay_seconds`. Wraps
 * dispatch_after so .cc files (which can't directly call libdispatch
 * without pulling in Apple-specific headers) can schedule
 * post-animation work without tangling Objective-C into the C++
 * call site.
 *
 * Used by the minimise op to orderOut the bubble + anchor the pill
 * AFTER the slide-and-grow animation finishes. */
extern "C" void Mixar_DispatchMainAfter(float delay_seconds,
                                        void (*callback)(void *),
                                        void *user_data)
{
  if (callback == nullptr) {
    return;
  }
  dispatch_time_t when = dispatch_time(
      DISPATCH_TIME_NOW, (int64_t)(delay_seconds * NSEC_PER_SEC));
  dispatch_after(when, dispatch_get_main_queue(), ^{
    callback(user_data);
  });
}


/* Set a window's alpha value immediately (no animation). Used to
 * reset the bubble's alpha back to 1.0 after a fade-out + orderOut
 * sequence so the next show is fully opaque. */
extern "C" void Mixar_WindowSetAlpha(void *window_handle, float alpha)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    [win setAlphaValue:(CGFloat)alpha];
  }
}


extern "C" void Mixar_WindowSnapToCentreBottom(void *window_handle, int margin_bottom)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    NSScreen *screen = [win screen];
    if (screen == nil) {
      screen = [NSScreen mainScreen];
    }
    if (screen == nil) {
      return;
    }
    NSRect screen_frame = [screen visibleFrame];
    NSRect win_frame = [win frame];
    NSPoint origin;
    origin.x = screen_frame.origin.x +
               (screen_frame.size.width - win_frame.size.width) / 2.0;
    origin.y = screen_frame.origin.y + (CGFloat)margin_bottom;
    [win setFrameOrigin:origin];
  }
}


/* Set an NSWindow to fully borderless (styleMask = 0).
 *
 * Used by the floating status pill so its content view fills the
 * entire window with no title-bar zone, no traffic lights, and no
 * separate area for the OS to render chrome materials. The earlier
 * "chromeless" treatment (Mixar_WindowSetChromeless) merely hid the
 * title bar visually while leaving styleMask with TITLED — this
 * meant macOS still rendered title-bar vibrancy in that zone, which
 * showed up as a darker band across the top of the small pill
 * window (the "two background colours" the user reported).
 *
 * Borderless removes the title bar entirely, giving us a single
 * solid contentView for the pill. The pill never needs to be
 * user-movable independently (it tracks the bubble via its
 * child-window relationship), so the loss of the OS drag region is
 * intentional. */
extern "C" void Mixar_WindowSetBorderless(void *window_handle)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    /* NSWindowStyleMaskBorderless is literally 0; setting it
     * removes TITLED, FullSizeContentView, Closable, Resizable,
     * everything. The pill is read-only, so that's fine. */
    [win setStyleMask:NSWindowStyleMaskBorderless];
  }
}


/* Returns true if the window already has at least one attached
 * child window. Used by the bubble open op to detect "we already
 * created the floating pill child window for this bubble" so we
 * don't spawn a second pill on subsequent open calls (which dedup
 * the bubble itself but would otherwise create a fresh pill each
 * time). */
extern "C" bool Mixar_WindowHasChildWindow(void *parent_handle)
{
  if (parent_handle == nullptr) {
    return false;
  }
  GHOST_WindowCocoa *parent_cocoa = static_cast<GHOST_WindowCocoa *>(parent_handle);
  NSWindow *parent = (NSWindow *)parent_cocoa->getViewWindow();
  if (parent == nil) {
    return false;
  }
  @autoreleasepool {
    return parent.childWindows.count > 0;
  }
}


/* Hand off window-drag tracking to AppKit's native code path.
 *
 * Earlier revisions tried to drive the drag from Python — modal
 * operator listening for MOUSEMOVE, computing per-event delta,
 * calling Mixar_WindowMoveBy each frame. That was unbearably laggy:
 * every mouse-move event paid the full bpy.ops dispatch cost
 * (Python → RNA → C++ exec → Cocoa) and stuttered visibly under
 * load. AppKit's performWindowDragWithEvent: takes a single mouse-
 * down NSEvent and runs the entire drag loop natively until the
 * user releases — no per-frame Python overhead at all.
 *
 * We grab the current NSEvent via [NSApp currentEvent], which is
 * the mouse-down that triggered Blender's keymap dispatch into our
 * operator. If for any reason that's not the right event type, the
 * call is a no-op (AppKit ignores non-mouse-down events). */
extern "C" void Mixar_WindowBeginDrag(void *window_handle)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    NSEvent *evt = [NSApp currentEvent];

    /* Inconsistency the user reported: drag worked sometimes, did
     * nothing other times. Root cause was the strict gate on
     * currentEvent being a mouse-down. By the time our Python
     * keymap op runs (mixar.bubble_header_drag → bubble_window_begin_drag
     * → here), Blender may have already pumped a MOUSEMOVE or two
     * onto NSApp, in which case [NSApp currentEvent] is a move
     * event, not the original press — and we silently bailed.
     *
     * Fix: if currentEvent isn't a mouse-down, synthesize one at
     * the current mouse location and pass that. performWindowDragWithEvent
     * doesn't care that the event is freshly minted; it just uses
     * the location and timestamp to start tracking, then drives the
     * drag from live mouse-move events until the OS sees a mouse-up.
     * The mouse button is still physically held down at this point
     * (the op was triggered by a press), so AppKit's tracking loop
     * works correctly. */
    NSEventType wanted_types[] = {
        NSEventTypeLeftMouseDown,
        NSEventTypeRightMouseDown,
        NSEventTypeOtherMouseDown,
    };
    bool have_mouse_down = false;
    if (evt != nil) {
      NSEventType t = [evt type];
      for (size_t i = 0; i < sizeof(wanted_types) / sizeof(wanted_types[0]); i++) {
        if (t == wanted_types[i]) {
          have_mouse_down = true;
          break;
        }
      }
    }

    if (!have_mouse_down) {
      NSPoint mouse_screen = [NSEvent mouseLocation];
      NSPoint mouse_in_window = [win convertPointFromScreen:mouse_screen];
      evt = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDown
                               location:mouse_in_window
                          modifierFlags:0
                              timestamp:[[NSProcessInfo processInfo] systemUptime]
                           windowNumber:[win windowNumber]
                                context:nil
                            eventNumber:0
                             clickCount:1
                               pressure:1.0];
    }

    if (evt != nil) {
      [win performWindowDragWithEvent:evt];
    }
  }
}


/* Pin the OS-level content min size for a window. NSWindow normally
 * lets the user drag the window edges to resize it down to whatever
 * contentMinSize is set to (default {0,0}). We use this to set a
 * floor large enough that the Agent Bubble's footer (input + Mode +
 * Send) stays visible no matter how aggressively the user drags the
 * top edge — without this, native OS resize bypasses our Python
 * drag-op clamp and the input gets clipped off the bottom. */
extern "C" void Mixar_WindowSetMinContentSize(void *window_handle, int width, int height)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    const NSSize content_min_size = NSMakeSize(width, height);
    NSRect content_rect = NSMakeRect(0, 0, width, height);
    NSRect frame_rect = [win frameRectForContentRect:content_rect];
    win.contentMinSize = content_min_size;
    /* Set minSize to the frame-equivalent of the content min so the two
     * attributes stay consistent. AppKit checks whichever is larger, so
     * they must agree — otherwise the legacy minSize can override the
     * content-based floor on some macOS versions (Sonoma+). */
    win.minSize = frame_rect.size;
  }
}


extern "C" void Mixar_WindowSetMaxContentSize(void *window_handle, int width, int height)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    /* A value of 0 means "no constraint" on that axis — use FLT_MAX so
     * AppKit imposes no upper bound. */
    const CGFloat max_w = (width > 0) ? (CGFloat)width : FLT_MAX;
    const CGFloat max_h = (height > 0) ? (CGFloat)height : FLT_MAX;
    const NSSize content_max_size = NSMakeSize(max_w, max_h);
    NSRect content_rect = NSMakeRect(0, 0, max_w, max_h);
    NSRect frame_rect = [win frameRectForContentRect:content_rect];
    win.contentMaxSize = content_max_size;
    win.maxSize = frame_rect.size;
  }
}


extern "C" void Mixar_WindowSetCornerRadius(void *window_handle, float radius)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }

  const CGFloat clamped = (radius < 0.0f) ? 0.0f : (CGFloat)radius;

  @autoreleasepool {
    NSView *content = win.contentView;
    if (content != nil) {
      content.wantsLayer = YES;
      if (content.layer != nil) {
        content.layer.cornerRadius = clamped;
        content.layer.masksToBounds = (clamped > 0.0f);
      }
    }

    if (clamped > 0.0f) {
      win.opaque = NO;
      win.backgroundColor = [NSColor clearColor];
    }
    else {
      win.opaque = YES;
      win.backgroundColor = [NSColor windowBackgroundColor];
    }
  }
}


extern "C" void Mixar_WindowSetBlurBehind(void *window_handle, bool enable)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }

  @autoreleasepool {
    if (enable) {
      /* Tell the compositor this window has per-pixel alpha.
       * Wherever the GPU clear colour has alpha < 1, the window
       * becomes semi-transparent (see-through).  No blur / vibrancy —
       * just a tinted translucent background. */
      win.opaque = NO;
      win.backgroundColor = [NSColor clearColor];
    }
    else {
      win.opaque = YES;
      win.backgroundColor = [NSColor windowBackgroundColor];
    }
  }
}

extern "C" void Mixar_WindowSetChromeless(void *window_handle, bool chromeless)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  /* BlenderWindow inherits from NSWindow but is only forward-declared
   * in GHOST_WindowCocoa.hh (the @interface lives in
   * GHOST_WindowCocoa.mm). From here we only see `@class BlenderWindow;`
   * so NSWindow-specific properties like titleVisibility are invisible
   * to the compiler. Cast to NSWindow* to expose them. */
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }

  @autoreleasepool {
    if (chromeless) {
      /* Hide the title text + make the title bar transparent +
       * extend the content view to fill the entire frame
       * (NSWindowStyleMaskFullSizeContentView). Together these mean
       * the OS title bar contributes zero visible vertical space
       * above the Blender editor.
       *
       * NSWindowStyleMaskResizable enables native edge/corner resize
       * (matching the Windows WM_NCHITTEST approach).
       *
       * Side effect: the entire window surface is now the content
       * view, so OS-level window-drag from the title bar zone is
       * gone. We compensate with movableByWindowBackground = YES
       * so the user can still drag the window from any non-widget area. */
      win.titleVisibility = NSWindowTitleHidden;
      win.titlebarAppearsTransparent = YES;
      [win setStyleMask:([win styleMask] | NSWindowStyleMaskFullSizeContentView |
                                           NSWindowStyleMaskResizable)];
      win.movableByWindowBackground = YES;

      /* Hide the traffic-light buttons AFTER setStyleMask — macOS
       * can reset button visibility when the mask changes. */
      [[win standardWindowButton:NSWindowCloseButton] setHidden:YES];
      [[win standardWindowButton:NSWindowMiniaturizeButton] setHidden:YES];
      [[win standardWindowButton:NSWindowZoomButton] setHidden:YES];
    }
    else {
      [[win standardWindowButton:NSWindowCloseButton] setHidden:NO];
      [[win standardWindowButton:NSWindowMiniaturizeButton] setHidden:NO];
      [[win standardWindowButton:NSWindowZoomButton] setHidden:NO];

      win.titleVisibility = NSWindowTitleVisible;
      win.titlebarAppearsTransparent = NO;
      [win setStyleMask:([win styleMask] & ~(NSWindowStyleMaskFullSizeContentView |
                                            NSWindowStyleMaskResizable))];
      win.movableByWindowBackground = NO;
    }
  }
}

/* --------------------------------------------------------------------
 * Cocoa objects.
 */

/**
 * CocoaAppDelegate
 * ObjC object to capture applicationShouldTerminate, and send quit event
 */
@interface CocoaAppDelegate : NSObject <NSApplicationDelegate>

@property(nonatomic, readonly, assign) GHOST_SystemCocoa *systemCocoa;

- (instancetype)initWithSystemCocoa:(GHOST_SystemCocoa *)systemCocoa;
- (void)dealloc;
- (void)applicationDidFinishLaunching:(NSNotification *)aNotification;
- (BOOL)application:(NSApplication *)theApplication openFile:(NSString *)filename;
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender;
- (void)applicationWillTerminate:(NSNotification *)aNotification;
- (void)applicationWillBecomeActive:(NSNotification *)aNotification;
- (void)toggleFullScreen:(NSNotification *)notification;
- (void)windowWillClose:(NSNotification *)notification;

- (BOOL)applicationSupportsSecureRestorableState:(NSApplication *)app;

@end

@implementation CocoaAppDelegate : NSObject

@synthesize systemCocoa = system_cocoa_;

- (instancetype)initWithSystemCocoa:(GHOST_SystemCocoa *)systemCocoa
{
  self = [super init];

  if (self) {
    NSNotificationCenter *center = [NSNotificationCenter defaultCenter];
    [center addObserver:self
               selector:@selector(windowWillClose:)
                   name:NSWindowWillCloseNotification
                 object:nil];
    system_cocoa_ = systemCocoa;
  }

  return self;
}

- (void)dealloc
{
  @autoreleasepool {
    NSNotificationCenter *center = [NSNotificationCenter defaultCenter];
    [center removeObserver:self name:NSWindowWillCloseNotification object:nil];
    [super dealloc];
  }
}

- (void)applicationDidFinishLaunching:(NSNotification *)aNotification
{
  if (system_cocoa_->window_focus_) {
    /* Raise application to front, convenient when starting from the terminal
     * and important for launching the animation player. we call this after the
     * application finishes launching, as doing it earlier can make us end up
     * with a front-most window but an inactive application. */
    [NSApp activateIgnoringOtherApps:YES];
  }

  [NSEvent setMouseCoalescingEnabled:NO];
}

- (BOOL)application:(NSApplication *)theApplication openFile:(NSString *)filename
{
  return system_cocoa_->handleOpenDocumentRequest(filename);
}

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender
{
  /* TODO: implement graceful termination through Cocoa mechanism
   * to avoid session log off to be canceled. */
  /* Note that Command-Q is already handled by key-handler. */
  system_cocoa_->handleQuitRequest();
  return NSTerminateCancel;
}

/* To avoid canceling a log off process, we must use Cocoa termination process
 * And this function is the only chance to perform clean up
 * So WM_exit needs to be called directly, as the event loop will never run before termination. */
- (void)applicationWillTerminate:(NSNotification *)aNotification
{
#if 0
  WM_exit(C, EXIT_SUCCESS);
#endif
}

- (void)applicationWillBecomeActive:(NSNotification *)aNotification
{
  system_cocoa_->handleApplicationBecomeActiveEvent();
}

- (void)toggleFullScreen:(NSNotification *)notification
{
}

/* The purpose of this function is to make sure closing "About" window does not
 * leave Blender with no key windows. This is needed due to a custom event loop
 * nature of the application: for some reason only using [NSApp run] will ensure
 * correct behavior in this case.
 *
 * This is similar to an issue solved in SDL:
 *   https://bugzilla.libsdl.org/show_bug.cgi?id=1825
 *
 * Our solution is different, since we want Blender to keep track of what is
 * the key window during normal operation. In order to do so we exploit the
 * fact that "About" window is never in the orderedWindows array: we only force
 * key window from here if the closing one is not in the orderedWindows. This
 * saves lack of key windows when closing "About", but does not interfere with
 * Blender's window manager when closing Blender's windows.
 *
 * NOTE: It also receives notifiers when menus are closed on macOS 14.
 * Presumably it considers menus to be windows. */
- (void)windowWillClose:(NSNotification *)notification
{
  @autoreleasepool {
    NSWindow *closing_window = (NSWindow *)[notification object];

    if (![closing_window isKeyWindow]) {
      /* If the window wasn't key then its either none of the windows are key or another window
       * is a key. The former situation is a bit strange, but probably forcing a key window is not
       * something desirable. The latter situation is when we definitely do not want to change the
       * key window.
       *
       * Ignoring non-key windows also avoids the code which ensures ordering below from running
       * when the notifier is received for menus on macOS 14. */
      return;
    }

    const NSInteger index = [[NSApp orderedWindows] indexOfObject:closing_window];
    if (index != NSNotFound) {
      return;
    }
    /* Find first suitable window from the current space. */
    for (NSWindow *current_window in [NSApp orderedWindows]) {
      if (current_window == closing_window) {
        continue;
      }
      if (current_window.isOnActiveSpace && current_window.canBecomeKeyWindow) {
        [current_window makeKeyAndOrderFront:nil];
        return;
      }
    }
    /* If that didn't find any windows, we try to find any suitable window of the application. */
    for (NSNumber *window_number in [NSWindow windowNumbersWithOptions:0]) {
      NSWindow *current_window = [NSApp windowWithWindowNumber:[window_number integerValue]];
      if (current_window == closing_window) {
        continue;
      }
      if ([current_window canBecomeKeyWindow]) {
        [current_window makeKeyAndOrderFront:nil];
        return;
      }
    }
  }
}

/* Explicitly opt-in to the secure coding for the restorable state.
 *
 * This is something that only has affect on macOS 12+, and is implicitly
 * enabled on macOS 14.
 *
 * For the details see
 *   https://sector7.computest.nl/post/2022-08-process-injection-breaking-all-macos-security-layers-with-a-single-vulnerability/
 */
- (BOOL)applicationSupportsSecureRestorableState:(NSApplication *)app
{
  return YES;
}

@end

/* --------------------------------------------------------------------
 * Initialization / Finalization.
 */

GHOST_SystemCocoa::GHOST_SystemCocoa()
{
  modifier_mask_ = 0;
  outside_loop_event_processed_ = false;
  need_delayed_application_become_active_event_processing_ = false;

  ignore_window_sized_messages_ = false;
  ignore_momentum_scroll_ = false;
  multi_touch_scroll_ = false;
  last_warp_timestamp_ = 0;
}

GHOST_SystemCocoa::~GHOST_SystemCocoa()
{
  /* The application delegate integrates the Cocoa application with the GHOST system.
   *
   * Since the GHOST system is about to be fully destroyed release the application delegate as
   * well, so it does not point back to a freed system, forcing the delegate to be created with the
   * new GHOST system in init(). */
  @autoreleasepool {
    CocoaAppDelegate *appDelegate = (CocoaAppDelegate *)[NSApp delegate];
    if (appDelegate) {
      [NSApp setDelegate:nil];
      [appDelegate release];
    }
  }
}

GHOST_TSuccess GHOST_SystemCocoa::init()
{
  GHOST_TSuccess success = GHOST_System::init();
  if (success) {

#ifdef WITH_INPUT_NDOF
    ndof_manager_ = new GHOST_NDOFManagerCocoa(*this);
#endif

    // ProcessSerialNumber psn;

    /* Carbon stuff to move window & menu to foreground. */
#if 0
    if (!GetCurrentProcess(&psn)) {
      TransformProcessType(&psn, kProcessTransformToForegroundApplication);
      SetFrontProcess(&psn);
    }
#endif

    @autoreleasepool {
      [NSApplication sharedApplication]; /* initializes `NSApp`. */

      /* Mixar: headless sandbox children (`--background`, spawned by
       * sandbox_supervisor) still create a Cocoa system so off-screen GPU work
       * keeps working, but they must not show a Dock icon or app-switcher entry.
       * Demote them to an accessory (background) app. Detected via the env var
       * the supervisor sets only on child processes, so the user's GUI instance
       * (which lacks it) is unaffected. */
      if ([[NSProcessInfo processInfo].environment objectForKey:@"MIXAR_SANDBOX_CONNECTION_ID"]) {
        [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
      }

      if ([NSApp mainMenu] == nil) {
        NSMenu *mainMenubar = [[NSMenu alloc] init];
        NSMenuItem *menuItem;
        NSMenu *windowMenu;
        NSMenu *appMenu;

        /* Create the application menu. */
        appMenu = [[NSMenu alloc] initWithTitle:@"Mixar"];

        [appMenu addItemWithTitle:@"About Mixar"
                           action:@selector(orderFrontStandardAboutPanel:)
                    keyEquivalent:@""];
        [appMenu addItem:[NSMenuItem separatorItem]];

        menuItem = [appMenu addItemWithTitle:@"Hide Mixar"
                                      action:@selector(hide:)
                               keyEquivalent:@"h"];
        menuItem.keyEquivalentModifierMask = NSEventModifierFlagCommand;

        menuItem = [appMenu addItemWithTitle:@"Hide Others"
                                      action:@selector(hideOtherApplications:)
                               keyEquivalent:@"h"];
        menuItem.keyEquivalentModifierMask = (NSEventModifierFlagOption |
                                              NSEventModifierFlagCommand);

        [appMenu addItemWithTitle:@"Show All"
                           action:@selector(unhideAllApplications:)
                    keyEquivalent:@""];

        menuItem = [appMenu addItemWithTitle:@"Quit Mixar"
                                      action:@selector(terminate:)
                               keyEquivalent:@"q"];
        menuItem.keyEquivalentModifierMask = NSEventModifierFlagCommand;

        menuItem = [[NSMenuItem alloc] init];
        menuItem.submenu = appMenu;

        [mainMenubar addItem:menuItem];
        [menuItem release];
        [appMenu release];

        /* Create the window menu. */
        windowMenu = [[NSMenu alloc] initWithTitle:@"Window"];

        menuItem = [windowMenu addItemWithTitle:@"Minimize"
                                         action:@selector(performMiniaturize:)
                                  keyEquivalent:@"m"];
        menuItem.keyEquivalentModifierMask = NSEventModifierFlagCommand;

        [windowMenu addItemWithTitle:@"Zoom" action:@selector(performZoom:) keyEquivalent:@""];

        menuItem = [windowMenu addItemWithTitle:@"Enter Full Screen"
                                         action:@selector(toggleFullScreen:)
                                  keyEquivalent:@"f"];
        menuItem.keyEquivalentModifierMask = NSEventModifierFlagControl |
                                             NSEventModifierFlagCommand;

        menuItem = [windowMenu addItemWithTitle:@"Close"
                                         action:@selector(performClose:)
                                  keyEquivalent:@"w"];
        menuItem.keyEquivalentModifierMask = NSEventModifierFlagCommand;

        menuItem = [[NSMenuItem alloc] init];
        menuItem.submenu = windowMenu;

        [mainMenubar addItem:menuItem];
        [menuItem release];

        [NSApp setMainMenu:mainMenubar];
        [NSApp setWindowsMenu:windowMenu];
        [windowMenu release];
      }

      if ([NSApp delegate] == nil) {
        CocoaAppDelegate *appDelegate = [[CocoaAppDelegate alloc] initWithSystemCocoa:this];
        [NSApp setDelegate:appDelegate];
      }

      /* AppKit provides automatic window tabbing. Blender is a single-tabbed
       * application without a macOS tab bar, and should explicitly opt-out of this.
       * This is also controlled by the macOS user default #NSWindowTabbingEnabled. */
      NSWindow.allowsAutomaticWindowTabbing = NO;

      [NSApp finishLaunching];
    }
  }
  return success;
}

/* --------------------------------------------------------------------
 * Window management.
 */

uint64_t GHOST_SystemCocoa::getMilliSeconds() const
{
  /* For comparing to NSEvent timestamp, this particular API function matches. */
  return (uint64_t)([[NSProcessInfo processInfo] systemUptime] * 1000);
}

uint8_t GHOST_SystemCocoa::getNumDisplays() const
{
  @autoreleasepool {
    return [[NSScreen screens] count];
  }
}

void GHOST_SystemCocoa::getMainDisplayDimensions(uint32_t &width, uint32_t &height) const
{
  @autoreleasepool {
    /* Get visible frame, that is frame excluding dock and top menu bar. */
    const NSRect frame = [GHOST_WindowCocoa::getPrimaryScreen() visibleFrame];

    /* Returns max window contents (excluding title bar...). */
    const NSRect contentRect = [NSWindow
        contentRectForFrameRect:frame
                      styleMask:(NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                                 NSWindowStyleMaskMiniaturizable)];

    width = contentRect.size.width;
    height = contentRect.size.height;
  }
}

void GHOST_SystemCocoa::getAllDisplayDimensions(uint32_t &width, uint32_t &height) const
{
  /* TODO! */
  getMainDisplayDimensions(width, height);
}

GHOST_IWindow *GHOST_SystemCocoa::createWindow(const char *title,
                                               int32_t left,
                                               int32_t top,
                                               uint32_t width,
                                               uint32_t height,
                                               GHOST_TWindowState state,
                                               GHOST_GPUSettings gpu_settings,
                                               const bool /*exclusive*/,
                                               const bool is_dialog,
                                               const GHOST_IWindow *parent_window)
{
  const GHOST_ContextParams context_params = GHOST_CONTEXT_PARAMS_FROM_GPU_SETTINGS(gpu_settings);
  GHOST_IWindow *window = nullptr;
  @autoreleasepool {
    /* Get the available rect for including window contents. */
    const NSRect primaryScreenFrame = [GHOST_WindowCocoa::getPrimaryScreen() visibleFrame];
    const NSRect primaryScreenContentRect = [NSWindow
        contentRectForFrameRect:primaryScreenFrame
                      styleMask:(NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                                 NSWindowStyleMaskMiniaturizable)];

    const int32_t bottom = primaryScreenContentRect.size.height - top - height;

    window = new GHOST_WindowCocoa(this,
                                   title,
                                   left,
                                   bottom,
                                   width,
                                   height,
                                   state,
                                   gpu_settings.context_type,
                                   context_params,
                                   is_dialog,
                                   (GHOST_WindowCocoa *)parent_window,
                                   gpu_settings.preferred_device);

    if (window->getValid()) {
      /* Store the pointer to the window. */
      GHOST_ASSERT(window_manager_, "window_manager_ not initialized");
      window_manager_->addWindow(window);
      window_manager_->setActiveWindow(window);
      /* Need to tell window manager the new window is the active one
       * (Cocoa does not send the event activate upon window creation). */
      pushEvent(new GHOST_Event(getMilliSeconds(), GHOST_kEventWindowActivate, window));
      pushEvent(new GHOST_Event(getMilliSeconds(), GHOST_kEventWindowSize, window));
    }
    else {
      GHOST_PRINT("GHOST_SystemCocoa::createWindow(): window invalid\n");
      delete window;
      window = nullptr;
    }
  }
  return window;
}

/**
 * Create a new off-screen context.
 * Never explicitly delete the context, use #disposeContext() instead.
 * \return The new context (or 0 if creation failed).
 */
GHOST_IContext *GHOST_SystemCocoa::createOffscreenContext(GHOST_GPUSettings gpu_settings)
{
  const GHOST_ContextParams context_params_offscreen =
      GHOST_CONTEXT_PARAMS_FROM_GPU_SETTINGS_OFFSCREEN(gpu_settings);

  switch (gpu_settings.context_type) {
#ifdef WITH_VULKAN_BACKEND
    case GHOST_kDrawingContextTypeVulkan: {
      GHOST_Context *context = new GHOST_ContextVK(
          context_params_offscreen, nullptr, 1, 2, gpu_settings.preferred_device);
      if (context->initializeDrawingContext()) {
        return context;
      }
      delete context;
      return nullptr;
    }
#endif

#ifdef WITH_METAL_BACKEND
    case GHOST_kDrawingContextTypeMetal: {
      GHOST_Context *context = new GHOST_ContextMTL(context_params_offscreen, nullptr, nullptr);
      if (context->initializeDrawingContext()) {
        return context;
      }
      delete context;
      return nullptr;
    }
#endif

    default:
      /* Unsupported backend. */
      return nullptr;
  }
}

/**
 * Dispose of a context.
 * \param context: Pointer to the context to be disposed.
 * \return Indication of success.
 */
GHOST_TSuccess GHOST_SystemCocoa::disposeContext(GHOST_IContext *context)
{
  delete context;

  return GHOST_kSuccess;
}

GHOST_IWindow *GHOST_SystemCocoa::getWindowUnderCursor(int32_t x, int32_t y)
{
  const NSPoint scr_co = NSMakePoint(x, y);

  @autoreleasepool {
    const int windowNumberAtPoint = [NSWindow windowNumberAtPoint:scr_co
                                      belowWindowWithWindowNumber:0];
    NSWindow *nswindow = [NSApp windowWithWindowNumber:windowNumberAtPoint];

    if (nswindow == nil) {
      return nil;
    }

    return window_manager_->getWindowAssociatedWithOSWindow((const void *)nswindow);
  }
}

/**
 * \note returns coordinates in Cocoa screen coordinates.
 */
GHOST_TSuccess GHOST_SystemCocoa::getCursorPosition(int32_t &x, int32_t &y) const
{
  const NSPoint mouseLoc = [NSEvent mouseLocation];

  /* Returns the mouse location in screen coordinates. */
  x = int32_t(mouseLoc.x);
  y = int32_t(mouseLoc.y);
  return GHOST_kSuccess;
}

/**
 * \note expect Cocoa screen coordinates.
 */
GHOST_TSuccess GHOST_SystemCocoa::setCursorPosition(int32_t x, int32_t y)
{
  GHOST_WindowCocoa *window = (GHOST_WindowCocoa *)window_manager_->getActiveWindow();
  if (!window) {
    return GHOST_kFailure;
  }

  /* Cursor and mouse dissociation placed here not to interfere with continuous grab
   * (in cont. grab setMouseCursorPosition is directly called). */
  CGAssociateMouseAndMouseCursorPosition(false);
  setMouseCursorPosition(x, y);
  CGAssociateMouseAndMouseCursorPosition(true);

  /* Force mouse move event (not pushed by Cocoa). */
  pushEvent(new GHOST_EventCursor(
      getMilliSeconds(), GHOST_kEventCursorMove, window, x, y, window->GetCocoaTabletData()));
  outside_loop_event_processed_ = true;

  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_SystemCocoa::getPixelAtCursor(float r_color[3]) const
{
  @autoreleasepool {
    NSColorSampler *sampler = [[NSColorSampler alloc] init];
    __block BOOL selectCompleted = NO;
    __block BOOL samplingSucceeded = NO;

    [sampler showSamplerWithSelectionHandler:^(NSColor *selectedColor) {
      dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.1 * NSEC_PER_SEC)),
                     dispatch_get_main_queue(),
                     ^{
                       if (selectedColor != nil) {
                         NSColor *rgbColor = [selectedColor
                             colorUsingColorSpace:[NSColorSpace deviceRGBColorSpace]];
                         if (rgbColor) {
                           r_color[0] = [rgbColor redComponent];
                           r_color[1] = [rgbColor greenComponent];
                           r_color[2] = [rgbColor blueComponent];
                         }
                         samplingSucceeded = YES;
                       }
                       selectCompleted = YES;
                     });
    }];

    while (!selectCompleted) {
      [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                               beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
    }

    return samplingSucceeded ? GHOST_kSuccess : GHOST_kFailure;
  }
}

GHOST_TSuccess GHOST_SystemCocoa::setMouseCursorPosition(int32_t x, int32_t y)
{
  float xf = float(x), yf = float(y);
  GHOST_WindowCocoa *window = (GHOST_WindowCocoa *)window_manager_->getActiveWindow();
  if (!window) {
    return GHOST_kFailure;
  }

  @autoreleasepool {
    NSScreen *windowScreen = window->getScreen();
    const NSRect screenRect = windowScreen.frame;

    /* Set position relative to current screen. */
    xf -= screenRect.origin.x;
    yf -= screenRect.origin.y;

    /* Quartz Display Services uses the old coordinates (top left origin). */
    yf = screenRect.size.height - yf;

    CGDisplayMoveCursorToPoint((CGDirectDisplayID)[[[windowScreen deviceDescription]
                                   objectForKey:@"NSScreenNumber"] unsignedIntValue],
                               CGPointMake(xf, yf));

    /* See https://stackoverflow.com/a/17559012. By default, hardware events
     * will be suppressed for 500ms after a synthetic mouse event. For unknown
     * reasons CGEventSourceSetLocalEventsSuppressionInterval does not work,
     * however calling CGAssociateMouseAndMouseCursorPosition also removes the
     * delay, even if this is undocumented. */
    CGAssociateMouseAndMouseCursorPosition(true);
  }
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_SystemCocoa::getModifierKeys(GHOST_ModifierKeys &keys) const
{
  keys.set(GHOST_kModifierKeyLeftOS, (modifier_mask_ & NSEventModifierFlagCommand) ? true : false);
  keys.set(GHOST_kModifierKeyLeftAlt, (modifier_mask_ & NSEventModifierFlagOption) ? true : false);
  keys.set(GHOST_kModifierKeyLeftShift,
           (modifier_mask_ & NSEventModifierFlagShift) ? true : false);
  keys.set(GHOST_kModifierKeyLeftControl,
           (modifier_mask_ & NSEventModifierFlagControl) ? true : false);

  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_SystemCocoa::getButtons(GHOST_Buttons &buttons) const
{
  const UInt32 button_state = GetCurrentEventButtonState();

  buttons.clear();
  buttons.set(GHOST_kButtonMaskLeft, button_state & (1 << 0));
  buttons.set(GHOST_kButtonMaskRight, button_state & (1 << 1));
  buttons.set(GHOST_kButtonMaskMiddle, button_state & (1 << 2));
  buttons.set(GHOST_kButtonMaskButton4, button_state & (1 << 3));
  buttons.set(GHOST_kButtonMaskButton5, button_state & (1 << 4));
  return GHOST_kSuccess;
}

GHOST_TCapabilityFlag GHOST_SystemCocoa::getCapabilities() const
{
  return GHOST_TCapabilityFlag(
      GHOST_CAPABILITY_FLAG_ALL &
      /* NOTE: order the following flags as they they're declared in the source. */
      ~(
          /* Cocoa has no support for a primary selection clipboard. */
          GHOST_kCapabilityClipboardPrimary |
          /* Cocoa doesn't define a Hyper modifier key,
           * it's possible another modifier could be optionally used in it's place. */
          GHOST_kCapabilityKeyboardHyperKey |
          /* No support yet for RGBA mouse cursors. */
          GHOST_kCapabilityCursorRGBA |
          /* No support yet for dynamic cursor generation. */
          GHOST_kCapabilityCursorGenerator));
}

/* --------------------------------------------------------------------
 * Event handlers.
 */

/**
 * The event queue polling function
 */
bool GHOST_SystemCocoa::processEvents(bool /*waitForEvent*/)
{
  bool anyProcessed = false;
  NSEvent *event;

  /* TODO: implement timer? */
#if 0
  do {
    GHOST_TimerManager* timerMgr = getTimerManager();

    if (waitForEvent) {
      uint64_t next = timerMgr->nextFireTime();
      double timeOut;

      if (next == GHOST_kFireTimeNever) {
        timeOut = kEventDurationForever;
      }
      else {
        timeOut = (double)(next - getMilliSeconds())/1000.0;
        if (timeOut < 0.0) {
          timeOut = 0.0;
        }
      }

      ::ReceiveNextEvent(0, nullptr, timeOut, false, &event);
    }

    if (timerMgr->fireTimers(getMilliSeconds())) {
      anyProcessed = true;
    }
#endif
  do {
    @autoreleasepool {
      event = [NSApp nextEventMatchingMask:NSEventMaskAny
                                 untilDate:[NSDate distantPast]
                                    inMode:NSDefaultRunLoopMode
                                   dequeue:YES];
      if (event == nil) {
        break;
      }

      anyProcessed = true;

      /* Send event to NSApp to ensure Mac wide events are handled,
       * this will send events to BlenderWindow which will call back
       * to handleKeyEvent, handleMouseEvent and handleTabletEvent. */

      /* There is on special exception for Control+(Shift)+Tab.
       * We do not get keyDown events delivered to the view because they are
       * special hotkeys to switch between views, so override directly */

      if (event.type == NSEventTypeKeyDown && event.keyCode == kVK_Tab &&
          (event.modifierFlags & NSEventModifierFlagControl))
      {
        handleKeyEvent(event);
      }
      else {
        /* For some reason NSApp is swallowing the key up events when modifier
         * key is pressed, even if there seems to be no apparent reason to do
         * so, as a workaround we always handle these up events. */
        if (event.type == NSEventTypeKeyUp &&
            (event.modifierFlags & (NSEventModifierFlagCommand | NSEventModifierFlagOption)))
        {
          handleKeyEvent(event);
        }

        [NSApp sendEvent:event];
      }
    }
  } while (event != nil);
#if 0
  } while (waitForEvent && !anyProcessed); /* Needed only for timer implementation. */
#endif

  if (need_delayed_application_become_active_event_processing_) {
    handleApplicationBecomeActiveEvent();
  }

  if (outside_loop_event_processed_) {
    outside_loop_event_processed_ = false;
    return true;
  }

  ignore_window_sized_messages_ = false;

  return anyProcessed;
}

/* NOTE: called from #NSApplication delegate. */
GHOST_TSuccess GHOST_SystemCocoa::handleApplicationBecomeActiveEvent()
{
  @autoreleasepool {
    for (GHOST_IWindow *iwindow : window_manager_->getWindows()) {
      GHOST_WindowCocoa *window = (GHOST_WindowCocoa *)iwindow;
      if (window->isDialog()) {
        NSWindow *nswin = (NSWindow *)window->getViewWindow();
        const bool is_floating_dock =
            nswin != nil &&
            [nswin.identifier isEqualToString:kMixarFloatingDockIdentifier];
        if (is_floating_dock) {
          /* Auxiliary floating docks (Agent Bubble + pill) manage
           * their OWN visibility — do nothing here. Two reasons:
           *
           * 1. Space yank-back. The docks are pinned to Mixar's Space
           *    (Mixar_WindowBindToParentSpace). hidesOnDeactivate == YES
           *    docks (the open bubble, the minimised pill) are already
           *    auto-restored by AppKit on activation, and AppKit does it
           *    in a Space-aware way. Calling orderFront ourselves
           *    overrides that and force-switches the user back to
           *    Mixar's Space the instant they swipe to another Space —
           *    the "swiped right but got yanked back to the leftmost
           *    window" bug.
           *
           * 2. Resurrecting a minimised bubble. A dock hidden with
           *    hidesOnDeactivate == NO was intentionally orderOut'd
           *    (the bubble is collapsed to its pill). Order-fronting it
           *    pops the full chat window back open while the pill stays
           *    minimised.
           *
           * Their Z-order above the host is guaranteed by the
           * addChildWindow relationship, and making them key would
           * steal viewport focus, so there is nothing for us to do. */
          continue;
        }
        [nswin makeKeyAndOrderFront:nil];
      }
    }

    /* Update the modifiers key mask, as its status may have changed when the application
     * was not active (that is when update events are sent to another application). */
    GHOST_IWindow *window = window_manager_->getActiveWindow();

    if (!window) {
      need_delayed_application_become_active_event_processing_ = true;
      return GHOST_kFailure;
    }

    need_delayed_application_become_active_event_processing_ = false;

    const unsigned int modifiers = [[[NSApplication sharedApplication] currentEvent]
        modifierFlags];

    if ((modifiers & NSEventModifierFlagShift) != (modifier_mask_ & NSEventModifierFlagShift)) {
      pushEvent(new GHOST_EventKey(getMilliSeconds(),
                                   (modifiers & NSEventModifierFlagShift) ? GHOST_kEventKeyDown :
                                                                            GHOST_kEventKeyUp,
                                   window,
                                   GHOST_kKeyLeftShift,
                                   false));
    }
    if ((modifiers & NSEventModifierFlagControl) != (modifier_mask_ & NSEventModifierFlagControl))
    {
      pushEvent(new GHOST_EventKey(getMilliSeconds(),
                                   (modifiers & NSEventModifierFlagControl) ? GHOST_kEventKeyDown :
                                                                              GHOST_kEventKeyUp,
                                   window,
                                   GHOST_kKeyLeftControl,
                                   false));
    }
    if ((modifiers & NSEventModifierFlagOption) != (modifier_mask_ & NSEventModifierFlagOption)) {
      pushEvent(new GHOST_EventKey(getMilliSeconds(),
                                   (modifiers & NSEventModifierFlagOption) ? GHOST_kEventKeyDown :
                                                                             GHOST_kEventKeyUp,
                                   window,
                                   GHOST_kKeyLeftAlt,
                                   false));
    }
    if ((modifiers & NSEventModifierFlagCommand) != (modifier_mask_ & NSEventModifierFlagCommand))
    {
      pushEvent(new GHOST_EventKey(getMilliSeconds(),
                                   (modifiers & NSEventModifierFlagCommand) ? GHOST_kEventKeyDown :
                                                                              GHOST_kEventKeyUp,
                                   window,
                                   GHOST_kKeyLeftOS,
                                   false));
    }

    modifier_mask_ = modifiers;

    outside_loop_event_processed_ = true;
  }
  return GHOST_kSuccess;
}

/* Mark an NSWindow as a non-blocking Mixar floating dock (Agent Bubble
 * or pill).  The dock is opened with dialog=true to inherit Blender's
 * macOS child-window Z-order semantics, but it must NOT be treated as
 * a modal dialog — otherwise BlenderWindow.canBecomeKeyWindow refuses
 * to make the main window key while the dock is visible, and all
 * keystrokes (viewport shortcuts, mixie chat typing) get stuck on the
 * dock.
 *
 * We tag with NSWindow.identifier (unused elsewhere in Blender) so
 * hasDialogWindow() can skip these windows regardless of their
 * hidesOnDeactivate state, which Mixar toggles when minimising. */
extern "C" void Mixar_WindowMarkAsFloatingDock(void *window_handle)
{
  if (window_handle == nullptr) {
    return;
  }
  GHOST_WindowCocoa *cocoa_window = static_cast<GHOST_WindowCocoa *>(window_handle);
  NSWindow *win = (NSWindow *)cocoa_window->getViewWindow();
  if (win == nil) {
    return;
  }
  @autoreleasepool {
    [win setIdentifier:kMixarFloatingDockIdentifier];
    if ([win isVisible]) {
      mixar_suppress_floating_dock_if_needed(win);
    }
  }
}

extern "C" void Mixar_FloatingDocksSuppressForModal()
{
  @autoreleasepool {
    s_mixar_floating_dock_suppression_depth++;
    if (s_mixar_floating_dock_suppression_depth > 1) {
      return;
    }

    if (s_mixar_suppressed_floating_docks == nil) {
      s_mixar_suppressed_floating_docks = [[NSMutableArray alloc] init];
    }
    [s_mixar_suppressed_floating_docks removeAllObjects];

    for (NSWindow *win in [NSApp windows]) {
      if (win == nil ||
          ![win.identifier isEqualToString:kMixarFloatingDockIdentifier] ||
          ![win isVisible] ||
          [win alphaValue] < 0.01)
      {
        continue;
      }
      [s_mixar_suppressed_floating_docks addObject:win];
      [win setAlphaValue:0.0];
      [win setIgnoresMouseEvents:YES];
    }
  }
}

extern "C" void Mixar_FloatingDocksRestoreAfterModal()
{
  @autoreleasepool {
    if (s_mixar_floating_dock_suppression_depth <= 0) {
      return;
    }
    s_mixar_floating_dock_suppression_depth--;
    if (s_mixar_floating_dock_suppression_depth > 0) {
      return;
    }

    for (NSWindow *win in s_mixar_suppressed_floating_docks) {
      if (win != nil) {
        [win setAlphaValue:1.0];
        [win setIgnoresMouseEvents:NO];
        /* Content may be stale if Blender skipped drawing while the
         * window was alpha-hidden.  Force a redraw so the user sees
         * current content the moment the window becomes visible. */
        mixar_force_window_redraw(win);
      }
    }
    [s_mixar_suppressed_floating_docks removeAllObjects];
  }
}

bool GHOST_SystemCocoa::hasDialogWindow()
{
  for (GHOST_IWindow *iwindow : window_manager_->getWindows()) {
    GHOST_WindowCocoa *window = (GHOST_WindowCocoa *)iwindow;
    if (!window->isDialog()) {
      continue;
    }
    /* Mixar: skip non-blocking floating docks (Agent Bubble, pill).
     * Without this, BlenderWindow.canBecomeKeyWindow refuses to make
     * the main window key while the bubble is open — so keystrokes
     * never reach the viewport or mixie chat on macOS. The bubble is
     * tagged with Mixar_WindowMarkAsFloatingDock at creation time. */
    NSWindow *nswin = (NSWindow *)window->getViewWindow();
    if (nswin != nil &&
        [nswin.identifier isEqualToString:kMixarFloatingDockIdentifier])
    {
      continue;
    }
    return true;
  }
  return false;
}

void GHOST_SystemCocoa::notifyExternalEventProcessed()
{
  outside_loop_event_processed_ = true;
}

/* NOTE: called from #NSWindow delegate. */
GHOST_TSuccess GHOST_SystemCocoa::handleWindowEvent(GHOST_TEventType eventType,
                                                    GHOST_WindowCocoa *window)
{
  if (!validWindow(window)) {
    return GHOST_kFailure;
  }
  switch (eventType) {
    case GHOST_kEventWindowClose:
      pushEvent(new GHOST_Event(getMilliSeconds(), GHOST_kEventWindowClose, window));
      break;
    case GHOST_kEventWindowActivate:
      window_manager_->setActiveWindow(window);
      window->loadCursor(window->getCursorVisibility(), window->getCursorShape());
      pushEvent(new GHOST_Event(getMilliSeconds(), GHOST_kEventWindowActivate, window));
      break;
    case GHOST_kEventWindowDeactivate:
      window_manager_->setWindowInactive(window);
      pushEvent(new GHOST_Event(getMilliSeconds(), GHOST_kEventWindowDeactivate, window));
      break;
    case GHOST_kEventWindowUpdate:
      if (native_pixel_) {
        window->setNativePixelSize();
        pushEvent(new GHOST_Event(getMilliSeconds(), GHOST_kEventNativeResolutionChange, window));
      }
      pushEvent(new GHOST_Event(getMilliSeconds(), GHOST_kEventWindowUpdate, window));
      break;
    case GHOST_kEventWindowMove:
      pushEvent(new GHOST_Event(getMilliSeconds(), GHOST_kEventWindowMove, window));
      break;
    case GHOST_kEventWindowSize:
      if (!ignore_window_sized_messages_) {
        /* Enforce only one resize message per event loop
         * (coalescing all the live resize messages). */
        window->updateDrawingContext();
        pushEvent(new GHOST_Event(getMilliSeconds(), GHOST_kEventWindowSize, window));
        /* Mouse up event is trapped by the resizing event loop,
         * so send it anyway to the window manager. */
        pushEvent(new GHOST_EventButton(getMilliSeconds(),
                                        GHOST_kEventButtonUp,
                                        window,
                                        GHOST_kButtonMaskLeft,
                                        GHOST_TABLET_DATA_NONE));
        // ignore_window_sized_messages_ = true;
      }
      break;
    case GHOST_kEventNativeResolutionChange:

      if (native_pixel_) {
        window->setNativePixelSize();
        pushEvent(new GHOST_Event(getMilliSeconds(), GHOST_kEventNativeResolutionChange, window));
      }

    default:
      return GHOST_kFailure;
      break;
  }

  outside_loop_event_processed_ = true;
  return GHOST_kSuccess;
}

/**
 * Get the true pixel size of an NSImage object.
 * \param image: NSImage to obtain the size of.
 * \return Contained image size in pixels.
 */
static NSSize getNSImagePixelSize(NSImage *image)
{
  /* Assuming the NSImage instance only contains one single image. */
  @autoreleasepool {
    NSImageRep *imageRepresentation = [[image representations] firstObject];
    return NSMakeSize(imageRepresentation.pixelsWide, imageRepresentation.pixelsHigh);
  }
}

/**
 * Convert an NSImage to an ImBuf.
 * \param image: NSImage to convert.
 * \return Pointer to the resulting allocated ImBuf. Caller must free.
 */
static ImBuf *NSImageToImBuf(NSImage *image)
{
  const NSSize imageSize = getNSImagePixelSize(image);
  ImBuf *ibuf = IMB_allocImBuf(imageSize.width, imageSize.height, 32, IB_byte_data);

  if (!ibuf) {
    return nullptr;
  }

  @autoreleasepool {
    NSBitmapImageRep *bitmapImage = nil;
    for (NSImageRep *representation in [image representations]) {
      if ([representation isKindOfClass:[NSBitmapImageRep class]]) {
        bitmapImage = (NSBitmapImageRep *)representation;
        break;
      }
    }

    if (bitmapImage == nil || bitmapImage.bitsPerPixel != 32 || bitmapImage.isPlanar ||
        bitmapImage.bitmapFormat & (NSBitmapFormatAlphaFirst | NSBitmapFormatFloatingPointSamples))
    {
      return nullptr;
    }

    uint8_t *ibuf_data = ibuf->byte_buffer.data;
    uint8_t *bmp_data = (uint8_t *)bitmapImage.bitmapData;

    /* Vertical Flip. */
    for (int y = 0; y < imageSize.height; y++) {
      const int row_byte_count = 4 * imageSize.width;
      const int ibuf_off = (imageSize.height - y - 1) * row_byte_count;
      const int bmp_off = y * row_byte_count;
      memcpy(ibuf_data + ibuf_off, bmp_data + bmp_off, row_byte_count);
    }
  }

  return ibuf;
}

/* NOTE: called from #NSWindow subclass. */
GHOST_TSuccess GHOST_SystemCocoa::handleDraggingEvent(GHOST_TEventType eventType,
                                                      GHOST_TDragnDropTypes draggedObjectType,
                                                      GHOST_WindowCocoa *window,
                                                      int mouseX,
                                                      int mouseY,
                                                      void *data)
{
  if (!validWindow(window)) {
    return GHOST_kFailure;
  }
  switch (eventType) {
    case GHOST_kEventDraggingEntered:
    case GHOST_kEventDraggingUpdated:
    case GHOST_kEventDraggingExited:
      window->clientToScreenIntern(mouseX, mouseY, mouseX, mouseY);
      pushEvent(new GHOST_EventDragnDrop(
          getMilliSeconds(), eventType, draggedObjectType, window, mouseX, mouseY, nullptr));
      break;

    case GHOST_kEventDraggingDropDone: {
      if (!data) {
        return GHOST_kFailure;
      }

      GHOST_TDragnDropDataPtr eventData;
      @autoreleasepool {
        switch (draggedObjectType) {
          case GHOST_kDragnDropTypeFilenames: {
            NSArray *droppedArray = (NSArray *)data;

            GHOST_TStringArray *strArray = (GHOST_TStringArray *)malloc(
                sizeof(GHOST_TStringArray));
            if (!strArray) {
              return GHOST_kFailure;
            }

            strArray->count = droppedArray.count;
            if (strArray->count == 0) {
              free(strArray);
              return GHOST_kFailure;
            }

            strArray->strings = (uint8_t **)malloc(strArray->count * sizeof(uint8_t *));

            for (int i = 0; i < strArray->count; i++) {
              NSString *droppedStr = [droppedArray objectAtIndex:i];
              const size_t pastedTextSize = [droppedStr
                  lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
              uint8_t *temp_buff = (uint8_t *)malloc(pastedTextSize + 1);

              if (!temp_buff) {
                strArray->count = i;
                break;
              }

              memcpy(temp_buff,
                     [droppedStr cStringUsingEncoding:NSUTF8StringEncoding],
                     pastedTextSize);
              temp_buff[pastedTextSize] = '\0';

              strArray->strings[i] = temp_buff;
            }

            eventData = static_cast<GHOST_TDragnDropDataPtr>(strArray);
            break;
          }
          case GHOST_kDragnDropTypeString: {
            NSString *droppedStr = (NSString *)data;
            const size_t pastedTextSize = [droppedStr
                lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
            uint8_t *temp_buff = (uint8_t *)malloc(pastedTextSize + 1);

            if (temp_buff == nullptr) {
              return GHOST_kFailure;
            }

            memcpy(
                temp_buff, [droppedStr cStringUsingEncoding:NSUTF8StringEncoding], pastedTextSize);
            temp_buff[pastedTextSize] = '\0';

            eventData = static_cast<GHOST_TDragnDropDataPtr>(temp_buff);
            break;
          }
          case GHOST_kDragnDropTypeBitmap: {
            NSImage *droppedImg = static_cast<NSImage *>(data);
            ImBuf *ibuf = NSImageToImBuf(droppedImg);

            eventData = static_cast<GHOST_TDragnDropDataPtr>(ibuf);

            [droppedImg release];
            break;
          }
          default:
            return GHOST_kFailure;
            break;
        }
      }

      window->clientToScreenIntern(mouseX, mouseY, mouseX, mouseY);
      pushEvent(new GHOST_EventDragnDrop(
          getMilliSeconds(), eventType, draggedObjectType, window, mouseX, mouseY, eventData));

      break;
    }
    default:
      return GHOST_kFailure;
  }
  outside_loop_event_processed_ = true;
  return GHOST_kSuccess;
}

void GHOST_SystemCocoa::handleQuitRequest()
{
  GHOST_Window *window = (GHOST_Window *)window_manager_->getActiveWindow();

  /* Discard quit event if we are in cursor grab sequence. */
  if (window && window->getCursorGrabModeIsWarp()) {
    return;
  }

  /* Push the event to Blender so it can open a dialog if needed. */
  pushEvent(new GHOST_Event(getMilliSeconds(), GHOST_kEventQuitRequest, window));
  outside_loop_event_processed_ = true;
}

bool GHOST_SystemCocoa::handleOpenDocumentRequest(void *filepathStr)
{
  NSString *filepath = (NSString *)filepathStr;

  /* Check for blender opened windows and make the front-most key.
   * In case blender is minimized, opened on another desktop space,
   * or in full-screen mode. */
  @autoreleasepool {
    NSArray *windowsList = [NSApp orderedWindows];
    if ([windowsList count]) {
      [[windowsList objectAtIndex:0] makeKeyAndOrderFront:nil];
    }

    GHOST_Window *window = window_manager_->getWindows().empty() ?
                               nullptr :
                               (GHOST_Window *)window_manager_->getWindows().front();

    if (!window) {
      return NO;
    }

    /* Discard event if we are in cursor grab sequence,
     * it'll lead to "stuck cursor" situation if the alert panel is raised. */
    if (window && window->getCursorGrabModeIsWarp()) {
      return NO;
    }

    const size_t filenameTextSize = [filepath lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
    char *temp_buff = (char *)malloc(filenameTextSize + 1);

    if (temp_buff == nullptr) {
      return GHOST_kFailure;
    }

    memcpy(temp_buff, [filepath cStringUsingEncoding:NSUTF8StringEncoding], filenameTextSize);
    temp_buff[filenameTextSize] = '\0';

    pushEvent(new GHOST_EventString(getMilliSeconds(),
                                    GHOST_kEventOpenMainFile,
                                    window,
                                    static_cast<GHOST_TEventDataPtr>(temp_buff)));
  }
  return YES;
}

GHOST_TSuccess GHOST_SystemCocoa::handleTabletEvent(void *eventPtr, short eventType)
{
  NSEvent *event = (NSEvent *)eventPtr;

  GHOST_IWindow *window = window_manager_->getWindowAssociatedWithOSWindow(
      (const void *)event.window);
  if (!window) {
    // printf("\nW failure for event 0x%x",event.type);
    return GHOST_kFailure;
  }

  GHOST_TabletData &ct = ((GHOST_WindowCocoa *)window)->GetCocoaTabletData();

  switch (eventType) {
    case NSEventTypeTabletPoint:
      /* workaround 2 corner-cases:
       * 1. if event.isEnteringProximity was not triggered since program-start.
       * 2. device is not sending event.pointingDeviceType, due no eraser. */
      if (ct.Active == GHOST_kTabletModeNone) {
        ct.Active = GHOST_kTabletModeStylus;
      }

      ct.Pressure = event.pressure;
      /* Range: -1 (left) to 1 (right). */
      ct.Xtilt = event.tilt.x;
      /* On macOS, the y tilt behavior is inverted from what we expect: negative
       * meaning a tilt toward the user, positive meaning away from the user.
       * Convert to what Blender expects: -1.0 (away from user) to +1.0 (toward user). */
      ct.Ytilt = -event.tilt.y;
      break;

    case NSEventTypeTabletProximity:
      /* Reset tablet data when device enters proximity or leaves. */
      ct = GHOST_TABLET_DATA_NONE;
      if (event.isEnteringProximity) {
        /* Pointer is entering tablet area proximity. */
        switch (event.pointingDeviceType) {
          case NSPointingDeviceTypePen:
            ct.Active = GHOST_kTabletModeStylus;
            break;
          case NSPointingDeviceTypeEraser:
            ct.Active = GHOST_kTabletModeEraser;
            break;
          case NSPointingDeviceTypeCursor:
          case NSPointingDeviceTypeUnknown:
          default:
            break;
        }
      }
      break;

    default:
      GHOST_ASSERT(FALSE, "GHOST_SystemCocoa::handleTabletEvent : unknown event received");
      return GHOST_kFailure;
      break;
  }
  return GHOST_kSuccess;
}

bool GHOST_SystemCocoa::handleTabletEvent(void *eventPtr)
{
  NSEvent *event = (NSEvent *)eventPtr;

  switch (event.subtype) {
    case NSEventSubtypeTabletPoint:
      handleTabletEvent(eventPtr, NSEventTypeTabletPoint);
      return true;
    case NSEventSubtypeTabletProximity:
      handleTabletEvent(eventPtr, NSEventTypeTabletProximity);
      return true;
    default:
      /* No tablet event included: do nothing. */
      return false;
  }
}

GHOST_TSuccess GHOST_SystemCocoa::handleMouseEvent(void *eventPtr)
{
  NSEvent *event = (NSEvent *)eventPtr;

  /* event.window returns other windows if mouse-over, that's OSX input standard
   * however, if mouse exits window(s), the windows become inactive, until you click.
   * We then fall back to the active window from ghost. */
  GHOST_WindowCocoa *window = (GHOST_WindowCocoa *)window_manager_
                                  ->getWindowAssociatedWithOSWindow((const void *)event.window);
  if (!window) {
    window = (GHOST_WindowCocoa *)window_manager_->getActiveWindow();
    if (!window) {
      // printf("\nW failure for event 0x%x", event.type);
      return GHOST_kFailure;
    }
  }

  switch (event.type) {
    case NSEventTypeLeftMouseDown:
      handleTabletEvent(event); /* Update window tablet state to be included in event. */
      pushEvent(new GHOST_EventButton(event.timestamp * 1000,
                                      GHOST_kEventButtonDown,
                                      window,
                                      GHOST_kButtonMaskLeft,
                                      window->GetCocoaTabletData()));
      break;
    case NSEventTypeRightMouseDown:
      handleTabletEvent(event); /* Update window tablet state to be included in event. */
      pushEvent(new GHOST_EventButton(event.timestamp * 1000,
                                      GHOST_kEventButtonDown,
                                      window,
                                      GHOST_kButtonMaskRight,
                                      window->GetCocoaTabletData()));
      break;
    case NSEventTypeOtherMouseDown:
      handleTabletEvent(event); /* Handle tablet events combined with mouse events. */
      pushEvent(new GHOST_EventButton(event.timestamp * 1000,
                                      GHOST_kEventButtonDown,
                                      window,
                                      convertButton(event.buttonNumber),
                                      window->GetCocoaTabletData()));
      break;
    case NSEventTypeLeftMouseUp:
      handleTabletEvent(event); /* Update window tablet state to be included in event. */
      pushEvent(new GHOST_EventButton(event.timestamp * 1000,
                                      GHOST_kEventButtonUp,
                                      window,
                                      GHOST_kButtonMaskLeft,
                                      window->GetCocoaTabletData()));
      break;
    case NSEventTypeRightMouseUp:
      handleTabletEvent(event); /* Update window tablet state to be included in event. */
      pushEvent(new GHOST_EventButton(event.timestamp * 1000,
                                      GHOST_kEventButtonUp,
                                      window,
                                      GHOST_kButtonMaskRight,
                                      window->GetCocoaTabletData()));
      break;
    case NSEventTypeOtherMouseUp:
      handleTabletEvent(event); /* Update window tablet state to be included in event. */
      pushEvent(new GHOST_EventButton(event.timestamp * 1000,
                                      GHOST_kEventButtonUp,
                                      window,
                                      convertButton(event.buttonNumber),
                                      window->GetCocoaTabletData()));
      break;
    case NSEventTypeLeftMouseDragged:
    case NSEventTypeRightMouseDragged:
    case NSEventTypeOtherMouseDragged:
      handleTabletEvent(event); /* Update window tablet state to be included in event. */

    case NSEventTypeMouseMoved: {
      /* TODO: CHECK IF THIS IS A TABLET EVENT */
      bool is_tablet = false;

      if (window->getCursorGrabModeIsWarp() && !is_tablet) {
        /* Wrap cursor at area/window boundaries. */
        GHOST_Rect bounds;
        if (window->getCursorGrabBounds(bounds) == GHOST_kFailure) {
          /* Fall back to window bounds. */
          window->getClientBounds(bounds);
        }

        GHOST_Rect corrected_bounds;
        /* Wrapping bounds are in window local coordinates, using GHOST (top-left) origin. */
        if (window->getCursorGrabMode() == GHOST_kGrabHide) {
          /* If the cursor is hidden, use the entire window. */
          corrected_bounds.t_ = 0;
          corrected_bounds.l_ = 0;

          NSWindow *cocoa_window = (NSWindow *)window->getOSWindow();
          const NSSize frame_size = cocoa_window.frame.size;

          corrected_bounds.b_ = frame_size.height;
          corrected_bounds.r_ = frame_size.width;
        }
        else {
          /* If the cursor is visible, use custom grab bounds provided in Cocoa bottom-left origin.
           * Flip them to use a GHOST top-left origin. */
          GHOST_Rect window_bounds;
          window->getClientBounds(window_bounds);
          window->screenToClient(bounds.l_, bounds.b_, corrected_bounds.l_, corrected_bounds.t_);
          window->screenToClient(bounds.r_, bounds.t_, corrected_bounds.r_, corrected_bounds.b_);

          corrected_bounds.b_ = (window_bounds.b_ - window_bounds.t_) - corrected_bounds.b_;
          corrected_bounds.t_ = (window_bounds.b_ - window_bounds.t_) - corrected_bounds.t_;
        }

        /* Clip the grabbing bounds to the current monitor bounds to prevent the cursor from
         * getting stuck at the edge of the screen. First compute the visible window frame: */
        NSWindow *cocoa_window = (NSWindow *)window->getOSWindow();
        NSRect screen_visible_frame = window->getScreen().visibleFrame;
        NSRect window_visible_frame = NSIntersectionRect(cocoa_window.frame, screen_visible_frame);
        NSRect local_visible_frame = [cocoa_window convertRectFromScreen:window_visible_frame];

        GHOST_Rect visible_rect;
        visible_rect.l_ = local_visible_frame.origin.x;
        visible_rect.t_ = local_visible_frame.origin.y;
        visible_rect.r_ = local_visible_frame.origin.x + local_visible_frame.size.width;
        visible_rect.b_ = local_visible_frame.origin.y + local_visible_frame.size.height;

        /* Then clip the corrected bound using the visible window rect. */
        visible_rect.clip(corrected_bounds);

        /* Get accumulation from previous mouse warps. */
        int32_t x_accum, y_accum;
        window->getCursorGrabAccum(x_accum, y_accum);

        /* Get the current software mouse pointer location, theoretically unaffected by pending
         * events that may still be referring to a location before warping. In practice extra
         * logic still need to be used to prevent interferences from stale events. */
        const NSPoint mousePos = event.window.mouseLocationOutsideOfEventStream;
        /* Casting. */
        const int32_t x_mouse = mousePos.x;
        const int32_t y_mouse = mousePos.y;

        /* Warp mouse cursor if needed. */
        int32_t warped_x_mouse = x_mouse;
        int32_t warped_y_mouse = y_mouse;
        corrected_bounds.wrapPoint(warped_x_mouse, warped_y_mouse, 4, window->getCursorGrabAxis());

        /* Set new cursor position. */
        if (x_mouse != warped_x_mouse || y_mouse != warped_y_mouse) {
          /* After warping, we can still receive unwrapped mouse that occured slightly before or
           * after the current event at close timestamps, causing the wrapping to be applied a
           * second time, leading to a visual jump. Ignore these events by returning early.
           * Using a small empirical future covering threshold, see PR #148158 for details. */
          const NSTimeInterval timestamp = event.timestamp;
          const NSTimeInterval stale_event_threshold = 0.003;
          if (timestamp < (last_warp_timestamp_ + stale_event_threshold)) {
            break;
          }

          int32_t warped_x, warped_y;
          window->clientToScreenIntern(warped_x_mouse, warped_y_mouse, warped_x, warped_y);
          setMouseCursorPosition(warped_x, warped_y); /* wrap */
          window->setCursorGrabAccum(x_accum + (x_mouse - warped_x_mouse),
                                     y_accum + (y_mouse - warped_y_mouse));

          /* This is the current time that matches NSEvent timestamp. */
          last_warp_timestamp_ = [[NSProcessInfo processInfo] systemUptime];
        }

        /* Generate event. */
        int32_t x, y;
        window->clientToScreenIntern(x_mouse + x_accum, y_mouse + y_accum, x, y);
        pushEvent(new GHOST_EventCursor(event.timestamp * 1000,
                                        GHOST_kEventCursorMove,
                                        window,
                                        x,
                                        y,
                                        window->GetCocoaTabletData()));
      }
      else {
        /* Normal cursor operation: send mouse position in window. */
        const NSPoint mousePos = event.locationInWindow;
        int32_t x, y;

        window->clientToScreenIntern(mousePos.x, mousePos.y, x, y);
        pushEvent(new GHOST_EventCursor(event.timestamp * 1000,
                                        GHOST_kEventCursorMove,
                                        window,
                                        x,
                                        y,
                                        window->GetCocoaTabletData()));
      }
      break;
    }
    case NSEventTypeScrollWheel: {
      const NSEventPhase momentumPhase = event.momentumPhase;
      const NSEventPhase phase = event.phase;

      /* when pressing a key while momentum scrolling continues after
       * lifting fingers off the trackpad, the action can unexpectedly
       * change from e.g. scrolling to zooming. this works around the
       * issue by ignoring momentum scroll after a key press */
      if (momentumPhase) {
        if (ignore_momentum_scroll_) {
          break;
        }
      }
      else {
        ignore_momentum_scroll_ = false;
      }

      /* we assume phases are only set for gestures from trackpad or magic
       * mouse events. note that using tablet at the same time may not work
       * since this is a static variable */
      if (phase == NSEventPhaseBegan && multitouch_gestures_) {
        multi_touch_scroll_ = true;
      }
      else if (phase == NSEventPhaseEnded) {
        multi_touch_scroll_ = false;
      }

      /* Standard scroll-wheel case, if no swiping happened,
       * and no momentum (kinetic scroll) works. */
      if (!multi_touch_scroll_ && momentumPhase == NSEventPhaseNone) {
        /* Horizontal scrolling. */
        if (event.deltaX != 0.0) {
          const int32_t delta = event.deltaX > 0.0 ? 1 : -1;
          /* On macOS, shift + vertical scroll events will be transformed into shift + horizontal
           * events by the OS input layer. Counteract this behavior by transforming them back into
           * shift + vertical scroll event. See PR #148122 for more details. */
          const GHOST_TEventWheelAxis direction = modifier_mask_ & NSEventModifierFlagShift ?
                                                      GHOST_kEventWheelAxisVertical :
                                                      GHOST_kEventWheelAxisHorizontal;

          pushEvent(new GHOST_EventWheel(event.timestamp * 1000, window, direction, delta));
        }
        /* Vertical scrolling. */
        if (event.deltaY != 0.0) {
          const int32_t delta = event.deltaY > 0.0 ? 1 : -1;
          pushEvent(new GHOST_EventWheel(
              event.timestamp * 1000, window, GHOST_kEventWheelAxisVertical, delta));
        }
      }
      else {
        const NSPoint mousePos = event.locationInWindow;

        /* with 10.7 nice scrolling deltas are supported */
        double dx = event.scrollingDeltaX;
        double dy = event.scrollingDeltaY;

        /* However, WACOM tablet (intuos5) needs old deltas,
         * it then has momentum and phase at zero. */
        if (phase == NSEventPhaseNone && momentumPhase == NSEventPhaseNone) {
          dx = event.deltaX;
          dy = event.deltaY;
        }

        int32_t x, y;
        window->clientToScreenIntern(mousePos.x, mousePos.y, x, y);

        BlenderWindow *view_window = (BlenderWindow *)window->getOSWindow();

        @autoreleasepool {
          const NSPoint delta = [[view_window contentView]
              convertPointToBacking:NSMakePoint(dx, dy)];
          pushEvent(new GHOST_EventTrackpad(event.timestamp * 1000,
                                            window,
                                            GHOST_kTrackpadEventScroll,
                                            x,
                                            y,
                                            delta.x,
                                            delta.y,
                                            event.isDirectionInvertedFromDevice));
        }
      }
      break;
    }
    case NSEventTypeMagnify: {
      const NSPoint mousePos = event.locationInWindow;
      int32_t x, y;
      window->clientToScreenIntern(mousePos.x, mousePos.y, x, y);
      pushEvent(new GHOST_EventTrackpad(event.timestamp * 1000,
                                        window,
                                        GHOST_kTrackpadEventMagnify,
                                        x,
                                        y,
                                        event.magnification * 125.0 + 0.1,
                                        0,
                                        false));
      break;
    }
    case NSEventTypeSmartMagnify: {
      const NSPoint mousePos = event.locationInWindow;
      int32_t x, y;
      window->clientToScreenIntern(mousePos.x, mousePos.y, x, y);
      pushEvent(new GHOST_EventTrackpad(
          event.timestamp * 1000, window, GHOST_kTrackpadEventSmartMagnify, x, y, 0, 0, false));
      break;
    }
    case NSEventTypeRotate: {
      const NSPoint mousePos = event.locationInWindow;
      int32_t x, y;
      window->clientToScreenIntern(mousePos.x, mousePos.y, x, y);
      pushEvent(new GHOST_EventTrackpad(event.timestamp * 1000,
                                        window,
                                        GHOST_kTrackpadEventRotate,
                                        x,
                                        y,
                                        event.rotation * -5.0,
                                        0,
                                        false));
    }
    default:
      return GHOST_kFailure;
      break;
  }
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_SystemCocoa::handleKeyEvent(void *eventPtr)
{
  NSEvent *event = (NSEvent *)eventPtr;
  GHOST_IWindow *window = window_manager_->getWindowAssociatedWithOSWindow(
      (const void *)event.window);

  if (!window) {
    // printf("\nW failure for event 0x%x",event.type);
    return GHOST_kFailure;
  }

  switch (event.type) {
    case NSEventTypeKeyDown:
    case NSEventTypeKeyUp: {
      /* Returns an empty string for dead keys. */
      GHOST_TKey keyCode;
      char utf8_buf[6] = {'\0'};

      @autoreleasepool {
        NSString *charsIgnoringModifiers = event.charactersIgnoringModifiers;
        if (charsIgnoringModifiers.length > 0) {
          keyCode = convertKey(event.keyCode, [charsIgnoringModifiers characterAtIndex:0]);
        }
        else {
          keyCode = convertKey(event.keyCode, 0);
        }

        NSString *characters = event.characters;
        if ([characters length] > 0) {
          NSData *convertedCharacters = [characters dataUsingEncoding:NSUTF8StringEncoding];

          for (int x = 0; x < convertedCharacters.length; x++) {
            utf8_buf[x] = ((char *)convertedCharacters.bytes)[x];
          }
        }
      }

      /* Arrow keys should not have UTF8. */
      if ((keyCode >= GHOST_kKeyLeftArrow) && (keyCode <= GHOST_kKeyDownArrow)) {
        utf8_buf[0] = '\0';
      }

      /* F-keys should not have UTF8. */
      if ((keyCode >= GHOST_kKeyF1) && (keyCode <= GHOST_kKeyF20)) {
        utf8_buf[0] = '\0';
      }

      /* no text with command key pressed */
      if (modifier_mask_ & NSEventModifierFlagCommand) {
        utf8_buf[0] = '\0';
      }

      if ((keyCode == GHOST_kKeyQ) && (modifier_mask_ & NSEventModifierFlagCommand)) {
        break; /* Command-Q is directly handled by Cocoa. */
      }

      if (event.type == NSEventTypeKeyDown) {
        pushEvent(new GHOST_EventKey(event.timestamp * 1000,
                                     GHOST_kEventKeyDown,
                                     window,
                                     keyCode,
                                     event.isARepeat,
                                     utf8_buf));
#if 0
        printf("Key down rawCode=0x%x charsIgnoringModifiers=%c keyCode=%u utf8=%s\n",
               event.keyCode,
               charsIgnoringModifiers.length > 0 ? [charsIgnoringModifiers characterAtIndex:0] :
                                                     ' ',
               keyCode,
               utf8_buf);
#endif
      }
      else {
        pushEvent(new GHOST_EventKey(
            event.timestamp * 1000, GHOST_kEventKeyUp, window, keyCode, false, nullptr));
#if 0
        printf("Key up rawCode=0x%x charsIgnoringModifiers=%c keyCode=%u utf8=%s\n",
               event.keyCode,
               charsIgnoringModifiers.length > 0 ? [charsIgnoringModifiers characterAtIndex:0] :
                                                     ' ',
               keyCode,
               utf8_buf);
#endif
      }
      ignore_momentum_scroll_ = true;
      break;
    }
    case NSEventTypeFlagsChanged: {
      const unsigned int modifiers = event.modifierFlags;

      if ((modifiers & NSEventModifierFlagShift) != (modifier_mask_ & NSEventModifierFlagShift)) {
        pushEvent(new GHOST_EventKey(event.timestamp * 1000,
                                     (modifiers & NSEventModifierFlagShift) ? GHOST_kEventKeyDown :
                                                                              GHOST_kEventKeyUp,
                                     window,
                                     GHOST_kKeyLeftShift,
                                     false));
      }
      if ((modifiers & NSEventModifierFlagControl) !=
          (modifier_mask_ & NSEventModifierFlagControl))
      {
        pushEvent(new GHOST_EventKey(
            event.timestamp * 1000,
            (modifiers & NSEventModifierFlagControl) ? GHOST_kEventKeyDown : GHOST_kEventKeyUp,
            window,
            GHOST_kKeyLeftControl,
            false));
      }
      if ((modifiers & NSEventModifierFlagOption) != (modifier_mask_ & NSEventModifierFlagOption))
      {
        pushEvent(new GHOST_EventKey(
            event.timestamp * 1000,
            (modifiers & NSEventModifierFlagOption) ? GHOST_kEventKeyDown : GHOST_kEventKeyUp,
            window,
            GHOST_kKeyLeftAlt,
            false));
      }
      if ((modifiers & NSEventModifierFlagCommand) !=
          (modifier_mask_ & NSEventModifierFlagCommand))
      {
        pushEvent(new GHOST_EventKey(
            event.timestamp * 1000,
            (modifiers & NSEventModifierFlagCommand) ? GHOST_kEventKeyDown : GHOST_kEventKeyUp,
            window,
            GHOST_kKeyLeftOS,
            false));
      }

      modifier_mask_ = modifiers;
      ignore_momentum_scroll_ = true;
      break;
    }

    default:
      return GHOST_kFailure;
      break;
  }
  return GHOST_kSuccess;
}

/* --------------------------------------------------------------------
 * Clipboard get/set.
 */

char *GHOST_SystemCocoa::getClipboard(bool /*selection*/) const
{
  @autoreleasepool {
    NSPasteboard *pasteBoard = [NSPasteboard generalPasteboard];
    NSString *textPasted = [pasteBoard stringForType:NSPasteboardTypeString];

    if (textPasted == nil) {
      return nullptr;
    }

    const size_t pastedTextSize = [textPasted lengthOfBytesUsingEncoding:NSUTF8StringEncoding];

    char *temp_buff = (char *)malloc(pastedTextSize + 1);

    if (temp_buff == nullptr) {
      return nullptr;
    }

    memcpy(temp_buff, [textPasted cStringUsingEncoding:NSUTF8StringEncoding], pastedTextSize);
    temp_buff[pastedTextSize] = '\0';

    if (temp_buff) {
      return temp_buff;
    }
  }
  return nullptr;
}

void GHOST_SystemCocoa::putClipboard(const char *buffer, bool selection) const
{
  if (selection) {
    return; /* For copying the selection, used on X11. */
  }

  @autoreleasepool {
    NSPasteboard *pasteBoard = NSPasteboard.generalPasteboard;
    [pasteBoard declareTypes:@[ NSPasteboardTypeString ] owner:nil];

    NSString *textToCopy = [NSString stringWithCString:buffer encoding:NSUTF8StringEncoding];
    [pasteBoard setString:textToCopy forType:NSPasteboardTypeString];
  }
}

static NSURL *NSPasteboardGetImageFile()
{
  NSURL *pasteboardImageFile = nil;

  @autoreleasepool {
    NSPasteboard *pasteboard = [NSPasteboard generalPasteboard];
    NSDictionary *pasteboardFilteringOptions = @{
      NSPasteboardURLReadingFileURLsOnlyKey : @YES,
      NSPasteboardURLReadingContentsConformToTypesKey : [NSImage imageTypes]
    };

    NSArray *pasteboardMatches = [pasteboard readObjectsForClasses:@[ [NSURL class] ]
                                                           options:pasteboardFilteringOptions];

    if (!pasteboardMatches || !pasteboardMatches.count) {
      return nil;
    }

    pasteboardImageFile = [[pasteboardMatches firstObject] copy];
  }

  return [pasteboardImageFile autorelease];
}

GHOST_TSuccess GHOST_SystemCocoa::hasClipboardImage() const
{
  @autoreleasepool {
    NSPasteboard *pasteboard = [NSPasteboard generalPasteboard];
    NSArray *supportedTypes = [NSArray
        arrayWithObjects:NSPasteboardTypeFileURL, NSPasteboardTypeTIFF, NSPasteboardTypePNG, nil];

    NSPasteboardType availableType = [pasteboard availableTypeFromArray:supportedTypes];

    if (!availableType) {
      return GHOST_kFailure;
    }

    /* If we got a file, ensure it's an image file. */
    if ([pasteboard availableTypeFromArray:@[ NSPasteboardTypeFileURL ]] &&
        NSPasteboardGetImageFile() == nil)
    {
      return GHOST_kFailure;
    }
  }

  return GHOST_kSuccess;
}

uint *GHOST_SystemCocoa::getClipboardImage(int *r_width, int *r_height) const
{
  if (!hasClipboardImage()) {
    return nullptr;
  }

  @autoreleasepool {
    NSPasteboard *pasteboard = [NSPasteboard generalPasteboard];

    NSImage *clipboardImage = nil;
    if (NSURL *pasteboardImageFile = NSPasteboardGetImageFile(); pasteboardImageFile != nil) {
      /* Image file. */
      clipboardImage = [[[NSImage alloc] initWithContentsOfURL:pasteboardImageFile] autorelease];
    }
    else {
      /* Raw image data. */
      clipboardImage = [[[NSImage alloc] initWithPasteboard:pasteboard] autorelease];
    }

    if (!clipboardImage) {
      return nullptr;
    }

    ImBuf *ibuf = NSImageToImBuf(clipboardImage);
    const NSSize clipboardImageSize = getNSImagePixelSize(clipboardImage);

    if (ibuf) {
      const size_t byteCount = clipboardImageSize.width * clipboardImageSize.height * 4;
      uint *rgba = (uint *)malloc(byteCount);

      if (!rgba) {
        IMB_freeImBuf(ibuf);
        return nullptr;
      }

      memcpy(rgba, ibuf->byte_buffer.data, byteCount);
      IMB_freeImBuf(ibuf);

      *r_width = clipboardImageSize.width;
      *r_height = clipboardImageSize.height;

      return rgba;
    }
  }

  return nullptr;
}

GHOST_TSuccess GHOST_SystemCocoa::putClipboardImage(uint *rgba, int width, int height) const
{
  @autoreleasepool {
    const size_t rowByteCount = width * 4;

    NSBitmapImageRep *imageRep = [[NSBitmapImageRep alloc]
        initWithBitmapDataPlanes:nil
                      pixelsWide:width
                      pixelsHigh:height
                   bitsPerSample:8
                 samplesPerPixel:4
                        hasAlpha:YES
                        isPlanar:NO
                  colorSpaceName:NSDeviceRGBColorSpace
                     bytesPerRow:rowByteCount
                    bitsPerPixel:32];

    /* Copy the source image data to imageRep, flipping it vertically. */
    uint8_t *srcBuffer = reinterpret_cast<uint8_t *>(rgba);
    uint8_t *dstBuffer = static_cast<uint8_t *>([imageRep bitmapData]);

    for (int y = 0; y < height; y++) {
      const int dstOff = (height - y - 1) * rowByteCount;
      const int srcOff = y * rowByteCount;
      memcpy(dstBuffer + dstOff, srcBuffer + srcOff, rowByteCount);
    }

    NSImage *image = [[[NSImage alloc] initWithSize:NSMakeSize(width, height)] autorelease];
    [image addRepresentation:imageRep];

    NSPasteboard *pasteboard = [NSPasteboard generalPasteboard];
    [pasteboard clearContents];

    BOOL pasteSuccess = [pasteboard writeObjects:@[ image ]];

    if (!pasteSuccess) {
      return GHOST_kFailure;
    }
  }
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_SystemCocoa::showMessageBox(const char *title,
                                                 const char *message,
                                                 const char *help_label,
                                                 const char *continue_label,
                                                 const char *link,
                                                 GHOST_DialogOptions dialog_options) const
{
  @autoreleasepool {
    NSAlert *alert = [[[NSAlert alloc] init] autorelease];
    alert.accessoryView = [[[NSView alloc] initWithFrame:NSMakeRect(0, 0, 500, 0)] autorelease];

    NSString *titleString = [NSString stringWithCString:title];
    NSString *messageString = [NSString stringWithCString:message];
    NSString *continueString = [NSString stringWithCString:continue_label];
    NSString *helpString = [NSString stringWithCString:help_label];

    if (dialog_options & GHOST_DialogError) {
      alert.alertStyle = NSAlertStyleCritical;
    }
    else if (dialog_options & GHOST_DialogWarning) {
      alert.alertStyle = NSAlertStyleWarning;
    }
    else {
      alert.alertStyle = NSAlertStyleInformational;
    }

    alert.messageText = titleString;
    alert.informativeText = messageString;

    [alert addButtonWithTitle:continueString];
    if (link && strlen(link)) {
      [alert addButtonWithTitle:helpString];
    }

    const NSModalResponse response = [alert runModal];
    if (response == NSAlertSecondButtonReturn) {
      NSString *linkString = [NSString stringWithCString:link];
      [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:linkString]];
    }
  }
  return GHOST_kSuccess;
}
