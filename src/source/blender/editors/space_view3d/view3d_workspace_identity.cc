/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */
#include "BLI_listbase.h"
#include "BKE_idprop.hh"
#include "BKE_main.hh"
#include "DNA_scene_types.h"
#include "RNA_access.hh"
#include "view3d_workspace_viewer.hh"
namespace blender {
std::string view3d_workspace_rna_string(Scene *scene, const char *key)
{
  if (!scene) { return {}; }
  PointerRNA ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = RNA_struct_find_property(&ptr, key);
  return prop ? RNA_property_string_get(&ptr, prop) : std::string();
}
static std::string tag(Scene *scene, const char *key)
{
  IDProperty *prop = IDP_GetPropertyFromGroup_null(scene->id.properties, key);
  return prop && prop->type == IDP_STRING ? IDP_string_get(prop) : "";
}
Scene *view3d_workspace_scene(Main *bmain, Scene *main, const std::string &task_id)
{
  if (!main || task_id.empty()) { return nullptr; }
  const std::string session = view3d_workspace_rna_string(main, "mixie_session_id");
  const std::string run = view3d_workspace_rna_string(main, "mixie_run_id");
  if (session.empty() || run.empty()) { return nullptr; }
  Scene *found = nullptr;
  for (Scene &item : bmain->scenes) {
    Scene *scene = &item;
    const std::string token = tag(scene, "mixar_workspace_token");
    if (scene != main && !token.empty() &&
        tag(scene, "mixar_workspace_task") == task_id &&
        tag(scene, "mixar_workspace_run") == run &&
        tag(scene, "mixar_workspace_main_session") == session &&
        view3d_workspace_rna_string(scene, "mixie_session_id") == "agentlane:" + token)
    {
      if (found) { return nullptr; } // Ambiguous identity must never preview an arbitrary scene.
      found = scene;
    }
  }
  return found;
}
}  // namespace blender
