/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edmixaraudio
 *
 * Reading the voice session's state from C++ draw code.
 *
 * The session itself is Python (`modules/voice/core/session.py`) and mirrors
 * itself onto the WindowManager; this is the ONE place C++ reads that mirror,
 * so the chat footer and the moodboard node tile cannot drift into two
 * different ideas of what "recording" means.
 *
 * Both readers are safe from a draw pass — they read registered RNA, allocate
 * nothing on the common path, and fall back to Idle whenever the voice module
 * has not registered yet (startup ordering), which is the honest answer: with
 * no session there is nothing recording.
 */

#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_string.h"
#include "BLI_utildefines.h" /* STREQ */

#include "BKE_context.hh"

#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "ED_mixar_audio_ui.hh"

/* Mixar 5.2 port: namespace wrap. Every include stays ABOVE this line -- a
 * header pulled in after it would land in `blender::blender`. */
namespace blender {

namespace {

/* `RNA_property_string_get` is strcpy-shaped, so a property with no `maxlen`
 * would overrun a stack buffer. Read the length first. */
void read_string_bounded(PointerRNA *ptr, const char *name, char *dst, int dst_maxncpy)
{
  if (dst == nullptr || dst_maxncpy <= 0) {
    return;
  }
  dst[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (prop == nullptr || RNA_property_type(prop) != PROP_STRING) {
    return;
  }
  if (RNA_property_string_length(ptr, prop) < dst_maxncpy) {
    RNA_property_string_get(ptr, prop, dst);
    return;
  }
  int allocated = 0;
  char *value = RNA_property_string_get_alloc(ptr, prop, nullptr, 0, &allocated);
  if (value != nullptr) {
    BLI_strncpy(dst, value, dst_maxncpy);
    /* 5.2: MEM_freeN is gone for a raw buffer; same port as the identically
     * shaped RNA string read in mixie_chat_slots.cc. */
    MEM_delete_void(static_cast<void *>(value));
  }
}

}  // namespace

MixarVoiceVisual ED_mixar_voice_visual_state(const bContext *C)
{
  wmWindowManager *wm = C ? CTX_wm_manager(C) : nullptr;
  if (wm == nullptr) {
    return MixarVoiceVisual::Idle;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixar_voice_state");
  if (prop == nullptr) {
    return MixarVoiceVisual::Idle;
  }

  /* By IDENTIFIER, never by the enum's integer: an enum persists as an index,
   * so reading the value would silently repoint every state if an item were
   * ever inserted into the list. */
  const int value = RNA_property_enum_get(&wm_ptr, prop);
  const char *identifier = nullptr;
  if (!RNA_property_enum_identifier(
          const_cast<bContext *>(C), &wm_ptr, prop, value, &identifier) ||
      identifier == nullptr)
  {
    return MixarVoiceVisual::Idle;
  }
  if (STREQ(identifier, "RECORDING")) {
    return MixarVoiceVisual::Recording;
  }
  if (STREQ(identifier, "TRANSCRIBING")) {
    return MixarVoiceVisual::Transcribing;
  }
  if (STREQ(identifier, "ERROR")) {
    return MixarVoiceVisual::Error;
  }
  return MixarVoiceVisual::Idle;
}

bool ED_mixar_voice_target_is(const bContext *C, const char *target)
{
  wmWindowManager *wm = C ? CTX_wm_manager(C) : nullptr;
  if (wm == nullptr || target == nullptr) {
    return false;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  char current[128];
  read_string_bounded(&wm_ptr, "mixar_voice_target", current, sizeof(current));
  return STREQ(current, target);
}

}  // namespace blender
