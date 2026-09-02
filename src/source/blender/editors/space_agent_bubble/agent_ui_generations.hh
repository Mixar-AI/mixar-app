/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * "My Generations" tab for the Agent island: the browser for everything Mixar
 * has made plus every asset library the user has connected.
 *
 * Two sources, one grid (the design's left rail switches between them):
 *  - AI generations: the auto-archived "Mixar Generations" asset library
 *    (`asset_search/core/generation_library.py` already writes it), the
 *    scene's generated moodboard media, the splat worlds in the file, and the
 *    jobs still running in the unified queue.
 *  - Asset Library: every registered asset library, browsable here and
 *    connectable from the rail ("+ Add Library…").
 *
 * Nothing here stores anything. The pane is a VIEW over data other modules
 * already own, exactly like the Queue tab is a view over `wm.mixie_queue`.
 */

#pragma once

struct ARegion;
struct bContext;
struct rctf;

/**
 * Paint the My Generations pane and lay its controls into the card panel.
 *
 * \param panel: the card panel rect in REGION pixel coordinates — the space
 * the island's uiBlocks use. Call from the WINDOW region's draw, NOT inside a
 * translated GPU matrix (a uiBlock captures the matrices at begin).
 * \param u: island unit scale (window_native_w / AGENT_ISLAND_W).
 *
 * 3D tiles carry Blender's OWN asset drag (#UI_but_drag_set_asset), so
 * dropping one in the viewport runs the View3D's existing asset dropbox with
 * asset-browser semantics — import method, undo push and placement included.
 * Nothing about the import is re-implemented here.
 */
void agent_ui_generations_draw(const bContext *C, ARegion *region, const rctf &panel, float u);
