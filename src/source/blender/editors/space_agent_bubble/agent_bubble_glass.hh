/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

namespace blender {
struct bContext;
struct wmRegionListenerParams;

/** One native setup request per window lifecycle, including unsupported windows. */
struct AgentBubbleGlassState {
  void *window = nullptr;
  bool pending = false;
  bool attempted = false;
  bool transparent = false;

  bool request(void *ghostwin)
  {
    if (ghostwin == nullptr) {
      return false;
    }
    if (window != ghostwin) {
      *this = {};
      window = ghostwin;
    }
    if (pending || attempted) {
      return false;
    }
    pending = true;
    return true;
  }

  template<typename Apply> bool apply(void *ghostwin, Apply native_apply)
  {
    if (!pending || window != ghostwin) {
      return false;
    }
    pending = false;
    attempted = true;
    transparent = native_apply(ghostwin);
    return true;
  }

  void reset(const void *ghostwin)
  {
    if (ghostwin == nullptr || window == ghostwin) {
      *this = {};
    }
  }
};

/** Queue setup after native creation/size repair; never enter the compositor from paint. */
void agent_bubble_glass_request(const bContext *C, void *ghostwin, bool pill);
void agent_bubble_glass_reset(const void *ghostwin = nullptr);
void agent_bubble_glass_region_listener(const wmRegionListenerParams *params);

}  // namespace blender
