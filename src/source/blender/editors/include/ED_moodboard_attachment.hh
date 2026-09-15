/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once

#include "BLI_rect.h"

namespace blender {
struct bContext;
struct ARegion;
struct wmOperatorType;
struct wmWindow;
/* Reject outgoing island/pill windows during native minimize handoff. */
bool ED_agent_bubble_is_attachment_destination(const wmWindow *window);
/* Publish the actual painted thumbnail slot, in region pixels. Presentation
 * only. */
void ED_moodboard_attachment_target(const bContext *C,
                                    ARegion *region,
                                    const char *image_name,
                                    const rctf &rect);
void MIXIE_OT_moodboard_attachment_flight(wmOperatorType *ot);
void mixie_attachment_qa_register();
}  // namespace blender
