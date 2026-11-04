/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Video preview player: control layout, hit-test, painter and QA targets.
 *
 * Layout is in window pixels from the player area, so the controls keep their
 * size whatever the window: over a bottom shade, the play/pause button, then
 * the timeline, the sound toggle and the volume bar. The window's own title
 * bar (or Esc) closes it.
 */

#include "mixie_moodboard_ops_common.hh"

#include <algorithm>
#include <string>

#include "BLI_math_vector.h"
#include "BLI_rect.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"

#include "../interface/interface_qa_inspect.hh"

#include "mixie_moodboard_video_glyphs.hh"
#include "mixie_moodboard_video_player.hh"
#include "mixie_moodboard_video_session.hh"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Layout
 * \{ */

PlayerLayout video_player_layout(const ScrArea *area)
{
  const rcti &a = area->totrct;
  const float u = UI_SCALE_FAC;
  const float pad = 20.0f * u;
  PlayerLayout l;

  const float bar_y = a.ymin + pad + 10.0f * u;
  const float bar_h = 6.0f * u;
  const float volume_w = 72.0f * u;
  l.volume = {a.xmax - pad - volume_w, a.xmax - pad, bar_y - bar_h * 0.5f, bar_y + bar_h * 0.5f};

  const float sound = 22.0f * u;
  const float sound_cx = l.volume.xmin - 14.0f * u - sound * 0.5f;
  l.sound = {sound_cx - sound * 0.5f, sound_cx + sound * 0.5f, bar_y - sound * 0.5f,
             bar_y + sound * 0.5f};

  l.timeline = {a.xmin + pad, l.sound.xmin - 16.0f * u, bar_y - bar_h * 0.5f,
                bar_y + bar_h * 0.5f};

  const float play = 34.0f * u;
  const float play_cx = (a.xmin + a.xmax) * 0.5f;
  const float play_cy = bar_y + 46.0f * u;
  l.play = {play_cx - play * 0.5f, play_cx + play * 0.5f, play_cy - play * 0.5f,
            play_cy + play * 0.5f};

  l.shade = {float(a.xmin), float(a.xmax), float(a.ymin), float(a.ymin) + 120.0f * u};
  return l;
}

/** Bars get a taller hit band than they draw; icons a little margin. */
int video_player_control_at(const ScrArea *area, const int xy[2])
{
  const PlayerLayout l = video_player_layout(area);
  const float u = UI_SCALE_FAC;
  const float x = float(xy[0]), y = float(xy[1]);
  auto in = [&](rctf r, const float pad_x, const float pad_y) {
    BLI_rctf_pad(&r, pad_x, pad_y);
    return BLI_rctf_isect_pt(&r, x, y);
  };
  if (in(l.play, 6.0f * u, 6.0f * u)) {
    return PLAYER_PLAY;
  }
  if (in(l.sound, 4.0f * u, 6.0f * u)) {
    return PLAYER_SOUND;
  }
  if (in(l.volume, 2.0f * u, 8.0f * u)) {
    return PLAYER_VOLUME;
  }
  if (in(l.timeline, 2.0f * u, 8.0f * u)) {
    return PLAYER_TIMELINE;
  }
  return PLAYER_NONE;
}

float video_player_bar_fraction(const rctf &bar, const int x)
{
  return std::clamp((float(x) - bar.xmin) / std::max(BLI_rctf_size_x(&bar), 1.0f), 0.0f, 1.0f);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Drawing
 * \{ */

static void draw_shade(const rctf &shade)
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint col = GPU_vertformat_attr_add(
      format, "color", gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);
  immBegin(GPU_PRIM_TRI_STRIP, 4);
  immAttr4f(col, 0.0f, 0.0f, 0.0f, 0.62f);
  immVertex2f(pos, shade.xmin, shade.ymin);
  immAttr4f(col, 0.0f, 0.0f, 0.0f, 0.62f);
  immVertex2f(pos, shade.xmax, shade.ymin);
  immAttr4f(col, 0.0f, 0.0f, 0.0f, 0.0f);
  immVertex2f(pos, shade.xmin, shade.ymax);
  immAttr4f(col, 0.0f, 0.0f, 0.0f, 0.0f);
  immVertex2f(pos, shade.xmax, shade.ymax);
  immEnd();
  immUnbindProgram();
}

static void draw_bar(const rctf &bar, const float fraction, const float fill_alpha)
{
  const float radius = BLI_rctf_size_y(&bar) * 0.5f;
  const float track[4] = {1.0f, 1.0f, 1.0f, 0.32f};
  const float fill[4] = {1.0f, 1.0f, 1.0f, fill_alpha};
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&bar, true, radius, track);
  if (fraction > 0.0f) {
    rctf done = bar;
    done.xmax = bar.xmin + std::max(BLI_rctf_size_x(&bar) * fraction, radius * 2.0f);
    ui::draw_roundbox_4fv(&done, true, radius, fill);
  }
}

void video_player_draw(const wmWindow * /*win*/, void *customdata)
{
  VideoPlayer &player = *static_cast<VideoPlayer *>(customdata);
  MoodboardVideoSession *session = video_player_session_find(player);
  if (!session || !player.area) {
    return;
  }
  const PlayerLayout l = video_player_layout(player.area);
  const float u = UI_SCALE_FAC;
  auto tone = [&](const int control) {
    return player.hovered == control ? 1.0f : 0.86f;
  };

  GPU_blend(GPU_BLEND_ALPHA);
  draw_shade(l.shade);

  const double duration = video_session_duration(*session);
  const float progress = duration > 0.0 ?
                             float(video_session_position(*session) / duration) :
                             0.0f;
  draw_bar(l.timeline, progress, tone(PLAYER_TIMELINE));
  draw_bar(l.volume, session->muted ? 0.0f : session->volume, tone(PLAYER_VOLUME));
  GPU_blend(GPU_BLEND_NONE);

  const float line = 2.0f * u;
  const float white[4] = {1.0f, 1.0f, 1.0f, 1.0f};
  float color[4];
  auto glyph = [&](const VideoGlyph kind, const rctf &box, const int control) {
    copy_v4_v4(color, white);
    color[3] = tone(control);
    video_glyph_draw(
        kind, BLI_rctf_cent_x(&box), BLI_rctf_cent_y(&box), BLI_rctf_size_x(&box), line, color);
  };
  glyph(session->playing ? VideoGlyph::Pause : VideoGlyph::Play, l.play, PLAYER_PLAY);
  glyph(session->muted ? VideoGlyph::SoundOff : VideoGlyph::SoundOn, l.sound, PLAYER_SOUND);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name QA targets
 * \{ */

void video_player_qa_targets(const wmWindow * /*win*/,
                             const ScrArea *area,
                             const ARegion *region,
                             std::vector<MixarQATarget> &r_targets)
{
  if (region->regiontype != RGN_TYPE_WINDOW) {
    return;
  }
  const VideoPlayer *player = video_player_find(area);
  MoodboardVideoSession *session = player ? video_player_session_find(*player) : nullptr;
  if (!session) {
    return;
  }
  const std::string movie = player->image->id.name + 2;
  auto add = [&](const char *surface, const rctf &rect) -> MixarQATarget & {
    MixarQATarget t;
    t.surface = surface;
    t.text = movie;
    BLI_rcti_rctf_copy_round(&t.rect_win, &rect);
    r_targets.push_back(std::move(t));
    return r_targets.back();
  };
  const PlayerLayout l = video_player_layout(area);
  rctf whole;
  BLI_rctf_rcti_copy(&whole, &area->totrct);
  MixarQATarget &picture = add("video_player", whole);
  picture.value = std::to_string(video_session_frame(*session));
  picture.sel = session->playing;
  picture.detail = video_session_audio_state(*session);
  picture.index = session->frame_count;
  add("video_player_play", l.play).sel = session->playing;
  add("video_player_timeline", l.timeline);
  add("video_player_sound", l.sound).sel = session->muted;
  add("video_player_volume", l.volume).value = std::to_string(
      int(session->volume * 100.0f + 0.5f));
}

/** \} */

}  // namespace blender::ed::mixie
