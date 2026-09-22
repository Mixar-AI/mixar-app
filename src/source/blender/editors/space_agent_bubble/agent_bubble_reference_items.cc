/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "agent_bubble_references.hh"
#include "DNA_image_types.h"
#include "DNA_scene_types.h"
#include "DNA_windowmanager_types.h"
#include "RNA_access.hh"

namespace blender {
namespace {
PointerRNA pointer(PointerRNA owner, const char *name)
{
  PropertyRNA *prop = owner.data ? RNA_struct_find_property(&owner, name) : nullptr;
  return prop ? RNA_property_pointer_get(&owner, prop) : PointerRNA{};
}

bool enabled(PointerRNA owner, const char *name)
{
  PropertyRNA *prop = owner.data ? RNA_struct_find_property(&owner, name) : nullptr;
  return prop && RNA_property_boolean_get(&owner, prop);
}

std::string enum_id(PointerRNA owner, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(&owner, name);
  const char *id = nullptr;
  if (prop) {
    RNA_property_enum_identifier(nullptr, &owner, prop, RNA_property_enum_get(&owner, prop), &id);
  }
  return id ? id : "";
}

void append_image(std::vector<AgentReference> &items,
                  PointerRNA image,
                  const char *source,
                  const bool allow_video = false)
{
  const Image *ima = static_cast<Image *>(image.data);
  if (ima && (allow_video || ima->source != IMA_SRC_MOVIE) && ima->source != IMA_SRC_SEQUENCE) {
    items.push_back({ima->id.name + 2, ima->id.name + 2, source});
  }
}
}  // namespace

std::vector<AgentReference> agent_bubble_reference_items(Scene *scene, wmWindowManager *wm)
{
  std::vector<AgentReference> items;
  if (!scene || !wm) {
    return items;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  const std::string active = enum_id(wm_ptr, "mixar_bubble_tab");
  if (active == "AGENT") {
    if (RNA_struct_find_property(&scene_ptr, "mixie_chat_pending_attachments")) {
      RNA_BEGIN (&scene_ptr, item, "mixie_chat_pending_attachments") {
        items.push_back({RNA_string_get(&item, "image_path"),
                         RNA_string_get(&item, "display_name"),
                         enum_id(item, "image_source"),
                         RNA_struct_find_property(&item, "scribble_view") &&
                             !RNA_string_get(&item, "scribble_view").empty()});
      }
      RNA_END;
    }
    return items;
  }

  const bool model = active == "THREE_D";
  const bool video = active == "VIDEO";
  const bool media = active == "IMAGE" || video;
  const bool splat = active == "SPLAT";
  if (!model && !media && !splat) {
    return items;
  }
  PointerRNA sidebar = pointer(scene_ptr, "mixie_moodboard_sidebar");
  PointerRNA tab = pointer(sidebar, model ? "tab_image_to_3d" :
                                    splat ? "tab_world_labs" :
                                    video ? "tab_video_gen" : "tab_imagegen");
  if (!tab.data) {
    return items;
  }
  const bool board = video || enabled(tab, media ? "use_reference_images" : "use_selected_image");
  if (board) {
    RNA_BEGIN (&scene_ptr, item, "mixie_moodboard_images") {
      if (enabled(item, "selected")) {
        append_image(items, pointer(item, "image"), "BOARD", video);
      }
    }
    RNA_END;
  }
  else if (media) {
    RNA_BEGIN (&tab, item, "reference_images") {
      append_image(items, pointer(item, "image"), "MEDIA_UPLOAD");
    }
    RNA_END;
  }
  else {
    append_image(items, pointer(tab, "reference_image"), model ? "MODEL_UPLOAD" : "SPLAT_UPLOAD");
  }
  return items;
}
}  // namespace blender
