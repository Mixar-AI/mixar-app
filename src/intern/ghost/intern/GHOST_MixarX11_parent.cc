/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * X11 parent relationships and the GHOST timer that keeps tracked
 * children following their parent. WM_TRANSIENT_FOR is stacking-only —
 * without this pump the pill detaches when the host is dragged.
 */

#ifdef WITH_GHOST_X11

#  include <X11/Xlib.h>

#  include <vector>

#  include "GHOST_ITimerTask.hh"
#  include "GHOST_MixarX11.hh"

struct MixarX11Track {
  void *child_handle;
  void *parent_handle;
  Window child_xwin;
  Window parent_xwin;
  int mode;
  int offset_x;
  int offset_y;
  int margin_bottom;
  bool has_last_origin = false;
  int last_parent_x = 0;
  int last_parent_y = 0;
};

static std::vector<MixarX11Track> s_x11_tracks;
static GHOST_ITimerTask *s_x11_track_timer = nullptr;

static void mixar_x11_track_tick(GHOST_ITimerTask * /*task*/, uint64_t /*time*/);

static void mixar_x11_track_stop_timer()
{
  if (s_x11_track_timer == nullptr) {
    return;
  }
  GHOST_ISystem *system = GHOST_ISystem::getSystem();
  if (system != nullptr) {
    system->removeTimer(s_x11_track_timer);
  }
  s_x11_track_timer = nullptr;
}

static void mixar_x11_track_start_timer()
{
  if (s_x11_track_timer != nullptr || s_x11_tracks.empty()) {
    return;
  }
  GHOST_SystemX11 *system = mixar_x11_system();
  if (system == nullptr) {
    return;
  }
  /* ~30Hz: re-anchor to WM ConfigureNotify motion, not the pointer. */
  s_x11_track_timer = system->installTimer(0, 33, mixar_x11_track_tick, nullptr);
}

static void mixar_x11_set_transient(void *child_handle, void *parent_handle)
{
  Display *display;
  Window child, parent;
  if (!mixar_x11_resolve(child_handle, &display, &child) ||
      !mixar_x11_resolve(parent_handle, &display, &parent))
  {
    return;
  }
  XSetTransientForHint(display, child, parent);
  XFlush(display);
}

static void mixar_x11_track_tick(GHOST_ITimerTask * /*task*/, uint64_t /*time*/)
{
  GHOST_SystemX11 *system = mixar_x11_system();
  Display *display = (system != nullptr) ? system->getXDisplay() : nullptr;
  if (display == nullptr) {
    return;
  }
  bool dropped = false;
  bool moved = false;
  for (size_t i = 0; i < s_x11_tracks.size();) {
    MixarX11Track &track = s_x11_tracks[i];

    int px, py, pw, ph;
    if (!mixar_x11_frame(display, track.parent_xwin, &px, &py, &pw, &ph)) {
      s_x11_tracks.erase(s_x11_tracks.begin() + i);
      dropped = true;
      continue;
    }
    int cx, cy, cw, ch;
    if (!mixar_x11_frame(display, track.child_xwin, &cx, &cy, &cw, &ch)) {
      s_x11_tracks.erase(s_x11_tracks.begin() + i);
      dropped = true;
      continue;
    }

    const bool parent_moved = (!track.has_last_origin || px != track.last_parent_x ||
                               py != track.last_parent_y);
    int target_x = cx;
    int target_y = cy;
    switch (track.mode) {
      case MIXAR_X11_TRACK_ABOVE_TOP_LEFT:
        target_x = px + track.offset_x;
        target_y = py - ch - track.offset_y;
        break;
      case MIXAR_X11_TRACK_CENTRE_BOTTOM:
        target_x = px + (pw - cw) / 2;
        target_y = py + ph - ch - track.margin_bottom;
        break;
      case MIXAR_X11_TRACK_FOLLOW_MOVE:
        if (parent_moved && track.has_last_origin) {
          target_x = cx + (px - track.last_parent_x);
          target_y = cy + (py - track.last_parent_y);
        }
        break;
      case MIXAR_X11_TRACK_RELATIVE_OFFSET:
        if (parent_moved && track.has_last_origin) {
          target_x = px + track.offset_x;
          target_y = py + track.offset_y;
          if (target_x + cw > px + pw) {
            target_x = px + pw - cw;
          }
          if (target_y + ch > py + ph) {
            target_y = py + ph - ch;
          }
          if (target_x < px) {
            target_x = px;
          }
          if (target_y < py) {
            target_y = py;
          }
          track.offset_x = target_x - px;
          track.offset_y = target_y - py;
        }
        else {
          /* WM-driven child drag (BeginDrag): refresh so a later parent
           * move does not snap the child back. */
          track.offset_x = cx - px;
          track.offset_y = cy - py;
        }
        break;
    }

    track.has_last_origin = true;
    track.last_parent_x = px;
    track.last_parent_y = py;

    if ((target_x != cx || target_y != cy) &&
        (track.mode == MIXAR_X11_TRACK_ABOVE_TOP_LEFT ||
         track.mode == MIXAR_X11_TRACK_CENTRE_BOTTOM || parent_moved))
    {
      XMoveWindow(display, track.child_xwin, target_x, target_y);
      moved = true;
    }
    i++;
  }
  if (moved) {
    XFlush(display);
  }
  if (dropped && s_x11_tracks.empty()) {
    mixar_x11_track_stop_timer();
  }
}

bool mixar_x11_track_remove(void *child_handle)
{
  for (size_t i = 0; i < s_x11_tracks.size(); i++) {
    if (s_x11_tracks[i].child_handle == child_handle) {
      s_x11_tracks.erase(s_x11_tracks.begin() + i);
      if (s_x11_tracks.empty()) {
        mixar_x11_track_stop_timer();
      }
      return true;
    }
  }
  return false;
}

void mixar_x11_track_add(void *child_handle,
                         void *parent_handle,
                         int mode,
                         int offset_x,
                         int offset_y,
                         int margin_bottom)
{
  if (child_handle == nullptr || parent_handle == nullptr || child_handle == parent_handle) {
    return;
  }
  Display *display;
  Window child, parent;
  if (!mixar_x11_resolve(child_handle, &display, &child) ||
      !mixar_x11_resolve(parent_handle, &display, &parent))
  {
    return;
  }

  MixarX11Track track;
  track.child_handle = child_handle;
  track.parent_handle = parent_handle;
  track.child_xwin = child;
  track.parent_xwin = parent;
  track.mode = mode;
  track.offset_x = offset_x;
  track.offset_y = offset_y;
  track.margin_bottom = margin_bottom;

  mixar_x11_track_remove(child_handle);
  s_x11_tracks.push_back(track);
  mixar_x11_track_start_timer();
  mixar_x11_track_tick(nullptr, 0);
}

extern "C" void Mixar_WindowSetParent(void *child_handle, void *parent_handle)
{
  mixar_x11_set_transient(child_handle, parent_handle);
  mixar_x11_track_add(child_handle,
                      parent_handle,
                      MIXAR_X11_TRACK_ABOVE_TOP_LEFT,
                      0,
                      mixar_x11_to_phys(child_handle, MIXAR_X11_PILL_GAP),
                      0);
}

extern "C" void Mixar_WindowSetParentPlain(void *child_handle, void *parent_handle)
{
  mixar_x11_set_transient(child_handle, parent_handle);
  /* Cocoa Plain still follows parent moves via addChildWindow. */
  mixar_x11_track_add(child_handle, parent_handle, MIXAR_X11_TRACK_FOLLOW_MOVE, 0, 0, 0);
}

extern "C" void Mixar_WindowSetParentTracked(void *child_handle, void *parent_handle)
{
  Display *display;
  Window child, parent;
  if (!mixar_x11_resolve(child_handle, &display, &child) ||
      !mixar_x11_resolve(parent_handle, &display, &parent))
  {
    return;
  }
  XSetTransientForHint(display, child, parent);
  XFlush(display);

  int px, py, pw, ph, cx, cy, cw, ch;
  if (!mixar_x11_frame(display, parent, &px, &py, &pw, &ph) ||
      !mixar_x11_frame(display, child, &cx, &cy, &cw, &ch))
  {
    return;
  }
  mixar_x11_track_add(
      child_handle, parent_handle, MIXAR_X11_TRACK_RELATIVE_OFFSET, cx - px, cy - py, 0);
}

extern "C" void Mixar_WindowDetachFromParent(void *child_handle, void * /*parent_handle*/)
{
  mixar_x11_track_remove(child_handle);
  Display *display;
  Window child;
  if (!mixar_x11_resolve(child_handle, &display, &child)) {
    return;
  }
  Atom transient = XInternAtom(display, "WM_TRANSIENT_FOR", False);
  if (transient != None) {
    XDeleteProperty(display, child, transient);
    XFlush(display);
  }
}

extern "C" void Mixar_WindowForgetTracking(const void *window_handle)
{
  if (window_handle == nullptr) {
    return;
  }
  mixar_x11_dock_forget(window_handle);
  for (size_t i = 0; i < s_x11_tracks.size();) {
    if (s_x11_tracks[i].child_handle == window_handle ||
        s_x11_tracks[i].parent_handle == window_handle)
    {
      s_x11_tracks.erase(s_x11_tracks.begin() + i);
    }
    else {
      i++;
    }
  }
  if (s_x11_tracks.empty()) {
    mixar_x11_track_stop_timer();
  }
}

extern "C" bool Mixar_WindowHasChildWindow(void *parent_handle)
{
  Display *display;
  Window parent;
  if (!mixar_x11_resolve(parent_handle, &display, &parent)) {
    return false;
  }
  for (const MixarX11Track &track : s_x11_tracks) {
    if (track.parent_handle == parent_handle || track.parent_xwin == parent) {
      return true;
    }
  }
  Window root = DefaultRootWindow(display);
  Window root_return, parent_return, *children = nullptr;
  unsigned int count = 0;
  if (!XQueryTree(display, root, &root_return, &parent_return, &children, &count)) {
    return false;
  }
  bool found = false;
  for (unsigned int i = 0; i < count && !found; i++) {
    Window transient_for = None;
    if (XGetTransientForHint(display, children[i], &transient_for) && transient_for == parent) {
      found = true;
    }
  }
  if (children) {
    XFree(children);
  }
  return found;
}

extern "C" void Mixar_WindowAnchorAtParentCentreBottom(void *child_handle,
                                                       void *parent_handle,
                                                       int margin_bottom)
{
  mixar_x11_set_transient(child_handle, parent_handle);
  mixar_x11_track_add(child_handle,
                      parent_handle,
                      MIXAR_X11_TRACK_CENTRE_BOTTOM,
                      0,
                      0,
                      mixar_x11_to_phys(child_handle, margin_bottom));
  Display *display;
  Window child;
  if (mixar_x11_resolve(child_handle, &display, &child)) {
    XRaiseWindow(display, child);
    XFlush(display);
  }
}

extern "C" void Mixar_WindowAnchorAtParentOffset(void *child_handle,
                                                 void *parent_handle,
                                                 int offset_x,
                                                 int offset_y)
{
  mixar_x11_set_transient(child_handle, parent_handle);
  mixar_x11_track_add(child_handle,
                      parent_handle,
                      MIXAR_X11_TRACK_RELATIVE_OFFSET,
                      mixar_x11_to_phys(child_handle, offset_x),
                      mixar_x11_to_phys(child_handle, offset_y),
                      0);
  Display *display;
  Window child;
  if (mixar_x11_resolve(child_handle, &display, &child)) {
    XRaiseWindow(display, child);
    XFlush(display);
  }
}

extern "C" bool Mixar_WindowGetParentOffset(void *child_handle,
                                            void *parent_handle,
                                            int *r_offset_x,
                                            int *r_offset_y)
{
  if (r_offset_x == nullptr || r_offset_y == nullptr) {
    return false;
  }
  Display *display;
  Window child, parent;
  if (!mixar_x11_resolve(child_handle, &display, &child) ||
      !mixar_x11_resolve(parent_handle, &display, &parent))
  {
    return false;
  }
  int px, py, pw, ph, cx, cy, cw, ch;
  if (!mixar_x11_frame(display, parent, &px, &py, &pw, &ph) ||
      !mixar_x11_frame(display, child, &cx, &cy, &cw, &ch))
  {
    return false;
  }
  (void)pw;
  (void)ph;
  (void)cw;
  (void)ch;
  *r_offset_x = mixar_x11_to_logical(child_handle, cx - px);
  *r_offset_y = mixar_x11_to_logical(child_handle, cy - py);
  return true;
}

extern "C" void Mixar_WindowPlaceInParent(void *child_handle,
                                          void *parent_handle,
                                          int offset_x,
                                          int offset_y)
{
  Display *display;
  Window child, parent;
  if (!mixar_x11_resolve(child_handle, &display, &child) ||
      !mixar_x11_resolve(parent_handle, &display, &parent))
  {
    return;
  }
  int px, py, pw, ph;
  if (!mixar_x11_frame(display, parent, &px, &py, &pw, &ph)) {
    return;
  }
  (void)pw;
  (void)ph;
  XMoveWindow(display,
              child,
              px + mixar_x11_to_phys(child_handle, offset_x),
              py + mixar_x11_to_phys(child_handle, offset_y));
  XFlush(display);
}

#endif /* WITH_GHOST_X11 */
