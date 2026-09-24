/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the timeline dock's ACTIONS row — Auto Key and Add Keyframe,
 * centred on their own row under the transport.
 *
 * They used to sit at the dock's right edge, at the far end of a row whose
 * other half is the ruler. Adding a keyframe is the job in Cinema Mode and
 * the transport is where the eye already is, so the group moved under the
 * play button: a sub-row of its own rather than one more thing competing for
 * the right margin, which the interpolation dropdown now owns.
 *
 * TWO controls, not three. Auto Key used to have a Record chip beside it,
 * which is a distinction Blender does not have and a director does not want
 * to make: Blender ships one auto-key switch, and a second toggle next to it
 * wearing the same chip asks "which of these do I want?" about an
 * implementation detail. One switch answers to what the director is doing —
 * a keyframe when the camera stops, a recorded take while the timeline plays
 * and something is driving it (`core/record.py`). The chip says which it is
 * doing, because a take being laid down is worth seeing.
 *
 * And that one switch IS Blender's: the chip is an RNA toggle on
 * `scene.tool_settings.use_keyframe_insert_auto`, the property the Timeline's
 * record button flips. It used to be a Director-only flag behind a Director
 * operator, so the Timeline could show auto-keying off while Cinema Mode had
 * it on, and Blender's own auto-keying never fired for a Cinema session.
 *
 * Split from `view3d_director_cinema_dock.cc` along the seam the dock's
 * layout already uses — one file per group — and to keep that file inside the
 * module size limit.
 *
 * Painting only; every control is a real ui::Button over the painted pixels.
 */

#include <algorithm>

#include "BLI_rect.h"

#include "BKE_context.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_overlay_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/** The primary action pill: height, side padding, and text-to-keycap gap. */
constexpr float ACTION_H = 30.0f;
constexpr float ACTION_PAD = 14.0f;
constexpr float ACTION_KEY_GAP = 8.0f;
/** Clear space between the chips and the button they qualify. */
constexpr float ACTION_GAP = 12.0f;
/**
 * The Auto Key chip: Blender's Auto Keying toggle over the surface's chrome.
 *
 * Green fill says ARMED, which is how every other state chip on this surface
 * reads (the grid chip, the tracking eyedropper, the walk chip). The button
 * is an RNA toggle on the scene's tool settings (#cinema_prop_toggle), so a
 * click is Blender flipping its own property, with its own notifier and undo,
 * exactly as the Timeline's record button does.
 */
void auto_key_chip(ui::Block *block,
                   const bContext *C,
                   const ARegion *region,
                   const rctf &chip,
                   const DirectorViewState &state)
{
  const bool armed = state.auto_key;
  if (armed) {
    MIXAR_THEME_LOAD(on, Primary);
    cinema_fill(chip, BLI_rctf_size_y(&chip) * 0.5f, on);
  }
  else {
    MIXAR_THEME_LOAD(top, CinemaRowTop);
    MIXAR_THEME_LOAD(bottom, CinemaRowBottom);
    cinema_panel(chip, BLI_rctf_size_y(&chip) * 0.5f, top, bottom);
  }
  cinema_qa_record(region, chip, "director_auto_key", armed ? "on" : "off", -1);
  Scene *scene = CTX_data_scene(const_cast<bContext *>(C));
  if (scene == nullptr) {
    return;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PointerRNA tool_settings_ptr = RNA_pointer_get(&scene_ptr, "tool_settings");
  /* Blender's own timeline flips RECORD_OFF to RECORD_ON when auto-keying is
   * armed (`rna_scene.cc` ui_icon); REC says a take is actually going down,
   * which `state.recording` publishes from the recorder. Tooltips are
   * literals: `ui::Button::tip` is non-owning. */
  ui::Button *but = cinema_prop_toggle(
      block,
      &tool_settings_ptr,
      "use_keyframe_insert_auto",
      state.recording ? ICON_REC : (armed ? ICON_RECORD_ON : ICON_RECORD_OFF),
      chip,
      state.recording ? "Recording a take: every frame the timeline plays is keyed" :
      armed ? "Auto Keying is on (the Timeline's record button): a keyframe after every "
              "camera move, and a recorded take while the timeline plays" :
              "Auto Keying (the Timeline's record button): key the camera automatically "
              "after every move, and record a take while the timeline plays");
  director_overlay_disable_button(but, !state.has_camera);
}

}  // namespace

void cinema_draw_dock_actions(ui::Block *block,
                              const bContext *C,
                              const ARegion *region,
                              const DirectorViewState &state,
                              const float cy)
{
  const float u = cinema_unit();
  const bool locked = state.locked;
  const char *label = locked ? "New Take" : "Add Keyframe";
  const char *key = locked ? nullptr : "I";
  const char *tip = locked ? "Start an editable child take" :
                             "Key the live camera pose as a keyframe (I)";

  /* The pill is sized to its own text: "New Take" and "Add Keyframe" are
   * different widths and a fixed box would clip one of them. */
  const float font = CINEMA_FONT_VALUE * u;
  const float text_w = cinema_text_width(label, font);
  const float key_w = key != nullptr ? (CINEMA_KEYCAP_W + ACTION_KEY_GAP) * u : 0.0f;
  const float pill_w = text_w + key_w + ACTION_PAD * 2.0f * u;
  const float chips_w = locked ? 0.0f : (ACTION_H + ACTION_GAP) * u;
  /* The GROUP is centred, not the pill: centring the pill alone would push
   * Auto Key off to one side of a row that is meant to read as one thing.
   * Floored at the dock's own inset, so a group wider than the dock starts
   * at the edge rather than off it. */
  float x = std::max((float(region->winx) - (chips_w + pill_w)) * 0.5f, ACTION_GAP * u);
  const float half = ACTION_H * u * 0.5f;

  if (!locked) {
    /* ONE chip. Armed is armed, and while a take is actually going down it
     * says so — `state.recording` is published by the recorder, not by a
     * second button. Blender's own timeline flips RECORD_OFF to RECORD_ON
     * when auto-keying is armed (`rna_scene.cc` ui_icon), and mirroring that
     * is what makes the chip read as armed rather than just-pressed. */
    const rctf chip = {x, x + ACTION_H * u, cy - half, cy + half};
    auto_key_chip(block, C, region, chip, state);
    x += (ACTION_H + ACTION_GAP) * u;
  }

  const rctf pill = {x, x + pill_w, cy - half, cy + half};
  MIXAR_THEME_LOAD(fill, Primary);
  cinema_fill(pill, BLI_rctf_size_y(&pill) * 0.5f, fill);
  /* The label carries the disabled state: an Emboss::None button paints
   * nothing of its own, so nothing else would show that it cannot fire. */
  const bool enabled = state.has_camera;
  const float text[4] = {1.0f, 1.0f, 1.0f, enabled ? 1.0f : 0.45f};
  cinema_text_left(label, pill.xmin + ACTION_PAD * u, cy, font, text);
  if (key != nullptr) {
    cinema_keycap(pill.xmin + ACTION_PAD * u + text_w + ACTION_KEY_GAP * u,
                  cy - CINEMA_KEYCAP_H * u * 0.5f,
                  key);
  }

  cinema_qa_record(region, pill, "director_capture", locked ? "new_take" : "capture", -1);
  ui::Button *but = cinema_op_button(
      block, locked ? "MIXAR_OT_director_new_take" : "MIXAR_OT_director_capture_beat", pill, tip);
  director_overlay_disable_button(but, !enabled);
}

}  // namespace blender
