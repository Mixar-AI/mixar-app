/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Standard message action-button interaction handling.
 */

#include "MEM_guardedalloc.h"

#include "BLI_string.h"
#include "BLI_time.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "ED_screen.hh"

#include "UI_view2d.hh"

#include "WM_api.hh"

#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

static SpaceMixieChat *get_space_mixie_chat(const bContext *C)
{
  ScrArea *area = CTX_wm_area(C);
  if (area && (area->spacetype == SPACE_MIXIE_CHAT ||
               area->spacetype == SPACE_AGENT_BUBBLE))
  {
    return static_cast<SpaceMixieChat *>(area->spacedata.first);
  }
  return nullptr;
}

bool mixie_chat_handle_action_button_click(bContext *C,
                                           ARegion *region,
                                           float mouse_x,
                                           float mouse_y)
{
  SpaceMixieChat *smixie = get_space_mixie_chat(C);
  if (!smixie) {
    return false;
  }
  const blender::Vector<MessageLayoutData> &layout_cache = mixie_chat_get_layout_cache(smixie);

  View2D *v2d = &region->v2d;
  ui::view2d_region_to_view(v2d, mouse_x, mouse_y, &mouse_x, &mouse_y);

  for (const MessageLayoutData &layout : layout_cache) {
    if (layout.action_button_count == 0) {
      continue;
    }

    const int action = chat_ui_handle_action_click(
        mouse_x, mouse_y, layout.action_buttons, layout.action_button_count);
    if (action != CHAT_ACTION_COPY) {
      continue;
    }

    /* Use text cached during layout; avoid a stale RNA collection lookup. */
    const char *text_to_copy = layout.copy_text;
    char *todo_text = nullptr;
    if (!text_to_copy && layout.slot_todo_count > 0) {
      char combined[SLOT_TODO_COMBINED_MAX];
      const size_t offset = mixie_chat_build_todo_text(layout.slot_todo_items,
                                                       layout.slot_todo_count,
                                                       "\xe2\x97\x8f",
                                                       combined,
                                                       sizeof(combined));
      if (offset > 0) {
        todo_text = BLI_strdupn(combined, offset);
        text_to_copy = todo_text;
      }
    }

    if (text_to_copy) {
      WM_clipboard_text_set(text_to_copy, false);
      MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
      rt->copy_feedback_msg_index = layout.message_index;
      rt->copy_feedback_time = BLI_time_now_seconds();
    }
    if (todo_text) {
      MEM_delete_void(todo_text);
    }
    ED_region_tag_redraw(region);
    return true;
  }

  return false;
}
}  // namespace blender
