/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Custom footer region drawing with pixel-precise positioning.
 * Layout (from top to bottom):
 *   [Pending attachment thumbnails row (optional)]
 *   [Mode buttons row: Ideate | Lookdev | Imagine | Code | General]
 *   [Attach Btns] [Text Input fills space] [Send Btn at right edge]
 *
 * REFACTORED: Modular architecture with separated concerns:
 * - mixie_chat_footer_constants.hh: Magic number constants
 * - mixie_chat_footer_cache.cc: Theme and attachment caching
 * - mixie_chat_footer_layout.cc: Height/position calculations
 * - mixie_chat_footer_thumbnails.cc: Thumbnail rendering
 */

#include "BLI_listbase.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BLF_api.hh"

#include "BKE_context.hh"
#include "BKE_main.hh"
#include "BKE_screen.hh"

#include "DNA_scene_types.h"
#include "DNA_space_types.h"

#include "ED_screen.hh"

#include "GPU_framebuffer.hh"
#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_footer_constants.hh"
#include "mixie_chat_footer_intern.hh"
#include "mixie_chat_intern.hh"

/* -------------------------------------------------------------------- */
/** \name Rotating Input Placeholder
 *
 * Instead of a single static "Describe your next step" hint, the empty
 * composer shows one of several concrete example prompts, rotating so the
 * user sees a different suggestion each time they return to an empty input.
 *
 * Rotation policy (see mixie_chat_footer_next_placeholder):
 *   - The suggestion only changes when the input field TRANSITIONS to empty
 *     (fresh session, or right after a message is sent / the text is cleared).
 *     While the field stays empty and untouched, the same hint is held — so
 *     it never flickers between redraws, and never changes mid-typing.
 *   - On each such transition a new index is chosen pseudo-randomly and is
 *     guaranteed to differ from the one just shown (no immediate repeats).
 *   - The pick is seeded from the wall clock (BLI_time_now_seconds), so the
 *     sequence a user sees is effectively random rather than a fixed cycle.
 *
 * This state is process-global and intentionally shared between the docked
 * Mixie chat footer and the floating Agent Bubble footer (both call
 * mixie_chat_footer_region_draw and share scene.mixie_chat_input).
 * \{ */

static const char *g_placeholder_suggestions[] = {
    "Create a stylized campfire with logs and stones",
    "Create a street lamp in Victorian style",
    "Bake a detailed sword into a low-poly game asset",
    "Texture a knight's helmet as battle-worn steel",
    "Model a small dragon hatchling",
    "Create a stack of old books tied with rope",
    "What can I do in Mixar",
};
static const int g_placeholder_count = int(ARRAY_SIZE(g_placeholder_suggestions));

/* Returns the placeholder to show for the current draw.
 * `is_empty` is whether scene.mixie_chat_input is currently empty. */
static const char *mixie_chat_footer_next_placeholder(bool is_empty)
{
  static int current_idx = 0;
  static bool prev_empty = false; /* forces a fresh pick on the first empty draw */

  if (is_empty && !prev_empty) {
    /* Field just became empty (or first ever draw): pick a new suggestion
     * that differs from the one previously shown. Using the wall clock as
     * entropy keeps the choice unpredictable without an RNG dependency. */
    if (g_placeholder_count > 1) {
      const uint64_t entropy = uint64_t(BLI_time_now_seconds() * 1000.0);
      const int step = 1 + int(entropy % uint64_t(g_placeholder_count - 1));
      current_idx = (current_idx + step) % g_placeholder_count;
    }
  }
  prev_empty = is_empty;

  return g_placeholder_suggestions[current_idx];
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Footer Region Callbacks
 * \{ */

void mixie_chat_footer_region_init(wmWindowManager *wm, ARegion *region)
{
  ED_region_header_init(region);

  /* Register the "Mixie Chat" keymap on the footer region so Cmd+V / Ctrl+V
   * reaches MIXIE_CHAT_OT_paste_image. This is the same keymap the main region
   * uses — it contains the paste binding alongside select/copy. The select/copy
   * operators will simply fail their polls in the footer context (harmless).
   *
   * No double-invocation with text edit paste: ui_do_but_textedit() consumes the
   * keyboard event with WM_UI_HANDLER_BREAK after it performs the inline
   * MIXIE_CHAT_OT_paste_image call. */
  wmKeyMap *chat_keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "Mixie Chat", SPACE_MIXIE_CHAT, RGN_TYPE_WINDOW);
  WM_event_add_keymap_handler(&region->runtime->handlers, chat_keymap);

  /* Register dropbox handler for image drag-and-drop onto the footer. */
  ListBase *dropboxes = WM_dropboxmap_find(
      "Mixie Chat Footer", SPACE_MIXIE_CHAT, RGN_TYPE_TOOLS);
  WM_event_add_dropbox_handler(&region->runtime->handlers, dropboxes);

  /* Set initial footer height using centralized calculation
   * This ensures the footer gets adequate space from the start */
  region->sizey = footer_layout_calculate_height(nullptr, nullptr, nullptr, 0);
}

void mixie_chat_footer_region_layout(const bContext *C, ARegion *region)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return;
  }

  /* Get cached theme for consistent calculations */
  const FooterThemeCache *theme = footer_cache_get_theme();

  /* Calculate required height using centralized function
   * CRITICAL: This eliminates code duplication between layout and draw */
  bool has_overflow = false;
  int input_lines = footer_layout_get_input_line_count(scene, region->winx);
  int mention_rows = mixie_chat_mention_row_count(scene);
  int required_height_unscaled = footer_layout_calculate_height(
      scene, theme, &has_overflow, input_lines, mention_rows);

  /* Warn if height exceeds maximum (should rarely happen) */
  if (has_overflow) {
    /* Could log warning here if needed */
  }

  /* Update region size if changed - MUST BE IN UNSCALED UNITS */
  if (region->sizey != required_height_unscaled) {
    region->sizey = required_height_unscaled;

    ScrArea *area = CTX_wm_area(C);
    if (area) {
      ED_area_tag_region_size_update(area, region);

      /* OPTIMIZED: Only redraw main region instead of all regions
       * The main region's View2D bounds depend on footer height */
      LISTBASE_FOREACH (ARegion *, rgn, &area->regionbase) {
        if (rgn->regiontype == RGN_TYPE_WINDOW) {
          ED_region_tag_redraw(rgn);
          break; /* Early exit after finding main region */
        }
      }
    }
  }
}

void mixie_chat_footer_region_draw(const bContext *C, ARegion *region)
{
  /* Get scene and main for properties */
  Scene *scene = CTX_data_scene(C);
  Main *bmain = CTX_data_main(C);
  if (!scene) {
    return;
  }

  /* CRITICAL FIX: Force footer size BEFORE any UI drawing.
   * Blender's layout system may reset sizey, so we enforce it here */
  const FooterThemeCache *theme = footer_cache_get_theme();
  int input_lines = footer_layout_get_input_line_count(scene, region->winx);
  int mention_rows = mixie_chat_mention_row_count(scene);
  region->sizey = footer_layout_calculate_height(scene, theme, nullptr, input_lines, mention_rows);

  ScrArea *area = CTX_wm_area(C);
  if (area) {
    ED_area_tag_region_size_update(area, region);

    /* OPTIMIZED: Only redraw main region, not all regions */
    LISTBASE_FOREACH (ARegion *, rgn, &area->regionbase) {
      if (rgn->regiontype == RGN_TYPE_WINDOW) {
        ED_region_tag_redraw(rgn);
        break;
      }
    }
  }

  /* Clear background — use custom colour if the Agent Bubble set one. */
  if (mixie_chat_has_bg_override()) {
    float bg[4];
    mixie_chat_get_bg_override(bg);
    GPU_clear_color(bg[0], bg[1], bg[2], bg[3]);
  }
  else {
    UI_ThemeClearColor(TH_BACK);
  }

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  /* Graceful degradation: if Python failed to register the property, default to false
   * (shows Send button). RNA_boolean_get would assert/crash; find_property is safe. */
  PropertyRNA *busy_prop = RNA_struct_find_property(&scene_ptr, "mixie_chat_is_busy");
  bool is_busy = busy_prop ? RNA_property_boolean_get(&scene_ptr, busy_prop) : false;

  /* Get cached attachment data - ELIMINATES per-frame allocations */
  int pending_count = 0;
  const blender::Vector<FooterAttachmentCache> *attachments = footer_cache_get_attachments(
      scene, &pending_count);

  /* Calculate element positions using centralized function */
  FooterElementPositions pos;
  footer_layout_calculate_positions(
      region->winx, pending_count, theme, &pos, input_lines, mention_rows);

  const float scale = UI_SCALE_FAC;

  /* ===== CREATE UI BLOCK FOR BUTTONS ===== */
  uiBlock *block = UI_block_begin(C, region, __func__, blender::ui::EmbossType::Emboss);

  /* ===== ROW 1 (TOP): INPUT FIELD ===== */
  if (pos.input_w > 0) {
    /* Graceful degradation: if Python hasn't registered the property yet, skip the
     * text field entirely. uiDefButR crashes on a missing RNA property (null deref
     * inside ui_but_string_get_ex). Same pattern as mixie_chat_is_busy above. */
    PropertyRNA *input_prop = RNA_struct_find_property(&scene_ptr, "mixie_chat_input");
    if (input_prop) {
      uiBut *input_but = uiDefButR(block,
                                   ButType::Text,
                                   0,
                                   "",  /* Empty label - placeholder will be set below */
                                   pos.input_x,
                                   pos.input_y,
                                   pos.input_w,
                                   pos.input_height,
                                   &scene_ptr,
                                   "mixie_chat_input",
                                   -1,
                                   0.0f,
                                   0.0f,
                                   nullptr);

      if (input_but) {
        /* Set placeholder text that disappears when typing. Rotates through a
         * set of concrete example prompts, picking a fresh one each time the
         * composer returns to empty (see mixie_chat_footer_next_placeholder). */
        const bool input_is_empty = (RNA_property_string_length(&scene_ptr, input_prop) == 0);
        UI_but_placeholder_set(input_but, mixie_chat_footer_next_placeholder(input_is_empty));

        /* Place cursor at end instead of selecting all text when re-activating. */
        UI_but_flag2_enable(input_but, UI_BUT2_ACTIVATE_ON_INIT_NO_SELECT);

        /* Enable UI_BUT_TEXTEDIT_UPDATE so interface_handlers.cc inserts \x1F on Enter.
         * Shift+Enter inserts a real newline for multi-line input.
         * The Python property's update callback detects the \x1F marker and triggers submit.
         * This ensures Enter key submits, but focus loss (clicking outside) does NOT submit.
         * NOTE: Do NOT use UI_but_func_set here - that callback fires on focus loss too. */
        UI_but_flag_enable(input_but, UI_BUT_TEXTEDIT_UPDATE);
      }
    }
  }

  /* ===== ROW 2 (BOTTOM): CONTROL BUTTONS ===== */

  /* LEFT SIDE: Mode dropdown with dynamic icon */
  PropertyRNA *mode_prop = RNA_struct_find_property(&scene_ptr, "mixie_chat_mode");
  int icon_id = ICON_MIXAR_ICON;  /* Default to Mixar logo */
  bool is_generate_mode = false;
  std::string mode_name = "Agent";  /* Default mode name */

  if (mode_prop) {
    /* Get current enum value to determine appropriate icon */
    int current_value = RNA_property_enum_get(&scene_ptr, mode_prop);

    /* Get enum items to determine icon and name for current mode */
    const EnumPropertyItem *items;
    int items_len;
    bool free_items;
    RNA_property_enum_items_gettexted(
        const_cast<bContext *>(C), &scene_ptr, mode_prop, &items, &items_len, &free_items);

    /* Set icon and name based on mode identifier
     * Note: Using ICON_MIXAR_ICON as fallback until custom SVGs are created */
    for (int i = 0; i < items_len; i++) {
      if (items[i].value == current_value) {
        mode_name = items[i].name;  /* Get display name */
        if (strcmp(items[i].identifier, "GENERATE") == 0) {
          icon_id = ICON_GENERATE;  /* TODO: Create generate.dat icon, using placeholder */
          is_generate_mode = true;
        }
        else {
          icon_id = ICON_AGENT;  /* TODO: Create agent.dat icon, using placeholder */
        }
        break;
      }
    }

    /* Create dropdown button with mode-specific icon and text label
     * Add spaces around text for internal padding */
    std::string padded_mode_name = " " + mode_name + " ";
    uiDefIconTextButR(block,
                      ButType::Menu,
                      0,
                      icon_id,
                      padded_mode_name.c_str(),  /* Display current enum value's name with padding */
                      pos.dropdown_x,
                      pos.buttons_y,
                      pos.dropdown_width,
                      pos.button_row_height,
                      &scene_ptr,
                      "mixie_chat_mode",
                      -1,
                      std::nullopt);

    if (free_items) {
      MEM_freeN((void *)items);
    }
  }

  /* GENERATE TYPE DROPDOWN: Show when Generate mode is selected */
  int generate_dropdown_x = pos.dropdown_x;
  if (is_generate_mode) {
    generate_dropdown_x = pos.dropdown_x + pos.dropdown_width + int(FOOTER_BUTTON_SPACING_BASE * scale);

    PropertyRNA *gen_type_prop = RNA_struct_find_property(&scene_ptr, "mixie_chat_generate_type");
    if (gen_type_prop) {
      /* Get current generate type to determine icon and text */
      int current_gen_value = RNA_property_enum_get(&scene_ptr, gen_type_prop);
      int gen_icon_id = ICON_MIXAR_ICON;  /* Default to Mixar logo */
      std::string gen_type_name = "Image";  /* Default type name */

      const EnumPropertyItem *gen_items;
      int gen_items_len;
      bool gen_free_items;
      RNA_property_enum_items_gettexted(
          const_cast<bContext *>(C), &scene_ptr, gen_type_prop, &gen_items, &gen_items_len, &gen_free_items);

      /* Name and icon come from the enum item itself. The generate-type
       * enum is catalog-driven (service keys + labels from the backend
       * generation catalog; see chat_props.py), so the Python items
       * callback owns per-service icons — no identifier hardcoding here. */
      for (int i = 0; i < gen_items_len; i++) {
        if (gen_items[i].value == current_gen_value) {
          gen_type_name = gen_items[i].name;  /* Get display name */
          if (gen_items[i].icon) {
            gen_icon_id = gen_items[i].icon;
          }
          break;
        }
      }

      /* Create generate type dropdown with icon and text label
       * Add spaces around text for internal padding */
      std::string padded_gen_type_name = " " + gen_type_name + " ";
      uiDefIconTextButR(block,
                        ButType::Menu,
                        0,
                        gen_icon_id,
                        padded_gen_type_name.c_str(),  /* Display current enum value's name with padding */
                        generate_dropdown_x,
                        pos.buttons_y,
                        pos.dropdown_width,
                        pos.button_row_height,
                        &scene_ptr,
                        "mixie_chat_generate_type",
                        -1,
                        std::nullopt);

      if (gen_free_items) {
        MEM_freeN((void *)gen_items);
      }
    }
  }

  /* Create footer icon buttons with hover effects.
   * Use EmbossType::None for clean icon-only appearance with subtle hover. */
  UI_block_emboss_set(block, blender::ui::EmbossType::None);

  /* Attachment button (paperclip icon) - position after dropdowns */
  int attach_btn_final_x = pos.attach_btn_x;
  if (is_generate_mode) {
    /* Position after both dropdowns when generate mode is active */
    attach_btn_final_x = generate_dropdown_x + pos.dropdown_width + int(FOOTER_BUTTON_SPACING_BASE * scale);
  }

  uiDefIconButO(block,
                ButType::But,
                "MIXIE_CHAT_OT_add_image_from_file",
                blender::wm::OpCallContext::InvokeDefault,
                ICON_PAPERCLIP,
                attach_btn_final_x,
                pos.buttons_y,
                pos.attach_btn_size,
                pos.button_row_height,
                std::nullopt);

  /* "Attach Selected Moodboard Image" button removed — moodboard
   * selection auto-mirrors into pending_attachments via the
   * polling sync in moodboard.core.chat_sync, so the explicit
   * attach button was redundant. The keymap binding and the
   * underlying MIXIE_CHAT_OT_attach_moodboard_image operator
   * remain (the operator just nudges a sync) so muscle memory
   * keeps working — only the footer entry is gone. */
  int next_btn_x = attach_btn_final_x + pos.attach_btn_size +
                    int(FOOTER_BUTTON_SPACING_BASE * scale);

  /* Screenshot button (camera icon) — only in AGENT mode, hidden in Agent Bubble */
  const bool is_bubble = (area && area->spacetype == SPACE_AGENT_BUBBLE);
  int screenshot_btn_x = next_btn_x;

  if (!is_generate_mode && !is_bubble) {
    uiDefIconButO(block,
                  ButType::But,
                  "MIXIE_CHAT_OT_capture_screenshot",
                  blender::wm::OpCallContext::InvokeDefault,
                  ICON_CAMERA_DATA,
                  screenshot_btn_x,
                  pos.buttons_y,
                  pos.attach_btn_size,
                  pos.button_row_height,
                  std::nullopt);
    next_btn_x = screenshot_btn_x + pos.attach_btn_size +
                 int(FOOTER_BUTTON_SPACING_BASE * scale);
  }

  /* Plan mode toggle (iOS-style switch) removed for now. It used to sit
   * here, only in Agent mode: a "Plan" label + iOS switch with a
   * transparent click target running MIXIE_CHAT_OT_toggle_plan_mode, plus
   * a footer_draw_plan_toggle() GPU overlay in the custom-overlay section
   * below. The mixie_chat_plan_enabled property and its toggle operator
   * remain, so the agent's plan behaviour is unchanged (default off) —
   * only the footer control is gone. To restore, re-add this label-measure
   * + uiDefButO click-target block and the footer_draw_plan_toggle() call. */

  /* Check if any generation is running in generate mode */
  bool is_generating = false;
  if (is_generate_mode) {
    /* Check the generating flag for the current generate sub-type */
    PropertyRNA *gen_type_prop_chk = RNA_struct_find_property(
        &scene_ptr, "mixie_chat_generate_type");
    if (gen_type_prop_chk) {
      int gen_val = RNA_property_enum_get(&scene_ptr, gen_type_prop_chk);
      const EnumPropertyItem *gen_items_chk;
      int gen_items_chk_len;
      bool gen_free_chk;
      RNA_property_enum_items_gettexted(
          const_cast<bContext *>(C), &scene_ptr, gen_type_prop_chk,
          &gen_items_chk, &gen_items_chk_len, &gen_free_chk);
      /* Identifiers are catalog service keys (see chat_props.py); map each
       * to the scene bool its queue listener / generator toggles. */
      const char *gen_flag_name = nullptr;
      for (int i = 0; i < gen_items_chk_len; i++) {
        if (gen_items_chk[i].value == gen_val) {
          if (strcmp(gen_items_chk[i].identifier, "depth_to_image") == 0)
            gen_flag_name = "mixie_lookdev_is_generating";
          else if (strcmp(gen_items_chk[i].identifier, "pbr_gen") == 0)
            gen_flag_name = "mixie_lookdev360_is_generating";
          else if (strcmp(gen_items_chk[i].identifier, "model_3d") == 0 ||
                   strcmp(gen_items_chk[i].identifier, "image_to_3d") == 0)
            gen_flag_name = "mixie_image_to_3d_is_generating";
          else if (strcmp(gen_items_chk[i].identifier, "hunyuan_rapid") == 0)
            gen_flag_name = "mixie_hunyuan_rapid_is_generating";
          else if (strcmp(gen_items_chk[i].identifier, "image_gen") == 0)
            gen_flag_name = "mixie_imagegen_is_generating";
          else if (strcmp(gen_items_chk[i].identifier, "scene_reconstruction") == 0)
            gen_flag_name = "mixie_scene_recon_is_generating";
          break;
        }
      }
      if (gen_free_chk) {
        MEM_freeN((void *)gen_items_chk);
      }
      if (gen_flag_name) {
        PropertyRNA *gflag = RNA_struct_find_property(&scene_ptr, gen_flag_name);
        if (gflag) {
          is_generating = RNA_property_boolean_get(&scene_ptr, gflag);
        }
      }
    }
  }

  /* RIGHT SIDE: Abort when busy, Cancel when generating, Send when idle.
   * Intentional asymmetry in draw strategy:
   *   BUSY  → uiDefIconButO(ICON_CANCEL): icon drawn by Blender's widget system.
   *   GENERATING → uiDefIconButO(ICON_CANCEL): cancel active generation.
   *   IDLE  → uiDefButO("") + footer_draw_submit_icon() GPU overlay: custom scaled
   *            ICON_SUBMIT_ARROW that cannot be sized correctly via the widget system.
   * Do not unify these branches — the GPU overlay is required for the Send icon. */
  if (is_busy) {
    uiDefIconButO(block,
                  ButType::But,
                  "MIXIE_CHAT_OT_abort_session",
                  blender::wm::OpCallContext::InvokeDefault,
                  ICON_CANCEL,
                  pos.send_btn_x,
                  pos.buttons_y,
                  pos.btn_size,
                  pos.btn_size,
                  std::nullopt);
  }
  else if (is_generating) {
    uiDefIconButO(block,
                  ButType::But,
                  "MIXIE_CHAT_OT_cancel_generation",
                  blender::wm::OpCallContext::InvokeDefault,
                  ICON_CANCEL,
                  pos.send_btn_x,
                  pos.buttons_y,
                  pos.btn_size,
                  pos.btn_size,
                  std::nullopt);
  }
  else {
    uiDefButO(block,
              ButType::But,
              "MIXIE_CHAT_OT_send_message",
              blender::wm::OpCallContext::InvokeDefault,
              "",
              pos.send_btn_x,
              pos.buttons_y,
              pos.btn_size,
              pos.btn_size,
              std::nullopt);
  }

  /* Restore emboss for any subsequent UI elements */
  UI_block_emboss_set(block, blender::ui::EmbossType::Emboss);

  /* Finalize block */
  UI_block_end(C, block);
  UI_block_draw(C, block);

  /* Custom GPU overlays (delegated to mixie_chat_footer_draw.cc) */
  footer_draw_send_button_glow(region, &scene_ptr, pos, scale);
  if (!is_busy && !is_generating) {
    footer_draw_submit_icon(region, pos);
  }
  /* Plan mode toggle overlay removed for now (see the click-target
   * removal above); footer_draw_plan_toggle() remains available to
   * restore it. */
  footer_draw_thumbnails(C, region, bmain, &scene_ptr, pos, theme, pending_count, attachments, scale);

  /* '@' mention autocomplete dropdown above the input (mixie_chat_mention.cc).
   * Clicks/keys are handled by the text-edit hooks in interface_handlers.cc
   * while the input is focused — this is pure drawing. */
  if (mention_rows > 0) {
    mixie_chat_mention_draw(scene, region);
  }
}

/** \} */
