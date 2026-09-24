/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Reader for the agent's pending asset question — see
 * `ED_mixie_chat_asset_picker.hh` for the rule. Every value is read through
 * RNA by its stable name (enum values by IDENTIFIER), exactly like the
 * island's other panes, so an absent Python property reads as "no picker"
 * rather than a crash.
 */

#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_scene_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "ED_mixie_chat_asset_picker.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* The chat's modal surfaces (mixie_chat_{rules,history,ink}_util.cc). Declared
 * rather than included: their intern headers are not self-contained. */
bool mixie_chat_rules_read_visible(wmWindowManager *wm);
bool mixie_chat_history_read_visible(wmWindowManager *wm);
bool mixie_chat_ink_read_visible(wmWindowManager *wm);

namespace {

/** Guarded string read — never the bare getter, which is strcpy-shaped. */
void read_string(PointerRNA *ptr, const char *name, char *out, const int out_maxncpy)
{
  out[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return;
  }
  char fixed[512];
  int len = 0;
  char *value = RNA_property_string_get_alloc(ptr, prop, fixed, sizeof(fixed), &len);
  if (value) {
    BLI_strncpy(out, value, out_maxncpy);
    if (value != fixed) {
      MEM_delete(value);
    }
  }
}

float read_float(PointerRNA *ptr, const char *name, const float fallback)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return (prop && RNA_property_type(prop) == PROP_FLOAT) ? RNA_property_float_get(ptr, prop) :
                                                           fallback;
}

/** Does the enum \a name currently hold the item \a identifier? */
bool enum_is(PointerRNA *ptr, const char *name, const char *identifier)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_ENUM) {
    return false;
  }
  const char *ident = nullptr;
  return RNA_property_enum_identifier(
             nullptr, ptr, prop, RNA_property_enum_get(ptr, prop), &ident) &&
         ident && STREQ(ident, identifier);
}

/** Copy one action item into the picker: an asset pick (the first five), the
 * Cancel answer, or the plain "Model from scratch" answer. */
void read_action(PointerRNA *item, MixieAssetPicker *picker)
{
  char asset_name[256];
  read_string(item, "asset_name", asset_name, sizeof(asset_name));
  char value[256];
  read_string(item, "value", value, sizeof(value));
  char label[256];
  read_string(item, "label", label, sizeof(label));

  if (asset_name[0]) {
    if (picker->count >= MIXIE_ASSET_PICKER_MAX) {
      return; /* The top five only. */
    }
    MixieAssetPick &pick = picker->picks[picker->count++];
    BLI_strncpy(pick.asset_name, asset_name, sizeof(pick.asset_name));
    BLI_strncpy(pick.value, value, sizeof(pick.value));
    BLI_strncpy(pick.label, label[0] ? label : asset_name, sizeof(pick.label));
    read_string(item, "library", pick.library, sizeof(pick.library));
    read_string(item, "asset_type", pick.asset_type, sizeof(pick.asset_type));
    read_string(item, "image", pick.image, sizeof(pick.image));
    pick.score = read_float(item, "score", -1.0f);
    return;
  }
  if (enum_is(item, "style", "DANGER") || STREQ(value, "abort")) {
    if (!picker->cancel_value[0]) {
      BLI_strncpy(picker->cancel_value, value, sizeof(picker->cancel_value));
    }
    return;
  }
  if (!picker->scratch_value[0] && value[0]) {
    BLI_strncpy(picker->scratch_value, value, sizeof(picker->scratch_value));
    BLI_strncpy(picker->scratch_label, label[0] ? label : value, sizeof(picker->scratch_label));
  }
}

/** The WM selection -> an index into the picks; the best match otherwise. */
int selected_index(const bContext *C, const MixieAssetPicker &picker)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return 0;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  char selected[256];
  read_string(&wm_ptr, MIXIE_ASSET_PICKER_SELECTED_PROP, selected, sizeof(selected));
  if (!selected[0]) {
    return 0;
  }
  for (int i = 0; i < picker.count; i++) {
    if (STREQ(picker.picks[i].value, selected)) {
      return i;
    }
  }
  return 0;
}

}  // namespace

bool mixie_chat_asset_picker_gather(const bContext *C, MixieAssetPicker *r_picker)
{
  memset(r_picker, 0, sizeof(*r_picker));
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return false;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  if (!enum_is(&scene_ptr, "mixie_chat_state", "AWAITING_INPUT")) {
    return false;
  }
  PropertyRNA *messages = RNA_struct_find_property(&scene_ptr, "mixie_chat_messages");
  if (!messages || RNA_property_type(messages) != PROP_COLLECTION) {
    return false;
  }

  /* The newest AGENT message still carrying an input_type is the pending
   * question (`question_ref.pending_interrupt_id`); an older one is answered. */
  const int length = RNA_property_collection_length(&scene_ptr, messages);
  for (int i = length - 1; i >= 0; i--) {
    PointerRNA message;
    if (!RNA_property_collection_lookup_int(&scene_ptr, messages, i, &message)) {
      continue;
    }
    if (!enum_is(&message, "sender", "AGENT")) {
      continue;
    }
    char input_type[32];
    read_string(&message, "input_type", input_type, sizeof(input_type));
    if (!input_type[0]) {
      continue;
    }
    if (!STREQ(input_type, "choice")) {
      return false;
    }
    PropertyRNA *actions = RNA_struct_find_property(&message, "action_items");
    if (!actions || RNA_property_type(actions) != PROP_COLLECTION) {
      return false;
    }
    CollectionPropertyIterator iter;
    RNA_property_collection_begin(&message, actions, &iter);
    for (; iter.valid; RNA_property_collection_next(&iter)) {
      PointerRNA item = iter.ptr;
      read_action(&item, r_picker);
    }
    RNA_property_collection_end(&iter);

    if (r_picker->count == 0) {
      memset(r_picker, 0, sizeof(*r_picker));
      return false;
    }
    read_string(&message, "bubble_id", r_picker->bubble_id, sizeof(r_picker->bubble_id));
    read_string(&message, "content", r_picker->question, sizeof(r_picker->question));
    if (!r_picker->question[0]) {
      read_string(&message, "text", r_picker->question, sizeof(r_picker->question));
    }
    r_picker->selected = selected_index(C, *r_picker);
    return true;
  }
  return false;
}

bool mixie_chat_asset_picker_shown(const bContext *C, MixieAssetPicker *r_picker)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (mixie_chat_rules_read_visible(wm) || mixie_chat_history_read_visible(wm) ||
      mixie_chat_ink_read_visible(wm))
  {
    return false;
  }
  MixieAssetPicker local;
  return mixie_chat_asset_picker_gather(C, r_picker ? r_picker : &local);
}

}  // namespace blender
