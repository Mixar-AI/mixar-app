/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Media tab for the Agent island: the moodboard's Image Gen and Video Gen
 * panels re-skinned as island chips. Which controls exist comes from the
 * live generation catalog (the per-(service, model) WindowManager param
 * groups built by `modules/common/generation_params`), never from the
 * design mock — the mock is a styling guide only.
 */

#pragma once

struct ARegion;
struct bContext;
struct rctf;

/**
 * Paint the Media pane and lay its controls into the card panel.
 *
 * \param panel: the card panel rect in REGION pixel coordinates. Call where
 * the other tab panes are called (the transcript WINDOW region's draw), NOT
 * inside a translated GPU matrix — the pane builds a uiBlock.
 * \param u: island unit scale (window_native_w / AGENT_ISLAND_W).
 *
 * Reads/writes only EXISTING state: `scene.mixie_moodboard_sidebar`'s
 * `tab_imagegen` / `tab_video_gen` PropertyGroups, the catalog param groups
 * on WindowManager, and `wm.mixar_bubble_media_kind` (Image/Video sub-tab,
 * registered by `agent_bubble/ui/properties/bubble_media_props.py`).
 * Generate dispatches the same operators the moodboard footers use.
 */
void agent_ui_tabmedia_draw(const bContext *C,
                            ARegion *region,
                            const rctf &panel,
                            float u);
