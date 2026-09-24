/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Owned native tooltips for node actions and the prompt. */

#include "mixie_draw_moodboard_intern.hh"

#include "BLI_string.h"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

namespace blender::ed::mixie {

static std::string node_tooltip_func(bContext * /*C*/, void *argN, const StringRef /*tip*/)
{
  /* This is complete, context-specific help. Appending the generic operator
   * or RNA description repeats the action and can describe a different scope. */
  return static_cast<const char *>(argN);
}

void moodboard_set_node_tooltip(ui::Button *but, const char *text)
{
  if (!but || !text || text[0] == '\0') {
    return;
  }
  /* The button takes ownership of the copy and frees it with the block, which
   * is what makes this safe where a bare `tip` StringRef is not. */
  const size_t size = strlen(text) + 1;
  char *owned = static_cast<char *>(MEM_new_uninitialized(size, __func__));
  memcpy(owned, text, size);
  ui::button_func_tooltip_set(but, node_tooltip_func, owned, MEM_delete_void);
}

}  // namespace blender::ed::mixie
