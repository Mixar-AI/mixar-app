/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup editors
 *
 * The agent's pending asset question, read from the chat's own state.
 *
 * When the agent searches the user's trained asset library and finds several
 * close matches it pauses with a `choice` question whose buttons carry asset
 * identity. While that question is pending the Agent Bubble's Agent tab shows
 * ONLY its picks, as a Library-style grid (`agent_ui_asset_picker.cc`), and
 * the transcript's click dispatch stands down (`mixie_chat_main_region.cc`).
 *
 * Nothing stores "the picker is open": the rule is derived on every read from
 * the same three facts `space_mixie_chat/core/asset_picker.py` checks —
 *  - `scene.mixie_chat_state` is AWAITING_INPUT,
 *  - the newest AGENT message with an `input_type` asks a `choice`,
 *  - that message still has action items with an `asset_name`.
 * Answering (a pick, "Model from scratch", Cancel or a typed reply) clears the
 * items or leaves AWAITING_INPUT, so the transcript returns by itself.
 */

#pragma once

namespace blender {

struct bContext;

/** The backend's top five (`asset_picker.MAX_ASSET_PICKS`, backend
 * `user_input.MAX_ASSET_OPTIONS`). Extra asset buttons are never shown. */
#define MIXIE_ASSET_PICKER_MAX 5

/** WindowManager string holding the selected pick's action value. */
#define MIXIE_ASSET_PICKER_SELECTED_PROP "mixie_chat_asset_pick_selected"

/** Payload prefix of a picker tile's name drag (#WM_DRAG_NAME): the prefix,
 * then the pick's action value. The View3D dropbox in
 * `space_mixie_chat/mixie_chat_asset_picker_drop.cc` accepts exactly this
 * and places the pick where it is dropped. Readable on purpose: the drag
 * draws its payload as the item name beside the preview. */
#define MIXIE_ASSET_PICK_DRAG_PREFIX "Use library asset: "

struct MixieAssetPick {
  /** Button label — also the answer the backend matches. */
  char label[256];
  /** Action value sent through `mixie_chat.select_slot_action`. */
  char value[256];
  char asset_name[256];
  char library[256];
  char asset_type[32];
  /** `bpy.data.images` name of the locally generated preview (may not exist
   * yet — the preview queue fills it in one tick at a time). */
  char image[64];
  /** Search similarity 0-1, or a negative number when the backend sent none. */
  float score;
};

struct MixieAssetPicker {
  char bubble_id[128];
  /** The question text (the bubble's content). */
  char question[512];
  MixieAssetPick picks[MIXIE_ASSET_PICKER_MAX];
  int count;
  /** "Model from scratch": the one plain, non-danger button. Empty if absent. */
  char scratch_value[256];
  char scratch_label[256];
  /** Cancel ("abort", danger style). Empty if absent. */
  char cancel_value[64];
  /** Index into #picks of the WM selection; 0 (the best match) when the
   * selection is empty or names no current pick. */
  int selected;
};

/**
 * Fill \a r_picker with the pending asset question.
 * \return false (and a zeroed \a r_picker) when no asset question is pending.
 */
bool mixie_chat_asset_picker_gather(const bContext *C, MixieAssetPicker *r_picker);

/**
 * Is the picker what the Agent tab shows right now? An asset question is
 * pending AND none of the chat's modal surfaces the user opened on top of the
 * transcript (project rules, past chats, the Scribble ink canvas) is up —
 * those keep drawing and receiving events as before, and the picker comes
 * back when they close. The island's draw and the transcript's click
 * dispatch both ask THIS, so they can never disagree about who owns a click.
 *
 * \param r_picker: optional; filled when the picker is shown.
 */
bool mixie_chat_asset_picker_shown(const bContext *C, MixieAssetPicker *r_picker);

}  // namespace blender
