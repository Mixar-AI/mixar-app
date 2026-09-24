/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Voice control artwork shared by the island's Voice chip and the minimised
 * Sketch pill: the stop square and the live ECG trace. Timing and shape come
 * from `agent_ui_voice_motion.hh`; these only paint. Expect `GPU_blend` ALPHA.
 */

#pragma once

#include "BLI_rect.h"

namespace blender {

struct ARegion;

/** Rounded stop square centred in \a box. */
void agent_ui_draw_stop_glyph(const rctf &box, const float color[4]);

/** The ECG trace across \a box at \a now, its height following \a level. */
void agent_ui_draw_voice_wave(const rctf &box, double now, float level, const float color[4]);

/**
 * Voice chip contents at its fitted \a form (#agent_chip_fit). Capturing:
 * stop + "Stop" + ECG (0), stop + "Stop" (1), stop (2). Otherwise the mic with
 * \a label (0) or alone (1). While the trace is drawn in \a region, the shared
 * motion scheduler keeps that region repainting; nothing else redraws.
 */
void agent_ui_draw_voice_chip(ARegion *region,
                              const rctf &chip,
                              int form,
                              bool capturing,
                              const char *label,
                              float level,
                              float text_size,
                              float icon_edge,
                              float icon_gap,
                              float wave_w,
                              const float color[4],
                              const float fill[4]);

}  // namespace blender
