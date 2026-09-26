/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup spoutliner
 */

#include "DNA_space_types.h"

#include "BLI_listbase_wrapper.hh"
#include "BLI_mempool.h"

#include "BKE_main.hh"

#include "RNA_access.hh"

#include "../outliner_intern.hh"
#include "common.hh"
#include "tree_display.hh"

namespace blender::ed::outliner {

template<typename T> using List = ListBaseWrapper<T>;

/* Mixar: an agent worker's private lane scene (`mixie_session_id` starting
 * with "agentlane:") is build scaffolding, merged into its tab's scene and
 * removed when the worker reports. The Scenes drawer never lists them; the
 * Outliner's Scenes view hides them too, so a user browsing scenes sees only
 * their own tabs (parallel scene tabs). */
static bool mixar_scene_is_agent_lane(Scene *scene)
{
  PointerRNA ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = RNA_struct_find_property(&ptr, "mixie_session_id");
  if (prop == nullptr) {
    return false;
  }
  const std::string session = RNA_property_string_get(&ptr, prop);
  return session.rfind("agentlane:", 0) == 0;
}

TreeDisplayScenes::TreeDisplayScenes(SpaceOutliner &space_outliner)
    : AbstractTreeDisplay(space_outliner)
{
}

bool TreeDisplayScenes::supports_mode_column() const
{
  return true;
}

ListBaseT<TreeElement> TreeDisplayScenes::build_tree(const TreeSourceData &source_data)
{
  /* On first view we open scenes. */
  const int show_opened = !space_outliner_.treestore ||
                          !BLI_mempool_len(space_outliner_.treestore);
  ListBaseT<TreeElement> tree = {nullptr};

  for (ID *id : List<ID>(source_data.bmain->scenes)) {
    Scene *scene = reinterpret_cast<Scene *>(id);
    if (mixar_scene_is_agent_lane(scene)) {
      continue;
    }
    TreeElement *te = add_element(&tree, id, nullptr, nullptr, TSE_SOME_ID, 0);
    TreeStoreElem *tselem = TREESTORE(te);

    /* New scene elements open by default */
    if ((scene == source_data.scene && show_opened) || !tselem->used) {
      tselem->flag &= ~TSE_CLOSED;
    }

    outliner_make_object_parent_hierarchy(&te->subtree);
  }

  return tree;
}

}  // namespace blender::ed::outliner
