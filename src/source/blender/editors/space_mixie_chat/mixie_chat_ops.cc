/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Native agent operators and transcript keymap, owned by the floating bubble. */
#include "WM_api.hh"
#include "WM_types.hh"
#include "DNA_space_types.h"
#include "mixie_chat_intern.hh"

namespace blender {

void mixie_chat_operatortypes()
{
  WM_operatortype_append(MIXIE_CHAT_OT_select_text);
  WM_operatortype_append(MIXIE_CHAT_OT_copy);
  WM_operatortype_append(MIXIE_CHAT_OT_drop_image);
  WM_operatortype_append(MIXIE_CHAT_OT_drop_asset_pick);
  WM_operatortype_append(MIXIE_CHAT_OT_agent_bubble_show);
  WM_operatortype_append(MIXIE_CHAT_OT_retitle_document);
  WM_operatortype_append(MIXIE_CHAT_OT_undo_stamp);
  WM_operatortype_append(MIXIE_CHAT_OT_ink_flush);
  WM_operatortype_append(MIXIE_CHAT_OT_ink_release_composer);
  WM_operatortype_append(MIXIE_CHAT_OT_focus_composer);
  WM_operatortype_append(MIXIE_CHAT_OT_ink_recognize_local);
  WM_operatortype_append(MIXIE_CHAT_OT_ink_local_poll);
  WM_operatortype_append(MIXIE_CHAT_OT_voice_start);
  WM_operatortype_append(MIXIE_CHAT_OT_voice_stop);
  WM_operatortype_append(MIXIE_CHAT_OT_voice_poll);
  WM_operatortype_append(MIXIE_CHAT_OT_lightbox);
}

void mixie_chat_keymap(wmKeyConfig *keyconf)
{
  wmKeyMap *keymap = WM_keymap_ensure(keyconf, "Agent Chat", SPACE_AGENT_BUBBLE, RGN_TYPE_WINDOW);

  /* Text selection with mouse drag */
  KeyMapItem_Params select_params{};
  select_params.type = LEFTMOUSE;
  select_params.value = KM_PRESS;
  select_params.modifier = 0;
  WM_keymap_add_item(keymap, "MIXIE_CHAT_OT_select_text", &select_params);

  /* Copy with Cmd+C (macOS) / Ctrl+C (other platforms) */
  KeyMapItem_Params copy_params{};
  copy_params.type = EVT_CKEY;
  copy_params.value = KM_PRESS;
#ifdef __APPLE__
  copy_params.modifier = KM_OSKEY;
#else
  copy_params.modifier = KM_CTRL;
#endif
  WM_keymap_add_item(keymap, "MIXIE_CHAT_OT_copy", &copy_params);

  /* Ctrl+V / Cmd+V: paste image or text into chat.
   * The transcript registers this keymap; the composer's text field handles
   * paste through the native UI handler.
   *
   * MIXIE_CHAT_OT_paste, not MIXIE_CHAT_OT_paste_image: this chord fires
   * when the composer does NOT hold text-edit focus, and paste_image
   * returns CANCELLED for a clipboard that holds no image, so a text paste
   * arriving here used to be dropped without a trace. The unified operator
   * attaches an image if there is one and appends the text otherwise.
   * (The inline hook in interface_handlers.cc still calls paste_image
   * directly — it needs the CANCELLED to fall back to its own
   * cursor-accurate ui_textedit_copypaste.)
   *
   * The Python addon keyconfig registers this chord too
   * (space_mixie_chat/ui/keymap.py); it has to, because the GUI keyconfig
   * preset reload wipes items from C-registered default-config keymaps. */
  KeyMapItem_Params paste_params{};
  paste_params.type = EVT_VKEY;
  paste_params.value = KM_PRESS;
#ifdef __APPLE__
  paste_params.modifier = KM_OSKEY;
#else
  paste_params.modifier = KM_CTRL;
#endif
  WM_keymap_add_item(keymap, "MIXIE_CHAT_OT_paste", &paste_params);
}

}  // namespace blender
