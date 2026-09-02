/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The My Generations pane's gathering pass.
 *
 * Four sources are normalised into one #GenItem list. None of them is owned
 * here — every one is read from something another module already maintains:
 *
 *   3D assets   the registered asset libraries, through Blender's own asset
 *               list (`ED_asset_list.hh`). The "Mixar Generations" library is
 *               written by `asset_search/core/generation_library.py`; this
 *               pane never writes an asset.
 *   media       `scene.mixie_moodboard_images`, restricted to items carrying
 *               a `generation_prompt` — the marker every generated still and
 *               movie gets and a user upload does not.
 *   splats      collections in this file flagged `mixar_splat_world` by
 *               `moodboard/core/splat_lifecycle.py`.
 *   live jobs   the `wm.mixie_queue` mirror, the same rows the Queue tab
 *               lists, so a generation appears here the moment it starts.
 *
 * The guarded RNA getters and the "4d ago" arithmetic live next door in
 * `agent_ui_generations_read.cc`; this file is the four sources and the
 * filter/sort that turns them into one list.
 *
 * The pane's own state (source, filter, sort, selection, browsed library)
 * lives in WindowManager properties registered by
 * `agent_bubble/ui/properties/generations_props.py` — WindowManager because
 * a browser's filter must not be serialised into a shared .blend.
 */

#include <algorithm>
#include <cmath>
#include <cstring>
#include <ctime>
#include <string>

#include "BLI_listbase.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_idtype.hh"
#include "BKE_main.hh"

#include "DNA_ID.h"
#include "DNA_asset_types.h"
#include "DNA_collection_types.h"
#include "DNA_image_types.h"
#include "DNA_scene_types.h"
#include "DNA_userdef_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"
#include "RNA_path.hh"

#include "AS_asset_representation.hh"

#include "ED_asset_library.hh"
#include "ED_asset_list.hh"

#include "agent_ui_generations_intern.hh"

namespace {

/* -------------------------------------------------------------------- */
/** \name Sources
 * \{ */

bool item_push(GenPaneData *data, GenItem **r_item)
{
  if (data->count >= GEN_MAX_ITEMS) {
    return false;
  }
  GenItem &item = data->items[data->count++];
  item = GenItem{};
  *r_item = &item;
  return true;
}

/** Every registered library, in preferences order, for the rail's list. */
void gather_libraries(GenPaneData *data)
{
  data->lib_count = 0;
  LISTBASE_FOREACH (const bUserAssetLibrary *, lib, &U.asset_libraries) {
    if (data->lib_count >= 16) {
      break;
    }
    if (!lib->name[0]) {
      continue;
    }
    BLI_strncpy(data->lib_names[data->lib_count++], lib->name, 64);
  }
}

/** What the caption calls an asset.
 *
 * Blender's own name for #ID_OB is "Object", but every Object in the
 * generations library is a generated mesh and the design's caption reads
 * "Mesh" — so that one is renamed and everything else keeps Blender's word,
 * rather than inventing a vocabulary the user would have to learn twice. */
const char *asset_type_label(const ID_Type id_type)
{
  if (id_type == ID_OB) {
    return "Mesh";
  }
  const char *name = BKE_idtype_idcode_to_name(short(id_type));
  return name ? name : "Asset";
}

/** Read one library into the item list. \a only_name limits it to that
 * library; null takes every registered one.
 *
 * \a reload drops the cached read first. Blender's asset list reads a library
 * ONCE and never notices a .blend appearing underneath it — which is exactly
 * what archiving a finished generation does — so the writer signals us
 * through `wm.mixar_generations_revision` and we clear on the edge. Doing it
 * on every draw instead would re-read the whole library on every mouse move. */
void gather_assets(const bContext *C,
                   GenPaneData *data,
                   const char *only_name,
                   const bool reload)
{
  LISTBASE_FOREACH (const bUserAssetLibrary *, lib, &U.asset_libraries) {
    if (only_name && !STREQ(lib->name, only_name)) {
      continue;
    }
    if (!lib->name[0] || !lib->dirpath[0]) {
      continue;
    }
    const AssetLibraryReference ref = blender::ed::asset::user_library_to_library_ref(*lib);
    if (reload) {
      blender::ed::asset::list::clear(&ref, C);
    }
    /* Asynchronous: the first draw kicks the read and paints "Loading…", and
     * the Python redraw pump supplies the frames until it lands. */
    blender::ed::asset::list::storage_fetch(&ref, C);
    if (!blender::ed::asset::list::is_loaded(&ref)) {
      data->loading = true;
      continue;
    }
    blender::ed::asset::list::iterate(
        ref, [&](blender::asset_system::AssetRepresentation &asset) -> bool {
          GenItem *item = nullptr;
          if (!item_push(data, &item)) {
            return false;
          }
          item->kind = GEN_ITEM_ASSET;
          item->asset = &asset;
          BLI_strncpy(item->name, asset.get_name().c_str(), sizeof(item->name));
          BLI_snprintf(item->key, sizeof(item->key), "asset:%s:%s", lib->name,
                       asset.library_relative_identifier().c_str());
          BLI_strncpy(item->type_label, asset_type_label(asset.get_id_type()),
                      sizeof(item->type_label));
          BLI_strncpy(item->model_label, lib->name, sizeof(item->model_label));
          const std::string blend = asset.full_library_path();
          BLI_strncpy(item->path, blend.c_str(), sizeof(item->path));
          /* The folder a datablock is addressed by inside a .blend — the
           * same "Object" / "Collection" segment `wm.append` wants. */
          if (const char *dir = BKE_idtype_idcode_to_name(short(asset.get_id_type()))) {
            BLI_strncpy(item->id_dir, dir, sizeof(item->id_dir));
          }
          if (const AssetMetaData &meta = asset.get_metadata(); meta.description) {
            BLI_strncpy(item->detail, meta.description, sizeof(item->detail));
          }
          item->sort_time = gen_blend_mtime(item->path);
          gen_format_age(item->sort_time, item->age);
          return true;
        });
  }
}

/** Generated stills and movies on this scene's moodboard. */
void gather_media(const bContext *C, GenPaneData *data)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *items = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
  if (!items || RNA_property_type(items) != PROP_COLLECTION) {
    return;
  }
  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&scene_ptr, items, &iter);
  for (; iter.valid; RNA_property_collection_next(&iter)) {
    PointerRNA row = iter.ptr;
    char prompt[256];
    gen_read_string(&row, "generation_prompt", prompt, sizeof(prompt));
    if (!prompt[0]) {
      /* A user upload, not a generation — the board owns it, not this tab. */
      continue;
    }
    PropertyRNA *img_prop = RNA_struct_find_property(&row, "image");
    if (!img_prop || RNA_property_type(img_prop) != PROP_POINTER) {
      continue;
    }
    PointerRNA img_ptr = RNA_property_pointer_get(&row, img_prop);
    Image *image = static_cast<Image *>(img_ptr.data);
    if (!image) {
      continue;
    }
    GenItem *item = nullptr;
    if (!item_push(data, &item)) {
      break;
    }
    item->kind = (image->source == IMA_SRC_MOVIE) ? GEN_ITEM_VIDEO : GEN_ITEM_IMAGE;
    item->image = image;
    BLI_strncpy(item->name, image->id.name + 2, sizeof(item->name));
    BLI_snprintf(item->key, sizeof(item->key), "media:%s", image->id.name + 2);
    BLI_strncpy(item->type_label,
                (item->kind == GEN_ITEM_VIDEO) ? "Video" : "Image",
                sizeof(item->type_label));
    BLI_strncpy(item->detail, prompt, sizeof(item->detail));
    BLI_strncpy(item->path, image->filepath, sizeof(item->path));
    char created[64];
    gen_read_string(&row, "mixar_created_at_iso", created, sizeof(created));
    item->sort_time = gen_epoch_from_iso(created);
    gen_format_age(item->sort_time, item->age);
  }
  RNA_property_collection_end(&iter);
}

/** Gaussian-splat worlds imported into this file. */
void gather_splats(const bContext *C, GenPaneData *data)
{
  Main *bmain = CTX_data_main(C);
  if (!bmain) {
    return;
  }
  LISTBASE_FOREACH (Collection *, collection, &bmain->collections) {
    PointerRNA ptr = RNA_id_pointer_create(&collection->id);
    /* `collection["mixar_splat_world"]` is a custom property, and the
     * bracketed identifier is RNA's explicit ID-property lookup — a bare name
     * goes through the registered-property path instead. Read through RNA
     * rather than walking IDProperties directly: the group an ID's custom
     * properties live in moved between Blender's `properties` and
     * `system_properties`. */
    PointerRNA flag_ptr;
    PropertyRNA *flag = nullptr;
    if (!RNA_path_resolve_property(&ptr, "[\"mixar_splat_world\"]", &flag_ptr, &flag) ||
        !flag)
    {
      continue;
    }
    GenItem *item = nullptr;
    if (!item_push(data, &item)) {
      break;
    }
    item->kind = GEN_ITEM_SPLAT;
    BLI_strncpy(item->name, collection->id.name + 2, sizeof(item->name));
    BLI_snprintf(item->key, sizeof(item->key), "splat:%s", collection->id.name + 2);
    BLI_strncpy(item->type_label, "Splat world", sizeof(item->type_label));
    BLI_strncpy(item->detail, "In this file", sizeof(item->detail));
  }
}

/** Jobs still in flight — the design's "GENERATING" tile. */
void gather_jobs(const bContext *C, GenPaneData *data)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *queue_prop = RNA_struct_find_property(&wm_ptr, "mixie_queue");
  if (!queue_prop || RNA_property_type(queue_prop) != PROP_POINTER) {
    return;
  }
  PointerRNA queue = RNA_property_pointer_get(&wm_ptr, queue_prop);
  PropertyRNA *items = RNA_struct_find_property(&queue, "items");
  if (!items || RNA_property_type(items) != PROP_COLLECTION) {
    return;
  }
  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&queue, items, &iter);
  for (; iter.valid; RNA_property_collection_next(&iter)) {
    PointerRNA row = iter.ptr;
    char state[32];
    gen_read_enum_id(&row, "state", state, sizeof(state));
    if (!state[0]) {
      gen_read_string(&row, "state", state, sizeof(state));
    }
    const bool live = STREQ(state, "PENDING") || STREQ(state, "PAUSED_AUTH") ||
                      STREQ(state, "RUNNING_SUBMIT") || STREQ(state, "RUNNING_POLL") ||
                      STREQ(state, "RUNNING_DOWNLOAD");
    if (!live) {
      continue;
    }
    GenItem *item = nullptr;
    if (!item_push(data, &item)) {
      break;
    }
    item->kind = GEN_ITEM_JOB;
    char job_id[64];
    char display[96];
    char label[96];
    gen_read_string(&row, "job_id", job_id, sizeof(job_id));
    gen_read_string(&row, "display_label", display, sizeof(display));
    gen_read_string(&row, "label", label, sizeof(label));
    BLI_strncpy(item->name, display[0] ? display : (label[0] ? label : "Generating"),
                sizeof(item->name));
    BLI_snprintf(item->key, sizeof(item->key), "job:%s", job_id);
    gen_read_string(&row, "type_label", item->type_label, sizeof(item->type_label));
    gen_read_string(&row, "model_label", item->model_label, sizeof(item->model_label));
    item->sort_time = double(gen_read_int(&row, "created_epoch"));
    gen_format_age(item->sort_time, item->age);
  }
  RNA_property_collection_end(&iter);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Filter + sort
 * \{ */

bool item_passes(const GenItem &item, const GenFilter filter)
{
  switch (filter) {
    case GEN_FILTER_ALL:
      return true;
    case GEN_FILTER_3D:
      /* An image saved as an asset is still an image — the chip filters on
       * the asset's real ID type, not on "is it in a library". A running job
       * is shown here too: 3D is where the overwhelming majority of them
       * land, and hiding it would make a generation vanish for as long as it
       * takes to make. */
      return (item.kind == GEN_ITEM_ASSET && !STREQ(item.id_dir, "Image")) ||
             item.kind == GEN_ITEM_JOB;
    case GEN_FILTER_IMAGE:
      return item.kind == GEN_ITEM_IMAGE ||
             (item.kind == GEN_ITEM_ASSET && STREQ(item.id_dir, "Image"));
    case GEN_FILTER_VIDEO:
      return item.kind == GEN_ITEM_VIDEO;
    case GEN_FILTER_SPLAT:
      return item.kind == GEN_ITEM_SPLAT;
    case GEN_FILTER_COUNT:
      break;
  }
  return true;
}

GenFilter filter_from_id(const char *id)
{
  if (STREQ(id, "THREE_D")) {
    return GEN_FILTER_3D;
  }
  if (STREQ(id, "IMAGE")) {
    return GEN_FILTER_IMAGE;
  }
  if (STREQ(id, "VIDEO")) {
    return GEN_FILTER_VIDEO;
  }
  if (STREQ(id, "SPLAT")) {
    return GEN_FILTER_SPLAT;
  }
  return GEN_FILTER_ALL;
}

/** \} */

}  // namespace

void agent_ui_generations_gather(const bContext *C, GenPaneData *r_data)
{
  *r_data = GenPaneData{};

  /* Edge-triggered library reload. Static because the edge is per-process:
   * the number only ever goes up, and every island window wants the same
   * one reload. */
  static int g_seen_revision = 0;
  bool reload = false;

  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm) {
    PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
    char source[32];
    char filter[32];
    char sort[32];
    gen_read_enum_id(&wm_ptr, "mixar_generations_source", source, sizeof(source));
    gen_read_enum_id(&wm_ptr, "mixar_generations_filter", filter, sizeof(filter));
    gen_read_enum_id(&wm_ptr, "mixar_generations_sort", sort, sizeof(sort));
    gen_read_string(&wm_ptr, "mixar_generations_selected", r_data->selected,
                sizeof(r_data->selected));
    gen_read_string(&wm_ptr, "mixar_generations_library", r_data->library,
                sizeof(r_data->library));
    if (PropertyRNA *page = RNA_struct_find_property(&wm_ptr, "mixar_generations_page");
        page && RNA_property_type(page) == PROP_INT)
    {
      r_data->page = std::max(0, RNA_property_int_get(&wm_ptr, page));
    }
    if (PropertyRNA *rev = RNA_struct_find_property(&wm_ptr, "mixar_generations_revision");
        rev && RNA_property_type(rev) == PROP_INT)
    {
      const int revision = RNA_property_int_get(&wm_ptr, rev);
      reload = revision != g_seen_revision;
      g_seen_revision = revision;
    }
    r_data->source = STREQ(source, "LIBRARY") ? GEN_SOURCE_LIBRARY : GEN_SOURCE_AI;
    r_data->filter = filter_from_id(filter);
    r_data->newest_first = !STREQ(sort, "OLDEST");
  }

  gather_libraries(r_data);

  if (r_data->source == GEN_SOURCE_LIBRARY) {
    gather_assets(C, r_data, r_data->library[0] ? r_data->library : nullptr, reload);
  }
  else {
    gather_jobs(C, r_data);
    gather_assets(C, r_data, GENERATIONS_LIBRARY_NAME, reload);
    gather_media(C, r_data);
    gather_splats(C, r_data);
  }

  /* Filter in place, then sort. Live jobs always lead: they are the one row
   * the user is waiting on, and a job with no created_epoch would otherwise
   * sink to the bottom of a newest-first list. */
  int kept = 0;
  for (int i = 0; i < r_data->count; i++) {
    if (item_passes(r_data->items[i], r_data->filter)) {
      if (kept != i) {
        r_data->items[kept] = r_data->items[i];
      }
      kept++;
    }
  }
  r_data->count = kept;

  const bool newest = r_data->newest_first;
  std::stable_sort(r_data->items,
                   r_data->items + r_data->count,
                   [newest](const GenItem &a, const GenItem &b) {
                     const bool a_live = a.kind == GEN_ITEM_JOB;
                     const bool b_live = b.kind == GEN_ITEM_JOB;
                     if (a_live != b_live) {
                       return a_live;
                     }
                     return newest ? (a.sort_time > b.sort_time) :
                                     (a.sort_time < b.sort_time);
                   });
}

int agent_ui_generations_selected_index(const GenPaneData &data)
{
  if (!data.selected[0]) {
    return -1;
  }
  for (int i = 0; i < data.count; i++) {
    if (STREQ(data.items[i].key, data.selected)) {
      return i;
    }
  }
  return -1;
}
