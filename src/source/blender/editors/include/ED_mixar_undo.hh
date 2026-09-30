/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

/** \file
 * \ingroup editors
 *
 * Mixar per-tab undo (design M4): the whole-document undo operator, defined
 * beside the stock undo operators in ``editors/undo/ed_undo.cc`` and
 * registered by the top bar (the Edit menu is its home).
 */

namespace blender {

struct bContext;
struct wmOperatorType;

void ED_OT_undo_whole_document(wmOperatorType *ot);

/** A checkpoint pushed on behalf of a scene tab from a timer or a job
 * callback: always a memfile step. #ED_undo_push picks the step type from
 * the context, and the window may show another tab whose active object is in
 * edit mode; the step would then be an edit-mesh step of THAT tab's mesh
 * tagged with this tab (review 2026-09-30, finding 6). Returns true when a
 * step was added. */
bool ED_undo_push_memfile(bContext *C, const char *str);

}  // namespace blender
