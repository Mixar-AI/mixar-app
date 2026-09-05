/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "RE_mixar_visibility.hh"

static bool render_mixar_visibility_validate(wmOperator *op, const Scene *scene)
{
  if (!RNA_boolean_get(op->ptr, "capture_visible_objects")) {
    return true;
  }
  if (RNA_boolean_get(op->ptr, "animation") ||
      RNA_boolean_get(op->ptr, "use_sequencer_scene") ||
      !STREQ(scene->r.engine, "BLENDER_EEVEE"))
  {
    BKE_report(op->reports, RPT_ERROR, "Visible object capture supports Eevee still renders only");
    return false;
  }
  if ((scene->r.scemode & R_DOCOMP) && scene->compositing_node_group) {
    BKE_report(op->reports, RPT_ERROR, "Disable compositing when capturing visible objects");
    return false;
  }
  return true;
}

static void render_mixar_visibility_property(wmOperatorType *ot)
{
  PropertyRNA *prop = RNA_def_boolean(ot->srna,
                                     "capture_visible_objects",
                                     false,
                                     "Capture Visible Objects",
                                     "Capture directly visible meshes during an Eevee still render");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}
