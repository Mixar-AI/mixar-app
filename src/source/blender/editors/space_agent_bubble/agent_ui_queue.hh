/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Queue tab for the Agent island: the unified job queue (the same
 * `wm.mixie_queue` mirror the moodboard N-panel's Queue tab lists), restyled
 * to the island's palette and drawn inside the card panel.
 */

#pragma once

struct ARegion;
struct bContext;
struct rctf;

/**
 * Paint the queue rows and lay their controls into the card panel.
 *
 * \param panel: the card panel rect in REGION pixel coordinates (the same
 * space the island's uiBlocks use — call this where the composer controls are
 * built, NOT inside a translated GPU matrix, because the uiBlock captures the
 * current matrices at begin).
 * \param u: island unit scale (window_native_w / AGENT_ISLAND_W) so the row
 * metrics track the island's own type scale.
 *
 * Reads `wm.mixie_queue.items` via RNA, read-only. Newest jobs first (the
 * mirror is already sorted). Row clicks select the job via the stock
 * `wm.context_set_int` on `mixie_queue.active_index` (which runs the
 * existing queue-selection hook); active rows get a cancel cross bound to
 * `mixie.queue_cancel_job`; a "Clear finished" action appears when any
 * terminal rows exist, bound to `mixie.queue_clear_all_completed`.
 */
void agent_ui_queue_draw(const bContext *C, ARegion *region, const rctf &panel, float u);
