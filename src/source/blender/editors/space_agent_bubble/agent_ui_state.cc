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
 *   status text   scene.mixie_chat_state   (the enum item's own UI name),
 *                 overridden to "Working" while IDLE with
 *                 scene.mixie_run_open (an open run's workers still building)
 *   status dot    scene.mixie_chat_is_busy, or that same open run
 *   title         the wm.mixie_chat_history_entries row whose session_id
 *                 matches scene.mixie_session_id; empty when none matches
 *                 (no invented "New Chat" fallback)
 *   segmented     scene.mixie_chat_mode == 'AGENT'
 *   auto switch   scene.mixie_chat_auto_mode
 *   model chip    wm.mixar_agent_model_label / wm.mixar_agent_model_byok_active
 *                 (absent until the Python half registers them)
 *   placeholder   shown while scene.mixie_chat_input is empty
 *   queue count   live rows in wm.mixie_queue.items
 *   cat catch     ED_moodboard_attachment_incoming (the live flight clock)
 *
 * Called from the draw callback, so it only ever READS: a draw callback runs
 * on every mouse move, and writing a property from one is how the chat's
 * redraw loops started.
 */

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_string.h"
#include "BLI_string_utf8.h"

#include "BKE_context.hh"

#include "DNA_scene_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "WM_api.hh"

#include "ED_moodboard_attachment.hh"

#include "agent_ui_draw.hh"
#include "agent_ui_cat_activity.hh"
#include "agent_ui_layout.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

void read_string_prop(PointerRNA *ptr, const char *name, char *out, const int out_maxncpy,
                      const bool tail = false)
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
    const char *start = value;
    if (tail && len >= out_maxncpy) {
      start += len - out_maxncpy + 1;
      while ((*start & 0xc0) == 0x80) {
        start++;
      }
    }
    BLI_strncpy_utf8(out, start, out_maxncpy);
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

  Scene *scene = CTX_data_scene(C);
  wmWindowManager *wm = CTX_wm_manager(C);
  MixieCatSignals cat;
  r_state->cat_scene = scene;

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
        {"IMAGE", AGENT_TAB_IMAGE},
        {"VIDEO", AGENT_TAB_VIDEO},
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
    r_state->status_busy = read_bool_prop(&scene_ptr, "mixie_chat_is_busy") ||
                           enum_is(&scene_ptr, "mixie_chat_state", "BUSY") ||
                           enum_is(&scene_ptr, "mixie_chat_state", "MODIFYING");
    /* The orchestrator ended its turn but the run is open: workers keep
     * building and the backend starts the next turn itself. The state enum
     * stays IDLE throughout, so its own UI name would read "Idle" while work
     * is going on. Same label and same lit dot as the Python header's
     * equivalent branch (agent_bubble/ui/header.py:_get_status). NOT
     * status_busy: the composer stays free while the cat still reflects
     * the workers' activity. A scene
     * without the property (file saved before the chat registered it) reads
     * false and keeps today's label. */
    r_state->status_active = enum_is(&scene_ptr, "mixie_chat_state", "IDLE") &&
                             read_bool_prop(&scene_ptr, "mixie_run_open");
    if (r_state->status_active) {
      BLI_strncpy(
          r_state->status_text, "Working", sizeof(r_state->status_text));
    }
    r_state->agent_mode = enum_is(&scene_ptr, "mixie_chat_mode", "AGENT");
    /* A scene saved before the chat registered the property reads false —
     * the same default the send path uses (core/composer_send.py). */
    r_state->auto_mode = read_bool_prop(&scene_ptr, "mixie_chat_auto_mode");
    cat.busy = r_state->status_busy;
    cat.waiting = enum_is(&scene_ptr, "mixie_chat_state", "AWAITING_INPUT") ||
                  enum_is(&scene_ptr, "mixie_chat_state", "MODIFYING");
    cat.offline = enum_is(&scene_ptr, "mixie_chat_state", "OFFLINE");
    cat.connecting = enum_is(&scene_ptr, "mixie_chat_state", "CONNECTING");

    read_string_prop(&scene_ptr, "mixie_chat_input", r_state->input_text, sizeof(r_state->input_text));
    r_state->prompt_empty = (r_state->input_text[0] == '\0');
    r_state->stop_visible = r_state->status_busy && r_state->prompt_empty;

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
          if (!cat.busy) {
            continue;
          }
          /* Only live activity after the most recent user prompt. Old steps
           * and completed reasoning must not animate a later idle turn. */
          cat.thinking |= read_bool_prop(&item, "thinking_active");
          PropertyRNA *content = RNA_struct_find_property(&item, "content");
          cat.responding |= content && RNA_property_string_length(&item, content) > 0;
          PropertyRNA *steps = RNA_struct_find_property(&item, "step_items");
          if (steps) {
            CollectionPropertyIterator step;
            RNA_property_collection_begin(&item, steps, &step);
            for (; step.valid; RNA_property_collection_next(&step)) {
              if (enum_is(&step.ptr, "status", "RUNNING")) {
                const bool reading = enum_is(&step.ptr, "kind", "READ") ||
                                     enum_is(&step.ptr, "kind", "SEARCH");
                cat.reading |= reading;
                cat.working |= !reading;
              }
            }
            RNA_property_collection_end(&step);
          }
          continue;
        }
        cat.thinking = cat.reading = cat.working = cat.responding = false;
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
  cat.generating = r_state->queue_count > 0;

  /* Scribble — read-only off the Python-registered properties, exactly what
   * the chat/bubble headers read (space_mixie_chat/ui/header.py). The chip is
   * not drawn at all until the toggle operator exists: a chip over a missing
   * operator would be inert for the deferred UI pass and read as broken. */
  r_state->scribble_available = WM_operatortype_find("MIXAR_OT_scribble_toggle", true) !=
                                nullptr;
  r_state->handwriting_available = WM_operatortype_find("MIXIE_CHAT_OT_ink_toggle", true) != nullptr;
  if (wm) {
    PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
    r_state->ink_visible = read_bool_prop(&wm_ptr, "mixie_chat_ink_visible");
    r_state->scribble_armed = read_bool_prop(&wm_ptr, "mixar_mark_armed");
    read_enum_name(&wm_ptr, "mixar_mark_intent", r_state->mark_intent,
                   sizeof(r_state->mark_intent));
  }

  /* Voice — the toggle registers only where the platform has a recogniser. */
  r_state->voice_available = WM_operatortype_find("MIXIE_CHAT_OT_voice_toggle", true) != nullptr;
  if (wm) {
    PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
    r_state->voice_listening = read_bool_prop(&wm_ptr, "mixie_chat_voice_listening");
    read_string_prop(&wm_ptr, "mixie_chat_voice_status", r_state->voice_status, sizeof(r_state->voice_status));
    /* "Listening" is core/voice.py's recording state (pinned by
     * tests/test_voice_stop_control.py); only then is the click a Stop. */
    r_state->voice_capturing = r_state->voice_listening &&
                               STREQ(r_state->voice_status, "Listening");
    PropertyRNA *level = RNA_struct_find_property(&wm_ptr, "mixie_chat_voice_level");
    r_state->voice_level = (r_state->voice_capturing && level &&
                            RNA_property_type(level) == PROP_FLOAT) ?
                               std::clamp(RNA_property_float_get(&wm_ptr, level), 0.0f, 1.0f) :
                               0.0f;
  }
  /* Hosted model pick — the WindowManager mirror the Python half writes
   * (byok preference state). A build whose Python half has not landed, or
   * an old .blend opened before the properties registered, reads as "no
   * picker": the chip is left out entirely instead of popping a menu that
   * is not registered. */
  r_state->model_available = false;
  r_state->model_byok_active = false;
  r_state->model_label[0] = '\0';
  if (wm) {
    PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
    PropertyRNA *label = RNA_struct_find_property(&wm_ptr, "mixar_agent_model_label");
    if (label && RNA_property_type(label) == PROP_STRING) {
      r_state->model_available = true;
      read_string_prop(
          &wm_ptr, "mixar_agent_model_label", r_state->model_label, sizeof(r_state->model_label));
      r_state->model_byok_active = read_bool_prop(&wm_ptr, "mixar_agent_model_byok_active");
    }
  }

  cat.listening = r_state->voice_listening;
  if (scene) {
    PointerRNA ptr = RNA_id_pointer_create(&scene->id);
    char activity[32], until[64];
    read_string_prop(&ptr, "mixie_chat_cat_activity", activity, sizeof(activity));
    read_string_prop(&ptr, "mixie_chat_cat_activity_until", until, sizeof(until));
    /* Python tool execution can start AND finish before the next draw. The
     * producer keeps a 900ms presentation pulse without changing job status.
     * String RNA preserves subsecond precision; native float RNA does not at
     * Unix timestamps. Bound both ends so clock corrections cannot stick it. */
    const double now = std::chrono::duration<double>(
                           std::chrono::system_clock::now().time_since_epoch()).count();
    const double remaining = std::strtod(until, nullptr) - now;
    if (remaining > 0.0 && remaining <= 0.91) {
      if (cat.busy) {
        cat.reading |= STREQ(activity, "READING");
        cat.working |= STREQ(activity, "WORKING");
        if (STREQ(activity, "RESPONDING")) {
          cat.thinking = cat.reading = cat.working = false;
          cat.responding = true;
        }
      }
      cat.finishing = STREQ(activity, "RESPONDING");
    }
  }
  if (wmWindow *win = CTX_wm_window(C)) {
    MixieAttachmentIncoming incoming;
    if (ED_moodboard_attachment_incoming(win, incoming)) {
      cat.catching = true;
      const float native_w = float(WM_window_native_pixel_x(win));
      const float native_h = float(WM_window_native_pixel_y(win));
      const float scale = native_w / float(std::max(1, int(win->sizex)));
      float chip_x = 0.0f, chip_y = 0.0f;
      mixie_cat_pill_chip_center(native_w, native_h, chip_x, chip_y);
      r_state->cat_catch = mixie_cat_catch_aim(incoming.progress,
                                              incoming.position[0],
                                              incoming.position[1],
                                              float(win->posx) + chip_x / scale,
                                              float(win->posy) + chip_y / scale);
    }
  }
  /* Delegated workers outlive the orchestrator turn. Apply this after reading
   * transcript signals so old reasoning cannot animate an otherwise idle run. */
  cat.busy |= r_state->status_active;
  cat.working |= r_state->status_active;
  r_state->cat_activity = mixie_cat_activity(cat);
  if (scene) {
    /* DRAFT marks only: SENT marks stay in the scene for follow-up turns but
     * no longer ride with the next message, so they are not counted. */
    PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
    PropertyRNA *marks = RNA_struct_find_property(&scene_ptr, "mixar_marks");
    if (marks && RNA_property_type(marks) == PROP_COLLECTION) {
      CollectionPropertyIterator iter;
      RNA_property_collection_begin(&scene_ptr, marks, &iter);
      for (; iter.valid; RNA_property_collection_next(&iter)) {
        PointerRNA item = iter.ptr;
        char mark_state[16];
        read_string_prop(&item, "state", mark_state, sizeof(mark_state));
        if (STREQ(mark_state, "DRAFT")) {
          r_state->mark_count++;
        }
      }
      RNA_property_collection_end(&iter);
    }
  }

  if (r_state->scribble_armed) {
    r_state->placeholder = "Draw or type instructions. Enter to send.";
    if (scene) {
      PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
      read_string_prop(&scene_ptr, "mixie_chat_input", r_state->sketch_prompt,
                       sizeof(r_state->sketch_prompt), true);
    }
  }
  else if (r_state->mark_count > 0) {
    r_state->placeholder = "Sketch ready. Add instructions, then Send.";
  }

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
