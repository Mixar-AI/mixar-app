/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Parallel task mirror: bounded RNA reads, task identity and lifecycle clocks.
 * Geometry and region registration live in view3d_agent_panel_cards.cc.
 */

#include "MEM_guardedalloc.h"

#include "BLI_map.hh"
#include "BLI_set.hh"
#include "BLI_string.h"
#include "BLI_time.h"

#include "BKE_context.hh"

#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "view3d_agent_panel.hh"
#include <algorithm>

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name RNA Mirror Access
 * \{ */

/** Safely read an RNA string into a fixed buffer: `RNA_property_string_get` is
 * unbounded, and `StringProperty(maxlen=N)` stores up to N characters plus the
 * NUL — one past a `char[N]`. Same helper shape as `mixie_chat_slots.cc`. */
static void agent_panel_read_string(PointerRNA *ptr,
                                    PropertyRNA *prop,
                                    char *dst,
                                    const size_t dstsize)
{
  dst[0] = '\0';
  if (!prop) {
    return;
  }
  char *buf = RNA_property_string_get_alloc(ptr, prop, dst, int(dstsize), nullptr);
  if (buf != dst) {
    BLI_strncpy(dst, buf, dstsize);
    /* 5.2: MEM_freeN is gone for void*; same port as mixie_chat_slots.cc. */
    MEM_delete_void(static_cast<void *>(buf));
  }
}

int view3d_agent_panel_card_count(const bContext *C)
{
  /* Graceful degradation, like the chat footer: an unregistered Python
   * property means no panel, never an assert. This runs on every event-loop
   * cycle through the region poll — one property read, no collection walk. */
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return 0;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixar_agent_cards_active");
  return prop ? RNA_property_int_get(&wm_ptr, prop) : 0;
}

void view3d_agent_panel_cards_sync(const bContext *C, AgentPanelRuntime *runtime)
{
  /* Clocks of the cards we already know, so a card that survives a sync keeps
   * counting from when it was first seen running rather than restarting. */
  blender::Map<std::string, double> seen_running;
  blender::Map<std::string, double> seen_exit;
  blender::Map<std::string, AgentPanelCard> previous_cards;
  blender::Set<std::string> expanded;
  for (const AgentPanelCard &card : runtime->cards) {
    previous_cards.add_overwrite(std::string(card.task_id), card);
    if (card.expanded) {
      expanded.add(std::string(card.task_id));
    }
    if (card.seen_running_at != 0.0) {
      seen_running.add_overwrite(std::string(card.task_id), card.seen_running_at);
    }
    if (card.seen_exit_at != 0.0) {
      seen_exit.add_overwrite(std::string(card.task_id), card.seen_exit_at);
    }
  }

  runtime->cards.clear();

  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *cards_prop = RNA_struct_find_property(&wm_ptr, "mixar_agent_cards");
  if (cards_prop == nullptr) {
    return;
  }

  const double now = BLI_time_now_seconds();
  int generation = runtime->generation;
  if (PropertyRNA *gen_prop = RNA_struct_find_property(&wm_ptr, "mixar_agent_cards_generation")) {
    generation = RNA_property_int_get(&wm_ptr, gen_prop);
  }
  if (generation != runtime->generation) {
    runtime->cat_identities.clear();
    previous_cards.clear();
  }

  int arrivals = 0;
  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&wm_ptr, cards_prop, &iter);
  while (iter.valid) {
    PointerRNA card_ptr = iter.ptr;
    AgentPanelCard card;

    agent_panel_read_string(&card_ptr,
                            RNA_struct_find_property(&card_ptr, "task_id"),
                            card.task_id,
                            sizeof(card.task_id));
    agent_panel_read_string(
        &card_ptr, RNA_struct_find_property(&card_ptr, "name"), card.name, sizeof(card.name));
    agent_panel_read_string(
        &card_ptr, RNA_struct_find_property(&card_ptr, "task"), card.task, sizeof(card.task));

    if (PropertyRNA *status_prop = RNA_struct_find_property(&card_ptr, "status")) {
      const int status = RNA_property_enum_get(&card_ptr, status_prop);
      card.status = (status >= int(AgentCardStatus::Pending) &&
                     status <= int(AgentCardStatus::Failed)) ?
                        AgentCardStatus(status) :
                        AgentCardStatus::Pending;
    }
    if (PropertyRNA *prop = RNA_struct_find_property(&card_ptr, "started_at")) {
      card.started_at = RNA_property_float_get(&card_ptr, prop);
    }
    if (PropertyRNA *prop = RNA_struct_find_property(&card_ptr, "ended_at")) {
      card.ended_at = RNA_property_float_get(&card_ptr, prop);
    }

    if (card.status == AgentCardStatus::Running) {
      card.seen_running_at = seen_running.lookup_default(std::string(card.task_id), now);
    }
    if (PropertyRNA *prop = RNA_struct_find_property(&card_ptr, "dismissing")) {
      card.dismissing = RNA_property_boolean_get(&card_ptr, prop);
    }
    if (card.dismissing || card.status == AgentCardStatus::Done) {
      card.seen_exit_at = seen_exit.lookup_default(std::string(card.task_id), now);
    }
    card.expanded = expanded.contains(std::string(card.task_id));
    card.cat_ordinal = runtime->cat_identities.lookup_or_add(std::string(card.task_id),
                                                             int(runtime->cat_identities.size()));

    if (const AgentPanelCard *previous = previous_cards.lookup_ptr(std::string(card.task_id))) {
      card.reveal_started_at = previous->reveal_started_at;
      card.slide = previous->slide;
      card.row = previous->row;
    }
    else {
      /* Late arrivals animate individually; offscreen tasks never extend the visible stagger. */
      card.reveal_started_at = now + std::min(arrivals++, AGENT_PANEL_VISIBLE_CARDS - 1) *
                                         AGENT_PANEL_STAGGER_SECONDS;
      card.slide.settle(1.0f);
      card.row.settle(float(runtime->cards.size()));
    }

    runtime->cards.append(card);
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);

  /* A NEW fan-out replays the slide-in and starts unscrolled; a card added
   * to (or a status flip inside) the fan-out already on screen must not
   * shove the whole column off-screen and back. Python owns that
   * distinction — see `AgentPanelRuntime::generation`. */
  if (generation != runtime->generation) {
    runtime->generation = generation;
    if (!runtime->cards.is_empty()) {
      runtime->scroll = 0.0f;
    }
  }
}

/** \} */

}  // namespace blender
