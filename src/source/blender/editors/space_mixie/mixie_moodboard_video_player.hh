/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Video preview player state, control layout and painter, shared by the
 * operator (mixie_moodboard_video_player.cc) and its drawing
 * (mixie_moodboard_video_player_draw.cc).
 */

#pragma once

#include "DNA_vec_types.h"

#include <vector>

namespace blender {
struct ARegion;
struct Image;
struct MixarQATarget;
struct ScrArea;
struct wmTimer;
struct wmWindow;
}  // namespace blender

namespace blender::ed::mixie {

enum PlayerControl {
  PLAYER_NONE = -1,
  PLAYER_PLAY,
  PLAYER_TIMELINE,
  PLAYER_SOUND,
  PLAYER_VOLUME,
};

enum class PlayerDrag { None, Timeline, Volume };

struct VideoPlayer {
  wmWindow *win = nullptr;
  ScrArea *area = nullptr;
  Image *image = nullptr;
  void *draw_handle = nullptr;
  wmTimer *timer = nullptr;
  PlayerDrag drag = PlayerDrag::None;
  bool resume_after_scrub = false;
  int hovered = PLAYER_NONE;
};

struct PlayerLayout {
  rctf play, timeline, sound, volume, shade;
};

/** Window-pixel rects of the player controls in \a area. */
PlayerLayout video_player_layout(const ScrArea *area);
/** The control under \a xy (window pixels), or PLAYER_NONE. */
int video_player_control_at(const ScrArea *area, const int xy[2]);
/** Where \a x falls along \a bar, 0..1. */
float video_player_bar_fraction(const rctf &bar, int x);
/** Window draw callback: the controls over the picture (customdata = VideoPlayer). */
void video_player_draw(const wmWindow *win, void *customdata);
/**
 * QA targets of a player window's Image Editor: `video_player` (text = movie,
 * value = frame, sel = playing, detail = audio state), its `_play`,
 * `_timeline`, `_sound` (sel = muted) and `_volume` (value = percent) controls.
 */
void video_player_qa_targets(const wmWindow *win,
                             const ScrArea *area,
                             const ARegion *region,
                             std::vector<MixarQATarget> &r_targets);

}  // namespace blender::ed::mixie
