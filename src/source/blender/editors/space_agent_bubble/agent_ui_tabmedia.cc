/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Media tab pane — the moodboard's Image Gen / Video Gen re-skinned as
 * island chips. All state/operators are the moodboard tabs' own (see
 * agent_ui_tabmedia.hh); param chips project the catalog param group at
 * `wm.mixar_genparams_<service>__<model>` — no param names hardcoded.
 */

#include <algorithm>
#include <cstdio>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_interface_layout.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_ui_pane_kit.hh"
#include "agent_ui_tabmedia.hh"
#include "agent_ui_tabmedia_intern.hh"
#include "agent_ui_theme.hh"

/* -------------------------------------------------------------------- */
/** \name Draw
 * \{ */

void agent_ui_tabmedia_draw(const bContext *C,
                            ARegion *region,
                            const rctf &panel,
                            const float u)
{
  Scene *scene = CTX_data_scene(C);
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!scene || !wm) {
    return;
  }

  /* Drawable band: the panel clipped to this region's framebuffer. */
  rctf band = panel;
  band.ymin = std::max(band.ymin, 0.0f);
  band.ymax = std::min(band.ymax, float(BLI_rcti_size_y(&region->winrct) + 1));
  if (BLI_rctf_size_y(&band) < 120.0f * u) {
    return;
  }

  const float col_param[4] = PANE_COL_CHIP;
  const float col_value[4] = PANE_COL_PILL_DIM;
  const float col_value_on[4] = PANE_COL_PILL;
  const float col_text[4] = AGENT_COL_TEXT;
  const float col_strong[4] = AGENT_COL_TEXT_STRONG;
  const float col_dim[4] = AGENT_COL_TEXT_DIM;

  const float font = PANE_FONT * u;
  const float font_sub = PANE_FONT_SUB * u;
  const float left = band.xmin + PANE_INSET_X * u;
  const float right = band.xmax - PANE_INSET_X * u;

  /* ---- Sub-tab state (wm.mixar_bubble_media_kind). ---- */
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  char kind_id[64] = "IMAGE";
  char kind_label[64] = "";
  media_read_enum(C, &wm_ptr, "mixar_bubble_media_kind", kind_id, kind_label);
  const bool video = STREQ(kind_id, "VIDEO");

  /* ---- Tab group + catalog identity. ---- */
  PointerRNA tab_ptr = {};
  const bool tab_ok = media_sidebar_tab_ptr(
      scene, video ? "tab_video_gen" : "tab_imagegen", &tab_ptr);

  char mode_id[64] = "", mode_label[64] = "";
  char model_id[64] = "", model_label[64] = "";
  if (tab_ok) {
    media_read_enum(C, &tab_ptr, "mode", mode_id, mode_label);
    media_read_enum(C, &tab_ptr, "model", model_id, model_label);
  }
  const char *service_fallback = video ? "video_gen" : "image_gen";
  const char *service_key = media_ident_is_placeholder(mode_id) ? service_fallback : mode_id;

  /* Catalog params group on WindowManager. */
  PointerRNA group_ptr = {};
  bool group_ok = false;
  if (!media_ident_is_placeholder(model_id)) {
    char svc[64], mdl[64], attr[160];
    media_sanitize_key(service_key, svc, sizeof(svc));
    media_sanitize_key(model_id, mdl, sizeof(mdl));
    SNPRINTF(attr, "mixar_genparams_%s__%s", svc, mdl);
    PropertyRNA *group_prop = RNA_struct_find_property(&wm_ptr, attr);
    if (group_prop && RNA_property_type(group_prop) == PROP_POINTER) {
      group_ptr = RNA_property_pointer_get(&wm_ptr, group_prop);
      group_ok = group_ptr.data != nullptr;
    }
  }

  GPU_blend(GPU_BLEND_ALPHA);

  /* Shared panel wash (pane kit). */
  pane_wash_paint(panel, u);

  /* ---- Row 1: Image Generation / Video Generation segmented. ---- */
  const float seg_top = band.ymax - PANE_STRIP_TOP * u;
  const char *seg_labels[2] = {"Image Generation", "Video Generation"};
  rctf seg_rects[2];
  {
    /* Widths from the measured labels, track centred in the panel — the
     * kit's segmented control, so this matches 3D/Splat exactly. */
    rctf probe[2];
    const rctf track_probe = pane_segmented_layout(0.0f, seg_top, seg_labels, 2, u, probe);
    const float track_w = BLI_rctf_size_x(&track_probe);
    const float x0 = (band.xmin + band.xmax) * 0.5f - track_w * 0.5f;
    pane_segmented_layout(x0, seg_top, seg_labels, 2, u, seg_rects);
    pane_segmented_paint(seg_rects, seg_labels, video ? 1 : 0, 2, u);
  }

  /* ---- Params rows: model dropdown + catalog chips, wrap to 2 rows. ---- */
  MediaParamChip chips[MEDIA_MAX_CHIPS + 1];
  int chip_count = 0;
  int param_total = 0;

  if (tab_ok) {
    /* Model dropdown first (on the Scene tab group, like the moodboard). */
    MediaParamChip &model_chip = chips[chip_count++];
    model_chip = {};
    model_chip.kind = MediaChipKind::Enum;
    model_chip.on_wm_group = false;
    BLI_strncpy(model_chip.prop_id, "model", sizeof(model_chip.prop_id));
    BLI_strncpy(model_chip.label, "Model", sizeof(model_chip.label));
    BLI_strncpy(model_chip.value,
                model_label[0] ? model_label : "Loading...",
                sizeof(model_chip.value));

    if (group_ok) {
      chip_count += media_gather_param_chips(
          C,
          &group_ptr, chips + chip_count, MEDIA_MAX_CHIPS - chip_count, &param_total);
    }
    else if (!video) {
      /* Image Gen's catalog-not-loaded fallback: the legacy enums on the tab
       * group, mirroring the moodboard drawer's fallback branch. */
      const char *legacy[3] = {"style", "aspect_ratio", "resolution"};
      for (const char *prop_id : legacy) {
        if (chip_count >= MEDIA_MAX_CHIPS) {
          break;
        }
        char ident[64], label[64];
        PointerRNA tab_copy = tab_ptr;
        if (!media_read_enum(C, &tab_copy, prop_id, ident, label)) {
          continue;
        }
        MediaParamChip &chip = chips[chip_count++];
        chip = {};
        chip.kind = MediaChipKind::Enum;
        chip.on_wm_group = false;
        BLI_strncpy(chip.prop_id, prop_id, sizeof(chip.prop_id));
        PropertyRNA *prop = RNA_struct_find_property(&tab_ptr, prop_id);
        BLI_strncpy(chip.label,
                    prop ? RNA_property_ui_name(prop) : prop_id,
                    sizeof(chip.label));
        BLI_strncpy(chip.value, label, sizeof(chip.value));
      }
    }
  }

  /* Lay chips out, wrapping once — but never past the floor that reserves
   * the prompt box (kit contract): the box is claimed FIRST and the chips
   * elide into "+N more" rather than pushing the prompt out of existence
   * while Generate stays armed. */
  const float chip_h_px = PANE_ROW_H * u;
  float row_y = seg_top - PANE_ROW_PITCH * u;
  /* Never lifted above the first chip row's own bottom — the box would climb
   * over the chips it is supposed to sit under. */
  const float params_floor = std::min(pane_params_floor(panel, u), row_y - chip_h_px);
  float x = left;
  int rows_used = 1;
  int shown = 0;
  for (int i = 0; i < chip_count; i++) {
    const float w = media_chip_width(chips[i], u, font, font_sub);
    if (x + w > right && rows_used < 2 &&
        row_y - PANE_ROW_PITCH * u - chip_h_px >= params_floor)
    {
      rows_used++;
      row_y -= PANE_ROW_PITCH * u;
      x = left;
    }
    if (x + w > right) {
      break; /* Row full and no room to wrap — remaining chips overflow. */
    }
    chips[i].rect.xmin = x;
    chips[i].rect.xmax = x + w;
    chips[i].rect.ymax = row_y;
    chips[i].rect.ymin = row_y - chip_h_px;
    x += w + PANE_CHIP_GAP * u;
    shown++;
  }

  for (int i = 0; i < shown; i++) {
    const MediaParamChip &chip = chips[i];
    const float cy = BLI_rctf_cent_y(&chip.rect);
    pane_fill_round(&chip.rect, PANE_RADIUS * u, col_param);
    const float pad = PANE_CHIP_PAD_X * u;
    float tx = chip.rect.xmin + pad;
    pane_label_left(chip.label, tx, cy, font_sub, col_dim);
    tx += pane_text_width(chip.label, font_sub) + 10.0f * u;

    if (chip.kind == MediaChipKind::Enum) {
      pane_label_left(chip.value, tx, cy, font, col_text);
      /* Down chevron. */
      pane_label_left("\xE2\x96\xBE", chip.rect.xmax - pad - 10.0f * u, cy, font_sub, col_text);
    }
    else if (chip.kind == MediaChipKind::Bool) {
      rctf pill;
      pill.xmin = tx;
      pill.xmax = chip.rect.xmax - pad + 4.0f * u;
      pill.ymin = cy - (PANE_PILL_H * 0.5f) * u;
      pill.ymax = cy + (PANE_PILL_H * 0.5f) * u;
      pane_fill_round(&pill, PANE_RADIUS * u, chip.bool_value ? col_value_on : col_value);
      const float on_w = pane_text_width("ON", font_sub);
      const float off_w = pane_text_width("OFF", font_sub);
      const float span = BLI_rctf_size_x(&pill);
      pane_label_left("ON",
                   pill.xmin + span * 0.25f - on_w * 0.5f,
                   cy,
                   font_sub,
                   chip.bool_value ? col_strong : col_dim);
      pane_label_left("OFF",
                   pill.xmin + span * 0.75f - off_w * 0.5f,
                   cy,
                   font_sub,
                   chip.bool_value ? col_dim : col_strong);
    }
    else { /* Int */
      pane_label_left("\xE2\x88\x92", tx + 4.0f * u, cy, font, col_dim);
      pane_label_centre(chip.value,
                     (tx + chip.rect.xmax - pad) * 0.5f,
                     cy,
                     font,
                     col_text);
      pane_label_left("+", chip.rect.xmax - pad - 8.0f * u, cy, font, col_dim);
    }
  }
  if (shown < chip_count) {
    char more[32];
    SNPRINTF(more, "+%d more", chip_count - shown);
    pane_label_left(more, x, row_y - chip_h_px * 0.5f, font_sub, col_dim);
  }

  /* Video catalog-only unavailable state. */
  const bool video_unavailable = video && (!tab_ok || !group_ok);
  if (video_unavailable) {
    pane_label_centre("Video generation needs the live catalog",
                   (band.xmin + band.xmax) * 0.5f,
                   row_y - chip_h_px * 0.5f,
                   font,
                   col_dim);
  }

  /* ---- Prompt box: strip bottom -> panel bottom (kit contract), bottom
   * row INSIDE the box foot like every other pane. ---- */
  UNUSED_VARS(rows_used);
  const float strip_bottom = std::max(row_y - chip_h_px, params_floor);
  rctf prompt_box = pane_prompt_box_rect(panel, strip_bottom, u);
  const bool prompt_fits = pane_prompt_fits(prompt_box, u);
  /* Generate is a PAID action and must never submit a prompt the user cannot
   * see or edit, so it is armed only where the field is actually drawn. */
  const bool prompt_ok = prompt_fits && tab_ok &&
                         RNA_struct_find_property(&tab_ptr, "prompt") != nullptr;
  pane_prompt_box_paint(prompt_box, u);
  const float bottom_h = PANE_ROW_H * u;
  const float bottom_y = pane_bottom_row_ymin(prompt_box, u);

  /* Upload / capture / refs / generate chip geometry (kit metrics; painted
   * AFTER the embossed field block below — its chrome covers earlier
   * pixels). */
  rctf upload = {}, capture = {}, generate = {};
  const float upload_w = pane_action_chip_w("Upload Reference", true, u);
  const float capture_w = pane_action_chip_w("Capture Viewport", false, u);
  float bx = prompt_box.xmin + PANE_BOTTOM_IN_L * u;
  /* Both halves upload: the image half into tab_imagegen's reference
   * collection, the video half onto the moodboard AS SELECTED (Video Gen's
   * references ARE the board selection). */
  upload = {bx, bx + upload_w, bottom_y, bottom_y + bottom_h};
  bx = upload.xmax + PANE_CHIP_GAP * u;
  /* Capture Viewport: LIVE — mixar.pane_capture_viewport screenshots the 3D
   * viewport and attaches the still as this tab's reference (image half:
   * reference collection; video half: boarded selected). */
  capture = {bx, bx + capture_w, bottom_y, bottom_y + bottom_h};
  bx = capture.xmax + PANE_CHIP_GAP * u;


  /* Generate — dim while that tab's flag says a submit is in flight. */
  bool busy = false;
  {
    PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
    PropertyRNA *flag = RNA_struct_find_property(
        &scene_ptr, video ? "mixie_video_gen_is_generating" : "mixie_imagegen_is_generating");
    busy = flag && RNA_property_type(flag) == PROP_BOOLEAN &&
           RNA_property_boolean_get(&scene_ptr, flag);
  }
  const bool can_generate = tab_ok && !busy && !video_unavailable && prompt_ok;
  generate = pane_generate_rect(prompt_box, u);

  /* ---- Controls. Two blocks, the composer's split: unembossed operator /
   * dropdown buttons, embossed prompt field. ---- */
  uiBlock *block = UI_block_begin(
      C, region, "agent_island_media", blender::ui::EmbossType::None);
  uiBlock *field_block = UI_block_begin(
      C, region, "agent_island_media_field", blender::ui::EmbossType::Emboss);

  /* Sub-tab halves. */
  for (int i = 0; i < 2; i++) {
    uiBut *but = uiDefButO(block, ButType::But, "wm.context_set_enum",
                           blender::wm::OpCallContext::InvokeDefault, "",
                           int(seg_rects[i].xmin), int(seg_rects[i].ymin),
                           short(BLI_rctf_size_x(&seg_rects[i])),
                           short(BLI_rctf_size_y(&seg_rects[i])),
                           i == 0 ? "Image generation" : "Video generation");
    if (but) {
      PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "data_path", "window_manager.mixar_bubble_media_kind");
      RNA_string_set(op_ptr, "value", i == 0 ? "IMAGE" : "VIDEO");
    }
  }

  /* Param chips. */
  for (int i = 0; i < shown; i++) {
    const MediaParamChip &chip = chips[i];
    const int cx = int(chip.rect.xmin);
    const int cy = int(chip.rect.ymin);
    const short cw = short(BLI_rctf_size_x(&chip.rect));
    const short ch = short(BLI_rctf_size_y(&chip.rect));
    PointerRNA *owner = chip.on_wm_group ? &group_ptr : &tab_ptr;

    if (chip.kind == MediaChipKind::Enum) {
      /* `wm.context_menu_enum`, NOT an RNA menu button: a ButType::Menu
       * draws Blender's own down-arrow on top of the chevron the chip has
       * already painted, so the chip showed TWO arrows. An operator button
       * carries no chrome of its own and opens the same enum menu. */
      char data_path[256];
      if (chip.on_wm_group) {
        char svc[64], mdl[64];
        media_sanitize_key(service_key, svc, sizeof(svc));
        media_sanitize_key(model_id, mdl, sizeof(mdl));
        SNPRINTF(
            data_path, "window_manager.mixar_genparams_%s__%s.%s", svc, mdl, chip.prop_id);
      }
      else {
        SNPRINTF(data_path,
                 "scene.mixie_moodboard_sidebar.%s.%s",
                 video ? "tab_video_gen" : "tab_imagegen",
                 chip.prop_id);
      }
      uiBut *but = uiDefButO(block, ButType::But, "wm.context_menu_enum",
                             blender::wm::OpCallContext::InvokeDefault, "",
                             cx, cy, cw, ch, nullptr);
      if (but) {
        pane_but_tooltip_owned(but, chip.label);
        PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
        RNA_string_set(op_ptr, "data_path", data_path);
      }
    }
    else if (chip.kind == MediaChipKind::Bool) {
      char data_path[256];
      char svc[64], mdl[64];
      media_sanitize_key(service_key, svc, sizeof(svc));
      media_sanitize_key(model_id, mdl, sizeof(mdl));
      SNPRINTF(data_path, "window_manager.mixar_genparams_%s__%s.%s", svc, mdl, chip.prop_id);
      uiBut *but = uiDefButO(block, ButType::But, "wm.context_toggle",
                             blender::wm::OpCallContext::InvokeDefault, "",
                             cx, cy, cw, ch, nullptr);
      if (but) {
        pane_but_tooltip_owned(but, chip.label);
        PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
        RNA_string_set(op_ptr, "data_path", data_path);
      }
    }
    else { /* Int: left half cycles down, right half cycles up. */
      char data_path[256];
      char svc[64], mdl[64];
      media_sanitize_key(service_key, svc, sizeof(svc));
      media_sanitize_key(model_id, mdl, sizeof(mdl));
      SNPRINTF(data_path, "window_manager.mixar_genparams_%s__%s.%s", svc, mdl, chip.prop_id);
      const short half = short(cw / 2);
      for (int side = 0; side < 2; side++) {
        uiBut *but = uiDefButO(block, ButType::But, "wm.context_cycle_int",
                               blender::wm::OpCallContext::InvokeDefault, "",
                               cx + side * half, cy, half, ch,
                               side == 0 ? "Decrease" : "Increase");
        if (but) {
          PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
          RNA_string_set(op_ptr, "data_path", data_path);
          RNA_boolean_set(op_ptr, "reverse", side == 0);
          RNA_boolean_set(op_ptr, "wrap", false);
        }
      }
    }
  }

  /* Prompt field over the prompt box. */
  if (prompt_ok) {
    /* The kit's top strip: ghost text top-left, caret at text height. */
    const rctf field = pane_prompt_field_rect(prompt_box, u);
    uiBut *input = uiDefButR(field_block, ButType::Text, 0, "",
                             int(field.xmin), int(field.ymin),
                             short(BLI_rctf_size_x(&field)),
                             short(BLI_rctf_size_y(&field)),
                             &tab_ptr, "prompt", -1, 0.0f, 0.0f, nullptr);
    if (input) {
      UI_but_placeholder_set(input, "Describe your scene here...");
      UI_but_flag2_enable(input, UI_BUT2_ACTIVATE_ON_INIT_NO_SELECT);
      UI_but_flag_enable(input, UI_BUT_TEXTEDIT_UPDATE);
    }
  }

  /* Field chrome on screen BEFORE the bottom row is painted (kit invariant:
   * the embossed field spans the whole box and covers earlier pixels). */
  UI_block_end(C, field_block);
  UI_block_draw(C, field_block);

  GPU_blend(GPU_BLEND_ALPHA);
  pane_action_chip_paint(upload, "Upload Reference", true, false, u);
  pane_action_chip_paint(capture, "Capture Viewport", false, false, u);
  /* Reference preview — REAL thumbnails of whatever this half will actually
   * SUBMIT (design: small previews, never a "N refs" count), the same way the
   * Agent tab previews its pending attachments.
   *
   * Image half: `use_reference_images` ON means the board selection is the
   * source and OFF means the tab's own uploads are (imagegen_ops.py reads it
   * exactly this way, and the uploader flips it off when it adds one).
   * Video half: Video Gen has no reference property of its own — its
   * references ARE the selected board media — so it always previews those. */
  {
    Image *ref_images[PANE_REF_THUMB_MAX] = {nullptr};
    int ref_count = 0;
    bool from_board = true;
    if (!video && tab_ok) {
      PropertyRNA *use_board = RNA_struct_find_property(&tab_ptr, "use_reference_images");
      if (use_board && RNA_property_type(use_board) == PROP_BOOLEAN) {
        from_board = RNA_property_boolean_get(&tab_ptr, use_board);
      }
    }
    if (from_board) {
      ref_count = pane_board_selected_images(C, ref_images, PANE_REF_THUMB_MAX);
    }
    else {
      PropertyRNA *refs = RNA_struct_find_property(&tab_ptr, "reference_images");
      if (refs && RNA_property_type(refs) == PROP_COLLECTION) {
        CollectionPropertyIterator iter;
        RNA_property_collection_begin(&tab_ptr, refs, &iter);
        for (; iter.valid && ref_count < PANE_REF_THUMB_MAX;
             RNA_property_collection_next(&iter))
        {
          PointerRNA item = iter.ptr;
          PropertyRNA *img_prop = RNA_struct_find_property(&item, "image");
          if (!img_prop || RNA_property_type(img_prop) != PROP_POINTER) {
            continue;
          }
          PointerRNA img = RNA_property_pointer_get(&item, img_prop);
          if (img.data) {
            ref_images[ref_count++] = static_cast<Image *>(img.data);
          }
        }
        RNA_property_collection_end(&iter);
      }
    }
    pane_ref_thumbs_paint(ref_images,
                          ref_count,
                          bx + PANE_REF_THUMB_GAP * u,
                          bottom_y,
                          bottom_h,
                          generate.xmin - PANE_CHIP_GAP * u,
                          u);
  }
  pane_generate_paint(generate, busy ? "Queued..." : "Generate", can_generate, u);
  GPU_blend(GPU_BLEND_NONE);

  /* Upload — per half: the image tab's own reference-collection uploader,
   * or the video flow's board-as-selected import. */
  uiDefButO(block, ButType::But,
            video ? "mixar.pane_video_upload_reference" : "mixie.imagegen_upload_reference",
            blender::wm::OpCallContext::InvokeDefault, "",
            int(upload.xmin), int(upload.ymin),
            short(BLI_rctf_size_x(&upload)), short(BLI_rctf_size_y(&upload)),
            video ? "Import selected reference stills for the video" :
                    "Add reference images from disk");

  /* Capture Viewport -> this tab's reference. */
  uiDefButO(block, ButType::But, "mixar.pane_capture_viewport",
            blender::wm::OpCallContext::InvokeDefault, "",
            int(capture.xmin), int(capture.ymin),
            short(BLI_rctf_size_x(&capture)), short(BLI_rctf_size_y(&capture)),
            "Screenshot the 3D viewport as a reference image");

  /* Generate goes through the SAME dispatcher Enter does
   * (`MIXIE_OT_moodboard_prompt_generate` -> `core/prompt_submit.py`), keyed
   * on the tab PropertyGroup's own RNA identifier — the string
   * interface_handlers.cc forwards. Hardcoding `mixie.imagegen_generate` here
   * made click and keypress submit DIFFERENT paid generations: the image
   * half's `depth_to_image` mode, which this pane's own dropdown exposes,
   * routes to `mixie.lookdev_generate`. */
  if (can_generate) {
    uiBut *but = uiDefButO(block, ButType::But, "mixie.moodboard_prompt_generate",
                           blender::wm::OpCallContext::InvokeDefault, "",
                           int(generate.xmin), int(generate.ymin),
                           short(BLI_rctf_size_x(&generate)),
                           short(BLI_rctf_size_y(&generate)),
                           video ? "Generate a video" : "Generate images");
    if (but) {
      PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "owner_type", RNA_struct_identifier(tab_ptr.type));
    }
  }

  UI_block_end(C, block);
  UI_block_draw(C, block);
}

/** \} */
