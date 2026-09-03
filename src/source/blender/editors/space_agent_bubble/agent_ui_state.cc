/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Reads the island's live state off the properties the chat already owns.
 *
 * Every value here comes from an EXISTING property — this file introduces no
 * state of its own. The mapping, once, so it is auditable:
 *
 *   status text   scene.mixie_chat_state   (the enum item's own UI name)
 *   status dot    scene.mixie_chat_is_busy
 *   title         the wm.mixie_chat_history_entries row whose session_id
 *                 matches scene.mixie_session_id
 *   segmented     scene.mixie_chat_mode == 'AGENT'
 *   placeholder   shown while scene.mixie_chat_input is empty
 *   queue count   live rows in wm.mixie_queue.items
 *
 * Called from the draw callback, so it only ever READS: a draw callback runs
 * on every mouse move, and writing a property from one is how the chat's
 * redraw loops started.
 */

#include <algorithm>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_string.h"

#include "BKE_context.hh"

#include "DNA_scene_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "agent_ui_draw.hh"
#include "agent_ui_layout.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

void read_string_prop(PointerRNA *ptr, const char *name, char *out, const int out_maxncpy)
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

bool read_bool_prop(PointerRNA *ptr, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return (prop && RNA_property_type(prop) == PROP_BOOLEAN) ?
             RNA_property_boolean_get(ptr, prop) :
             false;
}

/** The enum item's UI name — the label the property itself already carries. */
void read_enum_name(PointerRNA *ptr, const char *name, char *out, const int out_maxncpy)
{
  out[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_ENUM) {
    return;
  }
  const int value = RNA_property_enum_get(ptr, prop);
  const char *label = nullptr;
  if (RNA_property_enum_name_gettexted(nullptr, ptr, prop, value, &label) && label) {
    BLI_strncpy(out, label, out_maxncpy);
  }
}

bool enum_is(PointerRNA *ptr, const char *name, const char *identifier)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_ENUM) {
    return false;
  }
  const int value = RNA_property_enum_get(ptr, prop);
  const char *ident = nullptr;
  if (RNA_property_enum_identifier(nullptr, ptr, prop, value, &ident) && ident) {
    return STREQ(ident, identifier);
  }
  return false;
}

/**
 * Title of the history row for the session this scene is on.
 *
 * The chat has no "current session title" property — the title lives only on
 * the history rows the history overlay already draws from. Matching on
 * session_id reuses that rather than adding a second source of truth.
 */
void read_session_title(wmWindowManager *wm,
                        const char *session_id,
                        char *out,
                        const int out_maxncpy)
{
  out[0] = '\0';
  if (!wm || !session_id || session_id[0] == '\0') {
    return;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *entries = RNA_struct_find_property(&wm_ptr, "mixie_chat_history_entries");
  if (!entries) {
    return;
  }

  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&wm_ptr, entries, &iter);
  for (; iter.valid; RNA_property_collection_next(&iter)) {
    char sid[128];
    read_string_prop(&iter.ptr, "session_id", sid, sizeof(sid));
    if (STREQ(sid, session_id)) {
      read_string_prop(&iter.ptr, "name", out, out_maxncpy);
      break;
    }
  }
  RNA_property_collection_end(&iter);
}

/** Rows the unified queue mirror is currently showing as unfinished. */
int read_queue_count(wmWindowManager *wm)
{
  if (!wm) {
    return 0;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *queue_prop = RNA_struct_find_property(&wm_ptr, "mixie_queue");
  if (!queue_prop || RNA_property_type(queue_prop) != PROP_POINTER) {
    return 0;
  }
  PointerRNA queue = RNA_property_pointer_get(&wm_ptr, queue_prop);
  PropertyRNA *items = RNA_struct_find_property(&queue, "items");
  if (!items) {
    return 0;
  }

  int count = 0;
  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&queue, items, &iter);
  for (; iter.valid; RNA_property_collection_next(&iter)) {
    char state[64];
    read_string_prop(&iter.ptr, "state", state, sizeof(state));
    /* Terminal rows stay in the mirror as history; the pill counts live work. */
    if (!STREQ(state, "SUCCESS") && !STREQ(state, "FAILED") &&
        !STREQ(state, "CANCELLED"))
    {
      count++;
    }
  }
  RNA_property_collection_end(&iter);
  return count;
}

}  // namespace

void agent_ui_state_gather(const bContext *C, AgentIslandState *r_state)
{
  *r_state = {};

  r_state->active_tab = AGENT_TAB_AGENT;  /* overwritten from wm below */
  r_state->splat_is_new = true;
  r_state->placeholder = "Describe your scene here...";
  r_state->agent_mode = true;
  BLI_strncpy(r_state->title, "New Chat", sizeof(r_state->title));

  Scene *scene = CTX_data_scene(C);
  wmWindowManager *wm = CTX_wm_manager(C);

  if (wm) {
    /* Which content the card shows — wm.mixar_bubble_tab, a WindowManager
     * enum registered in agent_bubble/ui/properties/bubble_tab_props.py.
     * Falls back to AGENT before Python registers it. */
    /* Match on stable enum IDENTIFIERS, never display names. */
    PointerRNA wm_tab_ptr = RNA_id_pointer_create(&wm->id);
    const struct {
      const char *id;
      AgentTabId tab;
    } tab_map[] = {
        {"AGENT", AGENT_TAB_AGENT},
        {"THREE_D", AGENT_TAB_3D},
        {"MEDIA", AGENT_TAB_MEDIA},
        {"SPLAT", AGENT_TAB_SPLAT},
        {"GENERATIONS", AGENT_TAB_GENERATIONS},
        {"QUEUE", AGENT_TAB_QUEUE},
    };
    for (const auto &m : tab_map) {
      if (enum_is(&wm_tab_ptr, "mixar_bubble_tab", m.id)) {
        r_state->active_tab = m.tab;
        break;
      }
    }
  }

  if (scene) {
    PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);

    read_enum_name(&scene_ptr, "mixie_chat_state", r_state->status_text,
                   sizeof(r_state->status_text));
    r_state->status_busy = read_bool_prop(&scene_ptr, "mixie_chat_is_busy");
    r_state->agent_mode = enum_is(&scene_ptr, "mixie_chat_mode", "AGENT");

    char input[512];
    read_string_prop(&scene_ptr, "mixie_chat_input", input, sizeof(input));
    r_state->prompt_empty = (input[0] == '\0');

    PropertyRNA *messages = RNA_struct_find_property(&scene_ptr, "mixie_chat_messages");
    r_state->has_transcript =
        messages && RNA_property_collection_length(&scene_ptr, messages) > 0;

    /* Newest USER message -> pill preview. Walk the whole collection (no
     * reverse iterator on RNA collections) keeping the last match. */
    if (messages) {
      CollectionPropertyIterator iter;
      RNA_property_collection_begin(&scene_ptr, messages, &iter);
      for (; iter.valid; RNA_property_collection_next(&iter)) {
        PointerRNA item = iter.ptr;
        if (!enum_is(&item, "sender", "USER")) {
          continue;
        }
        PropertyRNA *text_prop = RNA_struct_find_property(&item, "text");
        if (!text_prop || RNA_property_type(text_prop) != PROP_STRING) {
          continue;
        }
        char text[160];
        read_string_prop(&item, "text", text, sizeof(text));
        if (text[0]) {
          BLI_strncpy(r_state->last_prompt, text, sizeof(r_state->last_prompt));
        }
      }
      RNA_property_collection_end(&iter);
    }

    char session_id[128];
    read_string_prop(&scene_ptr, "mixie_session_id", session_id, sizeof(session_id));

    char title[128];
    read_session_title(wm, session_id, title, sizeof(title));
    if (title[0] != '\0') {
      BLI_strncpy(r_state->title, title, sizeof(r_state->title));
    }
  }

  r_state->queue_count = read_queue_count(wm);

  /* Same property the account card meters — one source of truth for credits.
   * The backend owns the percentage (grandfathered allocations, trials and
   * clamping all live there); this only ever reads it. */
  r_state->credits_remaining = -1.0f;
  if (wm) {
    PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
    if (read_bool_prop(&wm_ptr, "mixar_usage_ready")) {
      PropertyRNA *pct = RNA_struct_find_property(&wm_ptr, "mixar_usage_remaining_pct");
      if (pct && RNA_property_type(pct) == PROP_FLOAT) {
        r_state->credits_remaining =
            std::clamp(RNA_property_float_get(&wm_ptr, pct) / 100.0f, 0.0f, 1.0f);
      }
    }
  }
}

}  // namespace blender
