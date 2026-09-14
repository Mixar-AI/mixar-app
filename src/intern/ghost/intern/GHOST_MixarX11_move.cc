/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * X11 Mixar_Window* stacking, placement, drag, and deferred work.
 * Animation helpers jump to the end state — there is no frame animator.
 * Mixar_DispatchMainAfter therefore runs its callback immediately.
 */

#ifdef WITH_GHOST_X11

#  include <X11/Xlib.h>

#  include "GHOST_MixarX11.hh"

extern "C" void Mixar_WindowForceSize(void *window_handle, int width, int height);
extern "C" void Mixar_WindowSetAlpha(void *window_handle, float alpha);

void mixar_x11_centre_bottom_of(void *child_handle, void *parent_handle, int margin_bottom)
{
  Display *display;
  Window child, parent;
  if (!mixar_x11_resolve(child_handle, &display, &child)) {
    return;
  }
  if (!mixar_x11_resolve(parent_handle, &display, &parent)) {
    return;
  }
  int px, py, pw, ph, cx, cy, cw, ch;
  if (!mixar_x11_frame(display, parent, &px, &py, &pw, &ph) ||
      !mixar_x11_frame(display, child, &cx, &cy, &cw, &ch))
  {
    return;
  }
  const int phys_margin = mixar_x11_to_phys(child_handle, margin_bottom);
  XMoveWindow(display, child, px + (pw - cw) / 2, py + ph - ch - phys_margin);
  XFlush(display);
}

extern "C" void Mixar_WindowOrderFront(void *window_handle)
{
  if (mixar_x11_dock_suppress_if_needed(window_handle)) {
    return;
  }
  Display *display;
  Window window;
  if (!mixar_x11_resolve_move_minimise(window_handle, &display, &window)) {
    return;
  }
  XMapRaised(display, window);
  XFlush(display);
}

extern "C" void Mixar_WindowOrderFrontNoActivate(void *window_handle)
{
  if (mixar_x11_dock_suppress_if_needed(window_handle)) {
    return;
  }
  Display *display;
  Window window;
  if (!mixar_x11_resolve_move_minimise(window_handle, &display, &window)) {
    return;
  }
  /* Map and raise without XSetInputFocus. The WM may still steal focus. */
  XMapWindow(display, window);
  XRaiseWindow(display, window);
  XFlush(display);
}

extern "C" void Mixar_WindowOrderOut(void *window_handle)
{
  Display *display;
  Window window;
  if (!mixar_x11_resolve_move_minimise(window_handle, &display, &window)) {
    return;
  }
  XUnmapWindow(display, window);
  XFlush(display);
}

extern "C" void Mixar_WindowMakeKey(void *window_handle)
{
  Display *display;
  Window window;
  if (!mixar_x11_resolve_move_minimise(window_handle, &display, &window)) {
    return;
  }
  XRaiseWindow(display, window);
  XSetInputFocus(display, window, RevertToParent, CurrentTime);
  XFlush(display);
}

extern "C" void Mixar_WindowPositionAboveParent(void *child_handle,
                                                void *parent_handle,
                                                int offset_x,
                                                int offset_y)
{
  Display *display;
  Window child, parent;
  /* Chrome gate, not the heavy one: this only ever calls XMoveWindow. What
   * destroyed the GL context on this stack was XMoveResizeWindow, which
   * resizes a live drawable — a pure move does not. Without this the pill
   * never reaches its anchor and sits wherever the WM first placed it. */
  if (!mixar_x11_resolve_chrome(child_handle, &display, &child) ||
      !mixar_x11_resolve_chrome(parent_handle, &display, &parent))
  {
    return;
  }
  /* Drain pending requests before measuring. The caller resizes the pill
   * (Mixar_WindowForceSize) immediately before anchoring it, and a
   * reparenting WM applies that asynchronously — measuring too early
   * returned the PRE-resize height and put the pill a full pill-height too
   * high, off the top of the screen instead of just above the island. */
  XSync(display, False);

  int px, py, pw, ph, cx, cy, cw, ch;
  if (!mixar_x11_frame(display, parent, &px, &py, &pw, &ph) ||
      !mixar_x11_frame(display, child, &cx, &cy, &cw, &ch))
  {
    return;
  }
  (void)pw;
  (void)ph;
  (void)cx;
  (void)cy;
  (void)cw;
  XMoveWindow(display,
              child,
              px + mixar_x11_to_phys(child_handle, offset_x),
              py - ch - mixar_x11_to_phys(child_handle, offset_y));
  XFlush(display);
}

extern "C" void Mixar_WindowSnapToCentreBottomOfWindow(void *child_handle,
                                                       void *parent_handle,
                                                       int margin_bottom)
{
  mixar_x11_centre_bottom_of(child_handle, parent_handle, margin_bottom);
}

extern "C" void Mixar_WindowSnapToCentreBottom(void *window_handle, int margin_bottom)
{
  Display *display;
  Window window;
  if (!mixar_x11_resolve(window_handle, &display, &window)) {
    return;
  }
  int x, y, width, height;
  if (!mixar_x11_frame(display, window, &x, &y, &width, &height)) {
    return;
  }
  Screen *screen = DefaultScreenOfDisplay(display);
  XMoveWindow(display,
              window,
              (WidthOfScreen(screen) - width) / 2,
              HeightOfScreen(screen) - height - mixar_x11_to_phys(window_handle, margin_bottom));
  XFlush(display);
}

extern "C" void Mixar_WindowAnimateFrameToCentreBottomOfWindow(void *child_handle,
                                                               void *parent_handle,
                                                               int new_width,
                                                               int new_height,
                                                               int margin_bottom,
                                                               float /*duration*/)
{
  Mixar_WindowForceSize(child_handle, new_width, new_height);
  mixar_x11_centre_bottom_of(child_handle, parent_handle, margin_bottom);
}

extern "C" void Mixar_WindowFloatIn(void *window_handle, int /*rise_pt*/, float /*duration*/)
{
  /* Instant snap: no CoreAnimation / compositor frame animator. */
  Mixar_WindowSetAlpha(window_handle, 1.0f);
}

extern "C" void Mixar_WindowFloatOut(void *window_handle, int /*sink_pt*/, float /*duration*/)
{
  Mixar_WindowSetAlpha(window_handle, 0.0f);
}

extern "C" bool Mixar_WindowContainsScreenCursor(void *window_handle, int margin_pt)
{
  Display *display;
  Window window;
  if (!mixar_x11_resolve(window_handle, &display, &window)) {
    return false;
  }
  if (!mixar_x11_is_viewable(display, window)) {
    return false;
  }
  int x, y, width, height;
  if (!mixar_x11_frame(display, window, &x, &y, &width, &height)) {
    return false;
  }
  Window root_return, child_return;
  int root_x = 0, root_y = 0, win_x = 0, win_y = 0;
  unsigned int mask = 0;
  if (!XQueryPointer(display,
                     DefaultRootWindow(display),
                     &root_return,
                     &child_return,
                     &root_x,
                     &root_y,
                     &win_x,
                     &win_y,
                     &mask))
  {
    return false;
  }
  const int margin = mixar_x11_to_phys(window_handle, margin_pt);
  return (root_x >= x - margin && root_x < x + width + margin && root_y >= y - margin &&
          root_y < y + height + margin);
}

extern "C" void Mixar_WindowBeginDrag(void *window_handle)
{
  Display *display;
  Window window;
  if (!mixar_x11_resolve_move_minimise(window_handle, &display, &window)) {
    return;
  }
  Atom moveresize = XInternAtom(display, "_NET_WM_MOVERESIZE", False);
  if (moveresize == None) {
    return;
  }

  Window root = DefaultRootWindow(display);
  Window root_return, child_return;
  int root_x = 0, root_y = 0, win_x = 0, win_y = 0;
  unsigned int mask = 0;
  if (!XQueryPointer(
          display, window, &root_return, &child_return, &root_x, &root_y, &win_x, &win_y, &mask))
  {
    return;
  }
  int button = 1;
  if (mask & Button2Mask) {
    button = 2;
  }
  else if (mask & Button3Mask) {
    button = 3;
  }

  XUngrabPointer(display, CurrentTime);
  XFlush(display);

  XEvent event = {};
  event.type = ClientMessage;
  event.xclient.window = window;
  event.xclient.message_type = moveresize;
  event.xclient.format = 32;
  event.xclient.data.l[0] = root_x;
  event.xclient.data.l[1] = root_y;
  event.xclient.data.l[2] = 8; /* _NET_WM_MOVERESIZE_MOVE */
  event.xclient.data.l[3] = button;
  event.xclient.data.l[4] = 1;
  XSendEvent(display, root, False, SubstructureRedirectMask | SubstructureNotifyMask, &event);
  XFlush(display);
}

/* The WM owns the grab after _NET_WM_MOVERESIZE. RELATIVE_OFFSET tracking
 * refreshes the stored offset while the child moves independently. */
extern "C" void Mixar_WindowUpdateDrag(void * /*window_handle*/) {}
extern "C" void Mixar_WindowEndDrag(void * /*window_handle*/) {}

extern "C" void Mixar_DispatchMainAfter(float /*delay_seconds*/,
                                        void (*callback)(void *),
                                        void *user_data)
{
  if (callback) {
    callback(user_data);
  }
}

#endif /* WITH_GHOST_X11 */
