/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Vector glyphs shared by the video card overlay and the preview player.
 */

#pragma once

namespace blender::ed::mixie {

enum class VideoGlyph {
  OpenPreview,
  Play,
  Pause,
  SoundOn,
  SoundOff,
};

/**
 * Draw \a glyph centred on (\a cx, \a cy) inside a box \a size wide, in the
 * units of the current matrix (canvas units on a card, pixels in a player).
 * Strokes are \a line_px screen pixels wide at any zoom.
 */
void video_glyph_draw(VideoGlyph glyph,
                      float cx,
                      float cy,
                      float size,
                      float line_px,
                      const float color[4]);

}  // namespace blender::ed::mixie
