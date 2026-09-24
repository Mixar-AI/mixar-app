/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Private helpers shared by the asset picker's grid pass
 * (`agent_ui_asset_picker.cc`) and its detail column
 * (`agent_ui_asset_picker_detail.cc`).
 */

#pragma once

#include "agent_ui_asset_picker_layout.hh"

namespace blender {

struct Image;
struct bContext;
struct rctf;
struct MixieAssetPick;
struct MixieAssetPicker;
namespace ui {
struct Block;
}

/** The pick's locally generated preview, or null while it is still queued
 * (`asset_choice_previews.py` fills one per tick) or when generation failed. */
Image *agent_ui_asset_pick_image(const bContext *C, const MixieAssetPick &pick);

/** Aspect-fit the pick's preview inside \a box, or the Library's dim mesh
 * placeholder while it has no pixels. */
void agent_ui_asset_pick_thumb(const bContext *C, const MixieAssetPick &pick, const rctf &box);

/** "Object" / "Collection" / "Asset" — the caption's first word. */
void agent_ui_asset_pick_type_label(const MixieAssetPick &pick, char r_out[32]);

/** "92%" (\a with_word false) or "92% match"; empty when no score was sent. */
void agent_ui_asset_pick_match_label(const MixieAssetPick &pick, bool with_word, char r_out[32]);

/** Break \a text into at most two lines that each fit \a max_w, at a space
 * where possible; the second line takes an ellipsis when text is left over. */
void agent_ui_asset_pick_wrap(
    const char *text, float max_w, float font, char r_a[256], char r_b[256]);

/** One answer button: `mixie_chat.select_slot_action` with the pending
 * bubble and \a value — the same operator a transcript button click runs. */
void agent_ui_asset_pick_answer_button(ui::Block *block,
                                       const rctf &rect,
                                       const MixieAssetPicker &picker,
                                       const char *value,
                                       const char *tip);

/** Paint + lay out the detail column for the selected pick. */
void agent_ui_asset_picker_detail(const bContext *C,
                                  ui::Block *block,
                                  const rctf &panel,
                                  const PickFrame &frame,
                                  const MixieAssetPicker &picker);

}  // namespace blender
