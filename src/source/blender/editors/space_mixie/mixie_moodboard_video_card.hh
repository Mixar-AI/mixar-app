/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Movie card hover controls and board sound (mixie_moodboard_video_card.cc,
 * mixie_moodboard_ops_preview.cc). Included by mixie_intern.hh.
 */

#pragma once

#include "DNA_vec_types.h"

namespace blender {
struct ARegion;
struct bContext;
struct Image;
struct PointerRNA;
struct ReportList;
struct ScrArea;
struct View2D;
struct wmWindow;
}  // namespace blender

namespace blender::ed::mixie {

/** Mute or unmute a board movie's sound (sound is on by default). */
bool moodboard_toggle_video_mute(bContext *C,
                                 PointerRNA *scene_ptr,
                                 int index,
                                 ReportList *reports);
/** Whether a board movie's sound is muted. */
bool moodboard_video_is_muted(const Image *image);
/** A board movie's audio track state (see video_session_audio_state). */
const char *moodboard_video_audio_state(const Image *image);

/** The hover controls over every movie card, left to right. */
enum {
  MOODBOARD_VIDEO_CARD_NONE = -1,
  MOODBOARD_VIDEO_CARD_PREVIEW = 0,
  MOODBOARD_VIDEO_CARD_PLAY = 1,
  MOODBOARD_VIDEO_CARD_SOUND = 2,
};
/** Canvas rects of the Preview / Play / Sound controls over \a media_rect. */
void moodboard_video_card_button_rects(View2D *v2d, const rctf &media_rect, rctf r_rects[3]);
/** Which control is under (\a x, \a y) in canvas units, or NONE. */
int moodboard_video_card_button_at(View2D *v2d, const rctf &media_rect, float x, float y);
/** Start a canvas region's draw: forget the movie rects of its last frame. */
void moodboard_video_cards_frame_begin(const ARegion *region);
/** Record a drawn movie card; returns whether it is the hovered one. */
bool moodboard_video_card_register(const ARegion *region, const char *key, const rctf &rect);
/** Region cursor callback hook: track the card under the pointer. */
void moodboard_video_card_hover_update(wmWindow *win, ScrArea *area, ARegion *region);
void mixie_moodboard_video_cards_shutdown();

}  // namespace blender::ed::mixie
