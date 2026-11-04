/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup bke
 *
 * Mixar per-tab undo: the owner map. Which tab reaches each datablock (walked
 * from every scene, then from the roots no scene reaches), which are shared,
 * and the per-tab view of the shared ones (``BKE_undo_tabs.hh``).
 */
#include <cstdlib>
#include <cstring>
#include <string>

#include "CLG_log.h"

#include "BLI_listbase.h"
#include "BLI_utildefines.h"
#include "BLI_map.hh"
#include "BLI_set.hh"
#include "BLI_string.h"
#include "BLI_time.h"
#include "BLI_assert.h"
#include "BLI_vector.hh"

#include "DNA_ID.h"
#include "DNA_scene_types.h"
#include "DNA_windowmanager_types.h"

#include "BKE_context.hh"
#include "BKE_global.hh"
#include "BKE_idprop.hh"
#include "BKE_idtype.hh"
#include "BKE_lib_query.hh"
#include "BKE_main.hh"
#include "BKE_undo_system.hh"
#include "BKE_undo_tabs.hh"
#include "BKE_wm_runtime.hh"

#include "MEM_guardedalloc.h"
#include "undo_tabs_intern.hh"

namespace blender {

static CLG_LogRef LOG = {"undo.tabs"};

/* -------------------------------------------------------------------- */
/** \name Owner map
 * \{ */


/** A type memfile undo never writes (a Brush, a WorkSpace, a Screen) is never
 * restored, so it can neither be owned nor shared: every scene's tool settings
 * point at the active brush, and counting it would refuse undo in every tab
 * once two tabs paint with the same brush. */
static bool owner_map_type_is_never_undone(const ID *id)
{
  const IDTypeInfo *info = BKE_idtype_get_info_from_id(id);
  return info != nullptr && (info->flags & IDTYPE_FLAGS_NO_MEMFILE_UNDO);
}

/** Calls ``visit`` for every datablock ``root`` reaches through FORWARD pointers.
 * IDWALK_RECURSE also follows back-pointers (a collection's runtime parents, an
 * embedded datablock's owner): a tab sharing a child collection with another tab
 * (Scene > New > Linked Copy) climbed through that collection's parents into the
 * other tab's master collection and its scene, and "reached" all of that tab.
 * Every step that changed what either reached then saw two tabs gain or lose it
 * and was filed under neither (the invariant test, seed 8097), and the two tabs'
 * datablocks read as shared. Embedded datablocks are walked in place by their
 * owner. A type memfile undo never writes is visited, never walked through: a
 * local brush's texture and image are reached from every scene whose tool
 * settings use that brush, and walked through they became "shared" and refused
 * undo in every tab painting with it (review 2026-10-01, R4); what they point at
 * is owned by whoever reaches it directly, else global. */
static void owner_map_walk(Main *bmain, ID *root, FunctionRef<void(const ID *)> visit)
{
  Set<const ID *> seen;
  Vector<ID *> todo;
  seen.add(root);
  todo.append(root);
  while (!todo.is_empty()) {
    ID *id = todo.pop_last();
    BKE_library_foreach_ID_link(
        bmain,
        id,
        [&](LibraryIDLinkCallbackData *cb_data) -> int {
          if (cb_data->cb_flag & IDWALK_CB_LOOPBACK) {
            return IDWALK_RET_NOP;
          }
          ID *ref = *cb_data->id_pointer;
          if (ref == nullptr) {
            return IDWALK_RET_NOP;
          }
          visit(ref);
          if ((ref->flag & ID_FLAG_EMBEDDED_DATA) == 0 && !owner_map_type_is_never_undone(ref) &&
              seen.add(ref))
          {
            todo.append(ref);
          }
          return IDWALK_RET_NOP;
        },
        nullptr,
        IDWALK_READONLY);
  }
}

static void owner_map_record(UndoOwnerMap *map, const ID *id, const uint32_t tab)
{
  if (id == nullptr || id->session_uid == 0) {
    return;
  }
  /* An embedded datablock (a material's or world's node tree, a scene's master
   * collection) is written and read with its owner and is in no Main list: the
   * owner's entry decides it. Recorded on its own it read as "gone" to every
   * restore that shared its owner (the invariant test, 2026-10-02: Linked Copy
   * shares the world, and every undo was refused for its "Shader Nodetree"). */
  if (id->flag & ID_FLAG_EMBEDDED_DATA) {
    return;
  }
  if (owner_map_type_is_never_undone(id)) {
    return;
  }
  uint32_t *slot = map->owner.lookup_ptr(id->session_uid);
  if (slot == nullptr) {
    map->owner.add_new(id->session_uid, tab);
    return;
  }
  if (*slot == tab) {
    return;
  }
  if (*slot == UNDO_TAB_SHARED) {
    Vector<uint32_t> &tabs = map->shared_by.lookup(id->session_uid);
    if (!tabs.contains(tab)) {
      tabs.append(tab);
    }
    return;
  }
  Vector<uint32_t> tabs;
  tabs.append(*slot);
  tabs.append(tab);
  map->shared_by.add_new(id->session_uid, std::move(tabs));
  *slot = UNDO_TAB_SHARED;
  /* A datablock linked from a library is never edited locally: a partial
   * restore keeps it as it is (the SHARED owner) and no tab is refused for it. */
  if (ID_IS_LINKED(id)) {
    return;
  }
  map->shared += 1;
  map->shared_name.add_new(id->session_uid, std::string(id->name + 2));
  map->shared_type.add_new(id->session_uid, GS(id->name));
  if (map->shared_names.size() < 32) {
    map->shared_names.append(std::string(id->name));
  }
}

/** The local shared datablocks the tab itself reaches: the ones a restore of
 * this tab would change under another tab. A datablock two OTHER tabs share
 * is none of this tab's business. Returns the count; names up to eight. */
int undo_tabs_owner_map_shared_for_tab(const UndoOwnerMap *map, const uint32_t tab, std::string *r_names)
{
  int count = 0;
  if (map == nullptr) {
    return 0;
  }
  for (const auto item : map->shared_name.items()) {
    const Vector<uint32_t> *tabs = map->shared_by.lookup_ptr(item.key);
    if (tabs == nullptr || !tabs->contains(tab)) {
      continue;
    }
    if (r_names != nullptr && count < 8) {
      *r_names += (r_names->empty() ? "" : ", ") + item.value;
    }
    count++;
  }
  return count;
}

/** A lane reaches it: the lane's own when no tab does, the tab's otherwise.
 * Never makes anything shared (a lane works on its tab's behalf). */
static void owner_map_record_lane(UndoOwnerMap *map, const ID *id)
{
  if (id == nullptr || id->session_uid == 0 || owner_map_type_is_never_undone(id) ||
      (id->flag & ID_FLAG_EMBEDDED_DATA))
  {
    return;
  }
  map->owner.add(id->session_uid, UNDO_TAB_LANE);
}

struct RootWalk {
  UndoOwnerMap *map;
  Vector<const ID *> unowned;
  Vector<uint32_t> tabs;
};

static void root_walk_note(RootWalk *w, const ID *id)
{
  const uint32_t owner = BKE_undo_owner_map_lookup(w->map, id->session_uid);
  if (owner == UNDO_TAB_SHARED) {
    if (const Vector<uint32_t> *tabs = w->map->shared_by.lookup_ptr(id->session_uid)) {
      for (const uint32_t tab : *tabs) {
        if (!w->tabs.contains(tab)) {
          w->tabs.append(tab);
        }
      }
    }
  }
  else if (owner == UNDO_TAB_LANE) {
    /* A lane's datablock claims nothing for the root: the root stays global
     * (kept as it is by every tab's walk, as the lane's datablocks are). */
  }
  else if (owner != UNDO_TAB_DOCUMENT) {
    if (!w->tabs.contains(owner)) {
      w->tabs.append(owner);
    }
  }
  else if (!w->unowned.contains(id)) {
    w->unowned.append(id);
  }
}

/** Roots outside every scene (review of #1746): an ID no scene reaches but
 * that points into ONE tab (an orphan collection holding the tab's objects, a
 * fake-user node group on the tab's image) belongs to that tab, so a partial
 * restore keeps it consistent with what it points at: kept as a global it
 * would keep a live pointer to a tab datablock the walk frees. One pointing
 * into two tabs is shared, and refuses their restores. What reaches no tab
 * stays global. */
static void owner_map_claim_roots(Main *bmain, UndoOwnerMap *map)
{
  ID *id = nullptr;
  FOREACH_MAIN_ID_BEGIN (bmain, id) {
    if (id->session_uid == 0 || map->owner.contains(id->session_uid)) {
      continue;
    }
    if (ELEM(GS(id->name), ID_SCE, ID_LI) || ID_IS_LINKED(id)) {
      continue; /* an unresolved lane, a library, library data */
    }
    const IDTypeInfo *info = BKE_idtype_get_info_from_id(id);
    if (info != nullptr && (info->flags & IDTYPE_FLAGS_NO_MEMFILE_UNDO)) {
      continue;
    }
    RootWalk walk{map};
    walk.unowned.append(id);
    owner_map_walk(bmain, id, [&](const ID *ref) {
      if (ref->session_uid != 0) {
        root_walk_note(&walk, ref);
      }
    });
    if (walk.tabs.is_empty()) {
      continue; /* global: reaches no tab */
    }
    /* One tab: the root and what it reaches are that tab's. Several: one
     * record per tab marks them shared with every one of those tabs. */
    for (const ID *found : walk.unowned) {
      for (const uint32_t tab : walk.tabs) {
        owner_map_record(map, found, tab);
      }
    }
  }
  FOREACH_MAIN_ID_END;
}

UndoOwnerMap *BKE_undo_owner_map_build(Main *bmain, double *r_ms)
{
  const double t0 = BLI_time_now_seconds();
  UndoOwnerMap *map = MEM_new<UndoOwnerMap>(__func__);
  if (bmain != nullptr) {
    /* The tabs first, then the lanes: a datablock a tab reaches is the tab's
     * whatever a lane does with it; what only a lane reaches is the lane's. */
    for (Scene &scene : bmain->scenes) {
      if (BKE_undo_tab_scene_is_lane(&scene)) {
        continue;
      }
      const uint32_t tab = BKE_undo_tab_uid_for_scene(bmain, &scene);
      if (tab == UNDO_TAB_DOCUMENT) {
        continue;
      }
      owner_map_record(map, &scene.id, tab);
      owner_map_walk(bmain, &scene.id, [&](const ID *id) { owner_map_record(map, id, tab); });
    }
    for (Scene &scene : bmain->scenes) {
      if (!BKE_undo_tab_scene_is_lane(&scene)) {
        continue;
      }
      owner_map_record_lane(map, &scene.id);
      owner_map_walk(bmain, &scene.id, [&](const ID *id) { owner_map_record_lane(map, id); });
    }
    owner_map_claim_roots(bmain, map);
  }
  map->build_ms = (BLI_time_now_seconds() - t0) * 1000.0;
  if (r_ms != nullptr) {
    *r_ms = map->build_ms;
  }
  CLOG_DEBUG(&LOG,
             "owner map: %d ids, %d shared, %.2f ms",
             int(map->owner.size()),
             map->shared,
             map->build_ms);
  return map;
}

void BKE_undo_owner_map_free(UndoOwnerMap *map)
{
  if (map != nullptr) {
    MEM_delete(map);
  }
}

uint32_t BKE_undo_owner_map_lookup(const UndoOwnerMap *map, const uint32_t session_uid)
{
  if (map == nullptr) {
    return UNDO_TAB_DOCUMENT;
  }
  return map->owner.lookup_default(session_uid, UNDO_TAB_DOCUMENT);
}

int BKE_undo_owner_map_size(const UndoOwnerMap *map)
{
  return map != nullptr ? int(map->owner.size()) : 0;
}

int BKE_undo_owner_map_shared_count(const UndoOwnerMap *map)
{
  return map != nullptr ? map->shared : 0;
}

/** \} */

}  // namespace blender
