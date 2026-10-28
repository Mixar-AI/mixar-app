/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup editors
 * \brief Chromeless areas: hidden regions that offer no way back.
 *
 * An editor reused as a bare surface (the moodboard video player renders its
 * movie through an Image Editor) hides its header, toolbar and sidebar, but a
 * hidden region normally keeps an edge arrow / reveal tab so the user can drag
 * it back. A chromeless area has none: area.cc asks the registered predicate
 * before it adds any edge action zone. A function pointer, so the screen
 * module needs no link dependency on the editor that owns the decision.
 */

#pragma once

namespace blender {

struct ScrArea;

using MixarAreaChromelessFn = bool (*)(const ScrArea *area);

/** Install the predicate (one owner; nullptr clears it). */
void ED_area_mixar_chromeless_set(MixarAreaChromelessFn fn);

}  // namespace blender
