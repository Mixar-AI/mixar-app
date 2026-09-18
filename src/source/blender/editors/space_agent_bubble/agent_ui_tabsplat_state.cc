/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 * Catalog state and enum projection for the Gaussian Splat pane.
 */

#include "MEM_guardedalloc.h"
#include "BKE_context.hh"
#include "BLI_string.h"
#include "BLI_utildefines.h"
#include "DNA_scene_types.h"
#include "DNA_windowmanager_types.h"
#include "RNA_access.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_tabsplat_intern.hh"

namespace blender {
/* -------------------------------------------------------------------- */
/** \name State resolution
 * \{ */

namespace {

/** Mirror of generation_params' `_sanitize` (`re.sub(r"\W", "_", name)`). */
void sanitize_ident(const char *in, char *out, const int out_len)
{
  int n = 0;
  for (int i = 0; in[i] != '\0' && n < out_len - 1; i++) {
    const char c = in[i];
    const bool word = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                      (c >= '0' && c <= '9') || (c == '_');
    out[n++] = word ? c : '_';
  }
  out[n] = '\0';
}

bool ident_is_placeholder(const char *ident)
{
  return ident[0] == '\0' || STREQ(ident, "LOADING") || STREQ(ident, "NONE") ||
         STREQ(ident, "ERROR");
}

}  // namespace

bool splat_state_resolve(const bContext *C, SplatTabState *r_state)
{
  *r_state = {};

  Scene *scene = CTX_data_scene(C);
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!scene || !wm) {
    return false;
  }

  /* scene.mixie_moodboard_sidebar.tab_world_labs */
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *sidebar_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_sidebar");
  if (!sidebar_prop || RNA_property_type(sidebar_prop) != PROP_POINTER) {
    return false;
  }
  PointerRNA sidebar = RNA_property_pointer_get(&scene_ptr, sidebar_prop);
  PropertyRNA *tab_prop = RNA_struct_find_property(&sidebar, "tab_world_labs");
  if (!tab_prop || RNA_property_type(tab_prop) != PROP_POINTER) {
    return false;
  }
  r_state->tab = RNA_property_pointer_get(&sidebar, tab_prop);
  if (r_state->tab.data == nullptr) {
    return false;
  }

  /* Current model slug — the enum IDENTIFIER is the catalog slug. Dynamic
   * items need the real context. */
  PropertyRNA *model_prop = RNA_struct_find_property(&r_state->tab, "model");
  if (!model_prop || RNA_property_type(model_prop) != PROP_ENUM) {
    return false;
  }
  {
    const int value = RNA_property_enum_get(&r_state->tab, model_prop);
    const char *ident = nullptr;
    if (!RNA_property_enum_identifier(
            const_cast<bContext *>(C), &r_state->tab, model_prop, value, &ident) ||
        !ident || ident_is_placeholder(ident))
    {
      return false;
    }
    BLI_strncpy(r_state->model_slug, ident, sizeof(r_state->model_slug));
    const char *name = nullptr;
    if (RNA_property_enum_name_gettexted(
            const_cast<bContext *>(C), &r_state->tab, model_prop, value, &name) &&
        name)
    {
      r_state->model_label = name;
    }
  }

  /* WindowManager generation-params group: mixar_genparams_world_labs__<slug>. */
  char slug_sane[128];
  sanitize_ident(r_state->model_slug, slug_sane, sizeof(slug_sane));
  char group_attr[192];
  SNPRINTF(group_attr, "mixar_genparams_world_labs__%s", slug_sane);
  BLI_strncpy(r_state->group_attr, group_attr, sizeof(r_state->group_attr));

  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *group_prop = RNA_struct_find_property(&wm_ptr, group_attr);
  if (!group_prop || RNA_property_type(group_prop) != PROP_POINTER) {
    return false;
  }
  r_state->params = RNA_property_pointer_get(&wm_ptr, group_prop);
  if (r_state->params.data == nullptr) {
    return false;
  }

  /* `mode` and `lod` enums — the drawer fails closed without both. */
  r_state->mode_prop = RNA_struct_find_property(&r_state->params, "p_mode");
  r_state->lod_prop = RNA_struct_find_property(&r_state->params, "p_lod");
  if (!r_state->mode_prop || RNA_property_type(r_state->mode_prop) != PROP_ENUM ||
      !r_state->lod_prop || RNA_property_type(r_state->lod_prop) != PROP_ENUM)
  {
    return false;
  }

  const int mode_value = RNA_property_enum_get(&r_state->params, r_state->mode_prop);
  const char *mode_ident = nullptr;
  if (RNA_property_enum_identifier(const_cast<bContext *>(C),
                                   &r_state->params,
                                   r_state->mode_prop,
                                   mode_value,
                                   &mode_ident) &&
      mode_ident)
  {
    BLI_strncpy(r_state->mode_ident, mode_ident, sizeof(r_state->mode_ident));
  }
  /* Compare the WHOLE identifier, case-insensitively, exactly as the drawer
   * does (`str(...).upper()` against {IMAGE, TEXT}). A first-character test
   * made any future catalog mode beginning with "i" grow the image
   * reference UI, and the drawer fails closed on a mode it does not know —
   * so this pane must too, or it offers a submit the N-panel refuses. */
  if (BLI_strcasecmp(r_state->mode_ident, "IMAGE") == 0) {
    r_state->image_mode = true;
  }
  else if (BLI_strcasecmp(r_state->mode_ident, "TEXT") == 0) {
    r_state->image_mode = false;
  }
  else {
    return false;
  }

  /* Busy state from the unified queue — the pane's only honest source: World
   * Labs enqueues pass no `scene_flag`, so no legacy `is_generating` property
   * is ever written for this flow. */
  r_state->active_jobs = pane_active_job_count(C, SPLAT_SERVICE_KEY);

  r_state->use_selected = false;
  if (PropertyRNA *use_sel = RNA_struct_find_property(&r_state->tab, "use_selected_image")) {
    r_state->use_selected = RNA_property_boolean_get(&r_state->tab, use_sel);
  }

  /* The tab's own uploaded/captured input, for the bottom row's preview. */
  r_state->reference_image = nullptr;
  if (PropertyRNA *ref = RNA_struct_find_property(&r_state->tab, "reference_image")) {
    if (RNA_property_type(ref) == PROP_POINTER) {
      PointerRNA img = RNA_property_pointer_get(&r_state->tab, ref);
      r_state->reference_image = static_cast<Image *>(img.data);
    }
  }
  return true;
}

int splat_enum_items_get(const bContext *C,
                         PointerRNA *ptr,
                         PropertyRNA *prop,
                         SplatEnumItem *r_items,
                         const int max_items)
{
  const EnumPropertyItem *items = nullptr;
  int totitem = 0;
  bool free = false;
  RNA_property_enum_items(
      const_cast<bContext *>(C), ptr, prop, &items, &totitem, &free);
  int count = 0;
  const int current = RNA_property_enum_get(ptr, prop);
  for (int i = 0; i < totitem; i++) {
    if (items[i].identifier == nullptr || items[i].identifier[0] == '\0') {
      continue; /* separators */
    }
    if (count < max_items) {
      r_items[count].ident = items[i].identifier;
      r_items[count].label = items[i].name ? items[i].name : items[i].identifier;
      r_items[count].active = (items[i].value == current);
    }
    count++;
  }
  if (free) {
    MEM_delete(items);
  }
  /* Count the full enum: a bounded segment buffer must not hide later choices. */
  return count;
}

/** \} */

}  // namespace blender
