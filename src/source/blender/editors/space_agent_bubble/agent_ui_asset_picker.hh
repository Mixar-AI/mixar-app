/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The agent's asset picker, drawn in place of the transcript on the Agent
 * tab while an asset question is pending (`ED_mixie_chat_asset_picker.hh`
 * holds the rule and the data).
 *
 * It is a Library look-alike on purpose — the user has just been asked to
 * choose between assets from their own library, and the Library tab is where
 * they already know what an asset looks like: the same tile plates and
 * two-line captions, the same accent selection ring, the same detail column
 * with its green primary and grey secondary action. Clicking a tile SELECTS
 * it (the Library's `wm.context_set_string` pattern); "Use This Asset"
 * answers with the selection, "Model from Scratch" and Cancel answer with
 * the backend's own buttons — all through `mixie_chat.select_slot_action`,
 * exactly as a click on the transcript's buttons would.
 */

#pragma once

namespace blender {

struct ARegion;
struct bContext;
struct rctf;
struct MixieAssetPicker;

/** The uiBlock the picker lays its buttons into (QA targets match on it). */
#define AGENT_ASSET_PICKER_BLOCK "agent_island_asset_picker"

/**
 * Paint the picker and lay its controls into \a panel.
 *
 * \param panel: the card panel rect in REGION pixel coordinates, as the pane
 * tabs receive it. Call from the WINDOW region's draw.
 * \param u: island unit scale (window_native_w / AGENT_ISLAND_W).
 */
void agent_ui_asset_picker_draw(const bContext *C,
                                ARegion *region,
                                const rctf &panel,
                                float u,
                                const MixieAssetPicker &picker);

/** QA targets for the picker's tiles and answers (`asset_pick_tile`,
 * `asset_pick_action`). */
void agent_ui_asset_picker_qa_register();

}  // namespace blender
