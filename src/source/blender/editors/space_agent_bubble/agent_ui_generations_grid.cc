/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Library — the tile grid itself: how many tiles fit, what each one
 * shows, and the drag that carries a 3D generation into the viewport.
 *
 * \section drag Dragging a generation into the viewport
 *
 * A 3D tile's button carries Blender's OWN asset drag
 * (#ui::button_drag_set_asset) plus #BUT_DRAG_FULL_BUT, so releasing it over a
 * 3D viewport runs the View3D's existing asset dropbox: the import method the
 * library is configured with, the undo push, the placement under the cursor —
 * all of it is Blender's, none of it re-implemented here. The full-button flag
 * is what lets a viewport-clipped tile start that drag from its visible strip.
 * That is only possible because
 * the generations already ARE assets in a registered library
 * (`asset_search/core/generation_library.py` archives them), which is why the
 * pane enumerates through `ED_asset_list.hh` rather than reading the folder
 * itself.
 *
 * Images and videos are deliberately NOT draggable: there is nothing sane to
 * drop a still into a 3D scene as, and a drag that silently does nothing is
 * worse than no drag. Their action lives in the detail column instead.
 */

#include "agent_ui_text.hh"

#include <algorithm>
#include <cstring>
#include <cmath>

#include "agent_ui_generations_clip.hh"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "DNA_ID.h"
#include "DNA_asset_types.h"
#include "DNA_screen_types.h"
#include "DNA_userdef_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "AS_asset_representation.hh"
#include "ED_asset.hh"

#include "agent_ui_generations_intern.hh"
#include "agent_ui_icons.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Grid geometry
 *
 * Column count comes from the resolved frame (at most the design's four).
 * A short island still shrinks the tile so the caption stays inside the
 * panel instead of being scissored off.
 * \{ */

GenGridMetrics agent_ui_generations_grid_metrics(const GenFrame &frame, const GenPaneData &data)
{
  GenGridMetrics m{};
  m.cols = std::max(1, frame.cols);
  m.x0 = frame.grid_x;
  m.y0 = frame.grid_top;
  m.bottom = frame.grid_bottom;

  const float avail = std::max(0.0f, m.y0 - m.bottom);
  const float font = frame.font_cap;
  const float caption = frame.cap_gap + 2.45f * font;
  m.tile = std::max(1.0f, std::min(frame.tile, avail - caption));
  m.pitch_x = m.tile + frame.tile_gap;
  m.pitch_y = m.tile + caption + frame.row_gap;
  const int total_rows = (data.count + m.cols - 1) / m.cols;
  const float content = total_rows * m.pitch_y - frame.row_gap;
  m.max_scroll = std::max(0.0f, content - avail);
  m.offset = std::clamp(data.scroll / 100.0f, 0.0f, 1.0f) * m.max_scroll;
  m.first_row = m.pitch_y > 0.0f ? int(m.offset / m.pitch_y) : 0;
  m.end_row = m.pitch_y > 0.0f ? std::min(total_rows, int(std::ceil((m.offset + avail) / m.pitch_y))) :
                                 total_rows;
  const float gutter = std::max(4.0f, frame.gap * 0.35f);
  m.view = {m.x0, frame.grid_right, m.bottom, m.y0};
  m.scrollbar = {frame.grid_right + gutter,
                 std::max(frame.grid_right + gutter + 6.0f, frame.detail_div_x - gutter),
                 m.bottom,
                 m.y0};
  return m;
}

namespace {

/** A dim glyph centred on the tile plate, for anything with no pixels. */
void draw_placeholder(const rctf &box, const AgentIcon icon)
{
  MIXAR_THEME_LOAD(col, TextSecondary);
  const float bg[4] = GEN_COL_TILE;
  const float s = std::min(BLI_rctf_size_x(&box), BLI_rctf_size_y(&box)) * 0.34f;
  rctf glyph;
  glyph.xmin = BLI_rctf_cent_x(&box) - s * 0.5f;
  glyph.xmax = glyph.xmin + s;
  glyph.ymin = BLI_rctf_cent_y(&box) - s * 0.5f;
  glyph.ymax = glyph.ymin + s;
  agent_ui_icon_draw(icon, &glyph, col, bg);
}

}  // namespace

bool agent_ui_generations_asset_has_preview(const bContext *C, const GenItem &item)
{
  if (item.kind != GEN_ITEM_ASSET || !item.asset) {
    return false;
  }
  /* Request visible previews explicitly: the native hit button has no icon,
   * so partial rows can be clipped without resizing their image. */
  item.asset->ensure_previewable(*C);
  ui::icon_ensure_deferred(C, blender::ed::asset::asset_preview_icon_id(*item.asset), true);
  const PreviewImage *prv = item.asset->get_preview();
  return prv && prv->rect[ICON_SIZE_PREVIEW] != nullptr;
}

void agent_ui_generations_thumb(const bContext *C,
                                const GenItem &item,
                                const rctf &box,
                                const float u)
{
  switch (item.kind) {
    case GEN_ITEM_ASSET: {
      if (!item.asset) {
        return;
      }
      if (agent_ui_generations_asset_has_preview(C, item)) {
        const BIFIconID icon = blender::ed::asset::asset_preview_icon_id(*item.asset);
        const float size = std::min(BLI_rctf_size_x(&box), BLI_rctf_size_y(&box));
        ui::icon_draw_preview(BLI_rctf_cent_x(&box) - size * 0.5f,
                              BLI_rctf_cent_y(&box) - size * 0.5f,
                              icon,
                              1.0f,
                              1.0f,
                              int(size));
        break;
      }
      /* No pixels YET — the deferred read is asynchronous, and a .blend with
       * no embedded preview at all never gets any. Either way the tile says
       * "3D asset" rather than drawing an empty plate. (The read itself does
       * reach a datablock preview inside the .blend: `full_path()` is the
       * exploded `<blend>/Object/<name>` form, which `IMB_thumb_manage`
       * splits and hands to `IMB_thumb_load_blend` — no file thumbnail on
       * disk is required.) */
      draw_placeholder(box, AGENT_ICON_MESH);
      break;
    }
    case GEN_ITEM_IMAGE:
    case GEN_ITEM_VIDEO:
      pane_image_thumb_draw(item.image, box);
      break;
    case GEN_ITEM_SPLAT:
      /* No preview exists for a splat world — what the viewport shows is
       * KIRI's GPU draw pass, not geometry. The tab strip's own splat mark
       * stands in for it. */
      draw_placeholder(box, AGENT_ICON_SPLAT);
      break;
    case GEN_ITEM_JOB:
      break;
  }
  UNUSED_VARS(u);
}

void agent_ui_generations_grid(const bContext *C,
                               ui::Block *block,
                               const rctf &panel,
                               const GenFrame &frame,
                               const GenPaneData &data,
                               const GenGridMetrics &grid,
                               rctf *r_selected_tile)
{
  BLI_rctf_init(r_selected_tile, 0.0f, 0.0f, 0.0f, 0.0f);

  MIXAR_THEME_LOAD(text, Text);
  MIXAR_THEME_LOAD(dim, TextSecondary);
  const float tile_bg[4] = GEN_COL_TILE;
  const float live[4] = GEN_COL_LIVE;
  const float font_chip = frame.font_chip;
  const float font_cap = frame.font_cap;
  const int cols = std::max(1, grid.cols);

  /* ---- Tiles ---- */
  const int first = grid.first_row * cols;
  const int last = std::min(data.count, grid.end_row * cols);
  const GenViewportClip clip(grid.view);

  if (data.count == 0) {
    const char *empty = data.loading ? "Loading assets…" :
                                       (data.source == GEN_SOURCE_LIBRARY ?
                                            "No assets in this library yet" :
                                            "Your generations will appear here");
    pane_label_centre(empty,
                      (frame.grid_x + frame.grid_right) * 0.5f,
                      (panel.ymin + panel.ymax) * 0.5f,
                      font_chip,
                      dim);
  }

  for (int i = first; i < last; i++) {
    const GenItem &item = data.items[i];
    const int slot = i - first;
    rctf tile;
    tile.xmin = grid.x0 + float(slot % cols) * grid.pitch_x;
    tile.xmax = tile.xmin + grid.tile;
    tile.ymax = grid.y0 + grid.offset - float(i / cols) * grid.pitch_y;
    tile.ymin = tile.ymax - grid.tile;

    pane_fill_round(&tile, std::min(GEN_TILE_RADIUS * frame.u, grid.tile * 0.18f), tile_bg);
    /* Paint full-size images under the viewport scissor, including partial rows. */
    agent_ui_generations_thumb(C, item, tile, frame.u);

    if (STREQ(item.key, data.selected)) {
      /* The caller paints the selection ring under the same viewport clip. */
      *r_selected_tile = tile;
    }

    /* Caption: type and age share the first line (both are short). The name
     * gets the whole tile on the second line, inset by padding, so the age
     * no longer truncates it. */
    const float inset = std::min(frame.cap_inset, grid.tile * 0.12f);
    const float text_w = std::max(1.0f, grid.tile - 2.0f * inset);
    const float cap1 = tile.ymin - frame.cap_gap - font_cap * 0.5f;
    const float cap2 = cap1 - font_cap * 1.35f;
    if (item.kind == GEN_ITEM_JOB) {
      pane_label_centre("GENERATING", BLI_rctf_cent_x(&tile), cap1, font_cap, live);
      char name[96];
      BLI_strncpy(name, item.name, sizeof(name));
      pane_fit_text(name, text_w, font_cap);
      pane_label_centre(name, BLI_rctf_cent_x(&tile), cap2, font_cap, dim);
    }
    else {
      const float age_w = item.age[0] ? pane_text_width(item.age, font_cap) : 0.0f;
      const float type_max = age_w > 0.0f ? text_w - age_w - frame.gap * 0.65f : text_w;
      char type_label[64];
      BLI_strncpy(type_label, item.type_label, sizeof(type_label));
      pane_fit_text(type_label, std::max(1.0f, type_max), font_cap);
      pane_label_left(type_label, tile.xmin + inset, cap1, font_cap, dim);
      if (item.age[0]) {
        pane_label_right(item.age, tile.xmax - inset, cap1, font_cap, dim);
      }

      char name[96];
      BLI_strncpy(name, item.name, sizeof(name));
      pane_fit_text(name, text_w, font_cap);
      pane_label_left(name, tile.xmin + inset, cap2, font_cap, text);
    }
  }

  for (int i = first; i < last; i++) {
    const GenItem &item = data.items[i];
    const int slot = i - first;
    rctf tile;
    tile.xmin = grid.x0 + float(slot % cols) * grid.pitch_x;
    tile.xmax = tile.xmin + grid.tile;
    tile.ymax = grid.y0 + grid.offset - float(i / cols) * grid.pitch_y;
    tile.ymin = tile.ymax - grid.tile;

    const char *tip = (item.kind == GEN_ITEM_ASSET) ?
                          "Click to inspect, or drag into the viewport" :
                          "Click to inspect";
    /* Keep Blender's PreviewTile event path for asset drag, but paint the
     * preview above: a clipped native button must not squeeze its image. */
    rctf hit;
    if (!BLI_rctf_isect(&tile, &grid.view, &hit) || BLI_rctf_size_y(&hit) < 1.0f) {
      continue;
    }

    ui::Button *but;
    if (item.kind == GEN_ITEM_ASSET) {
      but = uiDefIconPreviewBut(block,
                                ui::ButtonType::PreviewTile,
                                ICON_NONE,
                                int(hit.xmin),
                                int(hit.ymin),
                                short(BLI_rctf_size_x(&hit)),
                                short(BLI_rctf_size_y(&hit)),
                                nullptr,
                                0.0f,
                                0.0f,
                                tip);
      if (but) {
        if (wmOperatorType *ot = WM_operatortype_find("wm.context_set_string", true)) {
          ui::button_operator_set(but, ot, blender::wm::OpCallContext::InvokeDefault);
        }
      }
    }
    else {
      but = uiDefButO(block,
                      ui::ButtonType::But,
                      "wm.context_set_string",
                      blender::wm::OpCallContext::InvokeDefault,
                      "",
                      int(hit.xmin),
                      int(hit.ymin),
                      short(BLI_rctf_size_x(&hit)),
                      short(BLI_rctf_size_y(&hit)),
                      tip);
    }
    if (but) {
      pane_but_tooltip_owned(but, (std::string(item.name) + " — " + tip).c_str());
      PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "data_path", "window_manager.mixar_generations_selected");
      RNA_string_set(op_ptr, "value", item.key);
      ui::button_func_identity_compare_set(but, agent_ui_generations_button_identity);
    }
    if (but && item.kind == GEN_ITEM_ASSET && item.asset) {
      /* Blender's own asset drag: the View3D's existing asset dropbox does
       * the import, so a dropped generation behaves exactly as it would from
       * the asset browser. The import method is the library's, with the same
       * packing fallback the asset shelf applies. */
      eAssetImportMethod method = item.asset->get_import_method().value_or(ASSET_IMPORT_PACK);
      if (U.experimental.no_data_block_packing && method == ASSET_IMPORT_PACK) {
        method = ASSET_IMPORT_APPEND_REUSE;
      }
      AssetImportSettings import_settings{};
      import_settings.method = method;
      import_settings.use_instance_collections = false;
      ui::button_drag_set_asset(but,
                                item.asset,
                                import_settings,
                                ICON_NONE,
                                blender::ed::asset::asset_preview_icon_id(*item.asset));
      /* The drag payload does not mark the whole button draggable.
       * `but_contains_point_px_icon` then hit-tests a center square, so a
       * tile clipped by the grid (wider than it is tall) cannot start a
       * drag from the strip that is actually on screen. */
      ui::button_dragflag_enable(but, ui::BUT_DRAG_FULL_BUT);
    }
  }
  UNUSED_VARS(C);
}

}  // namespace blender
