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

struct wmOperatorType;

void ED_OT_undo_whole_document(wmOperatorType *ot);

}  // namespace blender
