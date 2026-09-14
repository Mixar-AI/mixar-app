/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * X11 Mixar_Window* chrome, size, and opacity. Parent tracking lives in
 * GHOST_MixarX11_parent.cc; drag/place/snap in GHOST_MixarX11_move.cc.
 * GHOST_SystemX11.cc is left byte-identical to upstream.
 *
 * Wayland sessions no-op via dynamic_cast. There is no X11 equivalent for
 * hide-on-deactivate, Spaces binding, blur-behind, or a portable corner
 * radius (XShape is not linked). Those entry points are explicit no-ops.
 */

#ifdef WITH_GHOST_X11

#  include <X11/Xatom.h>
#  include <X11/Xlib.h>
#  include <X11/Xutil.h>

#  include <algorithm>
#  include <vector>

#  include "GHOST_MixarX11.hh"

#  define MWM_HINTS_DECORATIONS (1L << 1)
struct MixarMwmHints {
  unsigned long flags;
  unsigned long functions;
  unsigned long decorations;
  long input_mode;
  unsigned long status;
};

struct MixarX11Dock {
  void *handle;
  Window xwin;
};

static std::vector<MixarX11Dock> s_x11_docks;
static int s_x11_dock_suppress_depth = 0;
static std::vector<Window> s_x11_suppressed_docks;

static void mixar_x11_set_state(Display *display,
                                Window window,
                                const char *state_name,
                                bool enable)
{
  Atom wm_state = XInternAtom(display, "_NET_WM_STATE", False);
  Atom state = XInternAtom(display, state_name, False);
  if (wm_state == None || state == None) {
    return;
  }
  XEvent event = {};
  event.type = ClientMessage;
  event.xclient.window = window;
  event.xclient.message_type = wm_state;
  event.xclient.format = 32;
  event.xclient.data.l[0] = enable ? 1 : 0;
  event.xclient.data.l[1] = long(state);
  event.xclient.data.l[2] = 0;
  event.xclient.data.l[3] = 1;
  XSendEvent(display,
             DefaultRootWindow(display),
             False,
             SubstructureRedirectMask | SubstructureNotifyMask,
             &event);
  XFlush(display);
}

void mixar_x11_dock_register(void *window_handle, Window window)
{
  for (MixarX11Dock &dock : s_x11_docks) {
    if (dock.handle == window_handle) {
      dock.xwin = window;
      return;
    }
  }
  s_x11_docks.push_back({window_handle, window});
}

void mixar_x11_dock_forget(const void *window_handle)
{
  if (window_handle == nullptr) {
    return;
  }
  for (size_t i = 0; i < s_x11_docks.size();) {
    if (s_x11_docks[i].handle == window_handle) {
      s_x11_docks.erase(s_x11_docks.begin() + i);
    }
    else {
      i++;
    }
  }
}

bool mixar_x11_dock_suppress_if_needed(void *window_handle)
{
  if (s_x11_dock_suppress_depth <= 0) {
    return false;
  }
  Display *display;
  Window window;
  if (!mixar_x11_resolve(window_handle, &display, &window)) {
    return false;
  }
  bool marked = false;
  for (const MixarX11Dock &dock : s_x11_docks) {
    if (dock.handle == window_handle || dock.xwin == window) {
      marked = true;
      break;
    }
  }
  if (!marked) {
    return false;
  }
  if (mixar_x11_is_viewable(display, window)) {
    s_x11_suppressed_docks.push_back(window);
    XUnmapWindow(display, window);
    XFlush(display);
  }
  return true;
}

extern "C" void Mixar_WindowSetChromeless(void *window_handle, bool chromeless)
{
  Display *display;
  Window window;
  if (!mixar_x11_resolve(window_handle, &display, &window)) {
    return;
  }

  MixarMwmHints hints = {};
  hints.flags = MWM_HINTS_DECORATIONS;
  hints.decorations = chromeless ? 0 : 1;
  Atom motif = XInternAtom(display, "_MOTIF_WM_HINTS", False);
  if (motif != None) {
    XChangeProperty(display,
                    window,
                    motif,
                    motif,
                    32,
                    PropModeReplace,
                    reinterpret_cast<unsigned char *>(&hints),
                    sizeof(MixarMwmHints) / sizeof(long));
  }

  mixar_x11_set_state(display, window, "_NET_WM_STATE_SKIP_TASKBAR", chromeless);
  mixar_x11_set_state(display, window, "_NET_WM_STATE_SKIP_PAGER", chromeless);
  XFlush(display);
}

extern "C" void Mixar_WindowSetBorderless(void *window_handle)
{
  Mixar_WindowSetChromeless(window_handle, true);
}

extern "C" void Mixar_WindowSetFloatingLevel(void *window_handle)
{
  if (mixar_x11_dock_suppress_if_needed(window_handle)) {
    return;
  }
  Display *display;
  Window window;
  if (!mixar_x11_resolve(window_handle, &display, &window)) {
    return;
  }
  mixar_x11_set_state(display, window, "_NET_WM_STATE_ABOVE", true);
}

extern "C" void Mixar_WindowMarkAsFloatingDock(void *window_handle)
{
  Display *display;
  Window window;
  if (!mixar_x11_resolve(window_handle, &display, &window)) {
    return;
  }
  Atom type = XInternAtom(display, "_NET_WM_WINDOW_TYPE", False);
  Atom utility = XInternAtom(display, "_NET_WM_WINDOW_TYPE_UTILITY", False);
  if (type != None && utility != None) {
    XChangeProperty(display,
                    window,
                    type,
                    XA_ATOM,
                    32,
                    PropModeReplace,
                    reinterpret_cast<unsigned char *>(&utility),
                    1);
    XFlush(display);
  }
  mixar_x11_dock_register(window_handle, window);
  mixar_x11_dock_suppress_if_needed(window_handle);
}

extern "C" void Mixar_FloatingDocksSuppressForModal()
{
  s_x11_dock_suppress_depth++;
  if (s_x11_dock_suppress_depth > 1) {
    return;
  }
  s_x11_suppressed_docks.clear();
  GHOST_SystemX11 *system = mixar_x11_system();
  Display *display = (system != nullptr) ? system->getXDisplay() : nullptr;
  if (display == nullptr) {
    return;
  }
  for (auto it = s_x11_docks.begin(); it != s_x11_docks.end();) {
    if (mixar_x11_window(it->handle) == nullptr) {
      it = s_x11_docks.erase(it);
      continue;
    }
    if (mixar_x11_is_viewable(display, it->xwin)) {
      s_x11_suppressed_docks.push_back(it->xwin);
      XUnmapWindow(display, it->xwin);
    }
    ++it;
  }
  XFlush(display);
}

extern "C" void Mixar_FloatingDocksRestoreAfterModal()
{
  if (s_x11_dock_suppress_depth <= 0) {
    return;
  }
  s_x11_dock_suppress_depth--;
  if (s_x11_dock_suppress_depth > 0) {
    return;
  }
  GHOST_SystemX11 *system = mixar_x11_system();
  Display *display = (system != nullptr) ? system->getXDisplay() : nullptr;
  if (display == nullptr) {
    s_x11_suppressed_docks.clear();
    return;
  }
  for (Window window : s_x11_suppressed_docks) {
    XMapWindow(display, window);
    XRaiseWindow(display, window);
  }
  XFlush(display);
  s_x11_suppressed_docks.clear();
}

/* ICCCM/EWMH have no per-window "hide with application" flag. */
extern "C" void Mixar_WindowSetHidesOnDeactivate(void * /*window_handle*/, bool /*hides*/) {}

/* macOS Spaces only. */
extern "C" void Mixar_WindowBindToParentSpace(void * /*window_handle*/) {}

/* Needs XShape (libXext), which this GHOST build does not link. */
extern "C" void Mixar_WindowSetCornerRadius(void * /*window_handle*/, float /*radius*/) {}

/* Compositor blur has no portable X11 request. */
extern "C" void Mixar_WindowSetBlurBehind(void * /*window_handle*/, bool /*enable*/) {}

/* X11 GL windows are opaque; no per-pixel alpha path. */
extern "C" bool Mixar_WindowHasAlphaChannel(void * /*window_handle*/)
{
  return false;
}

extern "C" void Mixar_WindowSetPerPixelAlpha(void * /*window_handle*/, bool /*enable*/) {}

extern "C" void Mixar_WindowForceSize(void *window_handle, int width, int height)
{
  Display *display;
  Window window;
  if (!mixar_x11_resolve(window_handle, &display, &window) || width <= 0 || height <= 0) {
    return;
  }
  const int phys_w = std::max(1, mixar_x11_to_phys(window_handle, width));
  const int phys_h = std::max(1, mixar_x11_to_phys(window_handle, height));
  /* Resize only. XMoveResizeWindow on a live GL window under this NVIDIA +
   * Xvfb stack destroys the context; the next present segfaults. Anchor
   * updates stay on the tracking timer / Snap* helpers, matching the
   * X11 backend that already ran here. */
  XResizeWindow(display, window, unsigned(phys_w), unsigned(phys_h));
  XFlush(display);
}

static void mixar_x11_set_size_hint(void *window_handle, bool is_min, int width, int height)
{
  Display *display;
  Window window;
  if (!mixar_x11_resolve(window_handle, &display, &window)) {
    return;
  }
  const int phys_w = mixar_x11_to_phys(window_handle, width);
  const int phys_h = mixar_x11_to_phys(window_handle, height);
  XSizeHints hints = {};
  long supplied = 0;
  if (!XGetWMNormalHints(display, window, &hints, &supplied)) {
    hints.flags = 0;
  }
  if (is_min) {
    hints.flags |= PMinSize;
    hints.min_width = phys_w;
    hints.min_height = phys_h;
  }
  else {
    hints.flags |= PMaxSize;
    hints.max_width = (width > 0) ? phys_w : 32767;
    hints.max_height = (height > 0) ? phys_h : 32767;
  }
  XSetWMNormalHints(display, window, &hints);
  XFlush(display);
}

extern "C" void Mixar_WindowSetMinContentSize(void *window_handle, int width, int height)
{
  mixar_x11_set_size_hint(window_handle, true, width, height);
}

extern "C" void Mixar_WindowSetMaxContentSize(void *window_handle, int width, int height)
{
  mixar_x11_set_size_hint(window_handle, false, width, height);
}

extern "C" void Mixar_WindowGetContentPixelSize(void *window_handle, int *r_width, int *r_height)
{
  if (r_width) {
    *r_width = 0;
  }
  if (r_height) {
    *r_height = 0;
  }
  Display *display;
  Window window;
  if (!mixar_x11_resolve(window_handle, &display, &window)) {
    return;
  }
  int x, y, width, height;
  if (!mixar_x11_frame(display, window, &x, &y, &width, &height)) {
    return;
  }
  if (r_width) {
    *r_width = width;
  }
  if (r_height) {
    *r_height = height;
  }
}

extern "C" bool Mixar_WindowGetContentSize(void *window_handle, int *r_width, int *r_height)
{
  if (r_width == nullptr || r_height == nullptr) {
    return false;
  }
  int pixel_w = 0, pixel_h = 0;
  Mixar_WindowGetContentPixelSize(window_handle, &pixel_w, &pixel_h);
  if (pixel_w <= 0 || pixel_h <= 0) {
    return false;
  }
  *r_width = mixar_x11_to_logical(window_handle, pixel_w);
  *r_height = mixar_x11_to_logical(window_handle, pixel_h);
  return true;
}

extern "C" int Mixar_WindowGetMaxHeightToScreenTop(void *window_handle, int reserve_top)
{
  Display *display;
  Window window;
  if (!mixar_x11_resolve(window_handle, &display, &window)) {
    return 0;
  }
  int x, y, width, height;
  if (!mixar_x11_frame(display, window, &x, &y, &width, &height)) {
    return 0;
  }
  const int phys = std::max(0, (y + height) - mixar_x11_to_phys(window_handle, reserve_top));
  return mixar_x11_to_logical(window_handle, phys);
}

extern "C" bool Mixar_WindowIsVisible(void *window_handle)
{
  if (window_handle == nullptr) {
    return false;
  }
  /* Wayland (or any non-X11 GHOST backend): never skip wm_draw. False
   * here drops SwapBuffers for every window and the NVIDIA driver then
   * presents into a stale context. */
  if (mixar_x11_system() == nullptr) {
    return true;
  }
  Display *display;
  Window window;
  if (!mixar_x11_resolve_any(window_handle, &display, &window)) {
    return true;
  }
  XWindowAttributes attr;
  if (!XGetWindowAttributes(display, window, &attr)) {
    return true;
  }
  return attr.map_state == IsViewable;
}

extern "C" void Mixar_WindowSetAlpha(void *window_handle, float alpha)
{
  Display *display;
  Window window;
  if (!mixar_x11_resolve(window_handle, &display, &window)) {
    return;
  }
  Atom opacity = XInternAtom(display, "_NET_WM_WINDOW_OPACITY", False);
  if (opacity == None) {
    return;
  }
  const float clamped = std::min(1.0f, std::max(0.0f, alpha));
  if (clamped >= 1.0f) {
    XDeleteProperty(display, window, opacity);
  }
  else {
    const unsigned long value = (unsigned long)(clamped * 0xffffffffu);
    XChangeProperty(display,
                    window,
                    opacity,
                    XA_CARDINAL,
                    32,
                    PropModeReplace,
                    reinterpret_cast<const unsigned char *>(&value),
                    1);
  }
  XFlush(display);
}

extern "C" void Mixar_WindowAnimateAlphaTo(void *window_handle,
                                           float target_alpha,
                                           float /*duration*/)
{
  Mixar_WindowSetAlpha(window_handle, target_alpha);
}

#endif /* WITH_GHOST_X11 */
