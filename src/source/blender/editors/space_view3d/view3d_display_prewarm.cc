/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * One-shot pre-warm of the viewport display shaders.
 *
 * A 3D viewport is blitted to screen through an OpenColorIO display shader
 * whose variant depends on the viewport's shading: solid shading uses the
 * configuration's default view transform, material preview the scene's view
 * transform and look, rendered shading the full render settings. Each variant
 * is built and compiled on first use, on the main thread (Metal
 * `newLibraryWithSource`, measured 0.34 s). Zen Mode's viewport is in material
 * preview and Engine Mode's workspaces open in solid shading, so the first
 * switch to Engine Mode paid that compile inside the switch.
 *
 * Python sets #PREWARM_WM_PROP once after startup (workflow bootstrap); the
 * next overlay pass compiles the variants the current scene can need and
 * clears the flag. Mirrors draw_color_management.cc's `viewport_settings_apply`
 * (view settings per variant) and `dither_get`.
 */

#include "BKE_colortools.hh"
#include "BKE_context.hh"
#include "BKE_idprop.hh"

#include "BLI_string_utf8.h"

#include "DNA_scene_types.h"
#include "DNA_windowmanager_types.h"

#include "GPU_immediate.hh"

#include "IMB_colormanagement.hh"

#include "view3d_intern.hh"

namespace blender {

static const char *PREWARM_WM_PROP = "mixar_prewarm_display_shaders";

static void prewarm_variant(const ColorManagedViewSettings *view_settings,
                            const ColorManagedDisplaySettings *display_settings,
                            const float dither)
{
  /* The viewport blit always merges the overlay buffer and converts to the
   * display space (#GPU_viewport_draw_to_screen). Binding the display shader
   * validates the last immediate-mode vertex format, which here is whatever the
   * overlay pass drew last (the agent halo's); reset it first, exactly as
   * #GPU_viewport_draw_to_screen does, or debug builds assert. */
  immVertexFormat();
  if (IMB_colormanagement_setup_glsl_draw_from_space(
          view_settings, display_settings, nullptr, dither, false, true))
  {
    IMB_colormanagement_finish_glsl_draw();
  }
}

void view3d_display_shader_prewarm(const bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm || !wm->id.properties) {
    return;
  }
  IDProperty *prop = IDP_GetPropertyFromGroup(wm->id.properties, PREWARM_WM_PROP);
  if (!prop || !ELEM(prop->type, IDP_INT, IDP_BOOLEAN) || IDP_int_or_bool_get(prop) == 0) {
    return;
  }
  const Scene *scene = CTX_data_scene(C);
  if (scene == nullptr) {
    return;
  }
  /* One shot: clear first so a failure below cannot repeat the compile. */
  IDP_int_or_bool_set(prop, 0);

  const ColorManagedDisplaySettings *display_settings = &scene->display_settings;
  ColorManagedViewSettings view_settings;

  /* Solid shading: the configuration's default view, no dither. */
  BKE_color_managed_view_settings_init(&view_settings, display_settings, nullptr);
  prewarm_variant(&view_settings, display_settings, 0.0f);

  /* Material preview: default settings plus the scene's view transform and look. */
  BKE_color_managed_view_settings_init(&view_settings, display_settings, nullptr);
  STRNCPY_UTF8(view_settings.view_transform, scene->view_settings.view_transform);
  STRNCPY_UTF8(view_settings.look, scene->view_settings.look);
  prewarm_variant(&view_settings, display_settings, scene->r.dither_intensity);

  /* Rendered shading and scene-lit material preview: the full render settings. */
  prewarm_variant(&scene->view_settings, display_settings, scene->r.dither_intensity);
}

}  // namespace blender
