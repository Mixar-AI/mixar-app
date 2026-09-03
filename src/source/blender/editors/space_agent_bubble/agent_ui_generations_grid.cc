/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * My Generations — the tile grid itself: how many tiles fit, what each one
 * shows, and the drag that carries a 3D generation into the viewport.
 *
 * \section drag Dragging a generation into the viewport
 *
 * A 3D tile's button carries Blender's OWN asset drag
 * (#ui::button_drag_set_asset), so releasing it over a 3D viewport runs the
 * View3D's existing asset dropbox: the import method the library is
 * configured with, the undo push, the placement under the cursor — all of it
 * is Blender's, none of it re-implemented here. That is only possible because
 * the generations already ARE assets in a registered library
 * (`asset_search/core/generation_library.py` archives them), which is why the
 * pane enumerates through `ED_asset_list.hh` rather than reading the folder
 * itself.
 *
 * Images and videos are deliberately NOT draggable: there is nothing sane to
 * drop a still into a 3D scene as, and a drag that silently does nothing is
 * worse than no drag. Their action lives in the detail column instead.
 */

#include <algorithm>
#include <cstring>

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
 * Column count is fixed at the design's four and never computed: the island
 * is a constant 1310 units wide whatever the window's pixel width (the unit
 * scale absorbs it), so the design's four columns always fit exactly. Only
 * the row count varies, with the island's height.
 * \{ */

GenGridMetrics agent_ui_generations_grid_metrics(const rctf &panel,
                                                 const float u,
                                                 const GenPaneData &data)
{
  GenGridMetrics m{};
  m.x0 = GEN_XL(panel, GEN_GRID_X, u);
  m.y0 = GEN_YTOP(panel, GEN_GRID_Y, u);
  m.bottom = panel.ymin + GEN_PAD * u;

  const float avail = std::max(0.0f, m.y0 - m.bottom);
  const float caption = GEN_CAP_BLOCK * u;
  m.tile = GEN_TILE * u;
  m.rows = int(avail / ((GEN_TILE + GEN_ROW_EXTRA) * u));
  if (m.rows < 1) {
    /* Not even one design-sized row fits. The tile shrinks to make room for
     * its caption rather than the caption being scissored off at the panel's
     * foot — which is what a forced full-size row produced at the island's
     * DEFAULT height, where the whole caption block hung outside the panel. */
    m.rows = 1;
    m.tile = std::clamp(avail - caption, GEN_TILE_MIN * u, GEN_TILE * u);
  }
  m.pitch_x = m.tile + GEN_TILE_GAP * u;
  m.pitch_y = m.tile + GEN_ROW_EXTRA * u;

  m.per_page = m.rows * GEN_COLS;
  m.pages = std::max(1, (data.count + m.per_page - 1) / m.per_page);
  m.page = std::clamp(data.page, 0, m.pages - 1);
  return m;
}

namespace {

/** A dim glyph centred on the tile plate, for anything with no pixels. */
void draw_placeholder(const rctf &box, const AgentIcon icon)
{
  const float col[4] = AGENT_COL_TEXT_DIM;
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
  /* Only ATTACHES the deferred read; what starts it is the icon id landing on
   * a ui::Button (`ui_def_but_icon` -> `ui_icon_ensure_deferred`), which is why an
   * asset tile is a preview BUTTON rather than a painted plate. */
  item.asset->ensure_previewable(*C);
  const PreviewImage *prv = item.asset->get_preview();
  return prv && prv->rect[ICON_SIZE_PREVIEW] != nullptr;
}

void agent_ui_generations_thumb(const bContext *C, const GenItem &item, const rctf &box, const float u)
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
                               const float u,
                               const GenPaneData &data,
                               const GenGridMetrics &grid,
                               rctf *r_selected_tile)
{
  BLI_rctf_init(r_selected_tile, 0.0f, 0.0f, 0.0f, 0.0f);

  const float text[4] = AGENT_COL_TEXT;
  const float dim[4] = AGENT_COL_TEXT_DIM;
  const float tile_bg[4] = GEN_COL_TILE;
  const float accent[4] = AGENT_COL_ACCENT;
  const float live[4] = GEN_COL_LIVE;
  const float font_chip = GEN_CHIP_FONT * u;
  const float font_cap = GEN_CAP_FONT * u;

  /* ---- Tiles ---- */
  const int first = grid.page * grid.per_page;
  const int last = std::min(data.count, first + grid.per_page);

  if (data.count == 0) {
    const char *empty = data.loading ? "Loading assets…" :
                        (data.source == GEN_SOURCE_LIBRARY ?
                             "No assets in this library yet" :
                             "Your generations will appear here");
    pane_label_centre(empty,
                      (GEN_XL(panel, GEN_GRID_X, u) + GEN_XL(panel, GEN_DETAIL_DIVIDER_X, u)) *
                          0.5f,
                      (panel.ymin + panel.ymax) * 0.5f,
                      font_chip,
                      dim);
  }

  for (int i = first; i < last; i++) {
    const GenItem &item = data.items[i];
    const int slot = i - first;
    rctf tile;
    tile.xmin = grid.x0 + float(slot % GEN_COLS) * grid.pitch_x;
    tile.xmax = tile.xmin + grid.tile;
    tile.ymax = grid.y0 - float(slot / GEN_COLS) * grid.pitch_y;
    tile.ymin = tile.ymax - grid.tile;

    pane_fill_round(&tile, GEN_TILE_RADIUS * u, tile_bg);
    /* This pass is also what REQUESTS an asset preview (see the thumb
     * helper), so it must run for every kind. A loaded preview is drawn here
     * and NOT by the button — the button carries the icon so Blender keeps
     * the deferred read alive, and drawing it twice is harmless overdraw we
     * avoid by leaving the button's own draw to cover the same pixels. */
    agent_ui_generations_thumb(C, item, tile, u);

    if (STREQ(item.key, data.selected)) {
      /* The ring is handed back rather than drawn: the block paints AFTER
       * this pass, and an asset tile's preview would cover the inner half of
       * a ring drawn now, so the caller re-draws it once the block is down. */
      *r_selected_tile = tile;
    }

    /* Caption: type over name on the left, age right-aligned on line two. */
    const float cap1 = tile.ymin - GEN_CAP_GAP * u - font_cap * 0.5f;
    const float cap2 = cap1 - GEN_CAP_PITCH * u;
    if (item.kind == GEN_ITEM_JOB) {
      pane_label_centre("GENERATING", BLI_rctf_cent_x(&tile), cap1, font_cap, live);
      char name[96];
      BLI_strncpy(name, item.name, sizeof(name));
      pane_fit_text(name, grid.tile, font_cap);
      pane_label_centre(name, BLI_rctf_cent_x(&tile), cap2, font_cap, dim);
    }
    else {
      char type_label[64];
      BLI_strncpy(type_label, item.type_label, sizeof(type_label));
      pane_fit_text(type_label, grid.tile, font_cap);
      pane_label_left(type_label, tile.xmin, cap1, font_cap, dim);

      const float age_w = item.age[0] ? pane_text_width(item.age, font_cap) + 8.0f * u : 0.0f;
      char name[96];
      BLI_strncpy(name, item.name, sizeof(name));
      pane_fit_text(name, grid.tile - age_w, font_cap);
      pane_label_left(name, tile.xmin, cap2, font_cap, text);
      if (item.age[0]) {
        pane_label_right(item.age, tile.xmax, cap2, font_cap, dim);
      }
    }
  }

  /* No bottom fade. The design draws one to say "there is more below", but
   * this grid PAGES rather than scrolls — nothing is ever half-visible under
   * it, and over a single visible row the gradient simply swallowed the
   * captions. The page chips carry that meaning instead.
   */

  for (int i = first; i < last; i++) {
    const GenItem &item = data.items[i];
    const int slot = i - first;
    rctf tile;
    tile.xmin = grid.x0 + float(slot % GEN_COLS) * grid.pitch_x;
    tile.xmax = tile.xmin + grid.tile;
    tile.ymax = grid.y0 - float(slot / GEN_COLS) * grid.pitch_y;
    tile.ymin = tile.ymax - grid.tile;

    const char *tip = (item.kind == GEN_ITEM_ASSET) ?
                          "Click to inspect, or drag into the viewport" :
                          "Click to inspect";
    /* An asset tile is a ui::ButtonType::PreviewTile, and that type is load-bearing
     * rather than cosmetic: Blender's drag-start lives in `ui_do_but_EXIT`,
     * and only the preview-tile/label family routes there. A ui::ButtonType::But
     * goes to `ui_do_but_BUT`, which handles the click and NEVER checks
     * `button_drag_is_draggable` — so the drag data attached below was
     * present and simply unreachable, and the tile clicked but would not
     * drag. The operator is attached afterwards, the way the asset shelf
     * does it, so a click still runs it.
     *
     * The preview icon id is passed UNCONDITIONALLY, not once the thumbnail
     * has pixels. Attaching it to a button is what STARTS the deferred read
     * (`ui_def_but_icon` -> `ui_icon_ensure_deferred`) — the asset shelf says
     * so in as many words — so gating it on pixels was a deadlock: no icon,
     * therefore no read, therefore no pixels, therefore no icon. Every
     * archived generation drew the placeholder cube forever while Blender's
     * own Asset Browser showed the same file's thumbnail fine.
     *
     * `ensure_previewable` only ALLOCATES the preview and attaches the load
     * info; the id it mints is valid immediately and resolves to nothing
     * until the read lands, so an unloaded tile still shows our placeholder
     * through the button. */
    BIFIconID preview = BIFIconID(ICON_NONE);
    if (item.kind == GEN_ITEM_ASSET && item.asset) {
      item.asset->ensure_previewable(*C);
      preview = blender::ed::asset::asset_preview_icon_id(*item.asset);
    }

    ui::Button *but;
    if (item.kind == GEN_ITEM_ASSET) {
      but = uiDefIconPreviewBut(block, ui::ButtonType::PreviewTile, preview,
                                int(tile.xmin), int(tile.ymin),
                                short(BLI_rctf_size_x(&tile)),
                                short(BLI_rctf_size_y(&tile)),
                                nullptr, 0.0f, 0.0f, tip);
      if (but) {
        if (wmOperatorType *ot = WM_operatortype_find("wm.context_set_string", true)) {
          ui::button_operator_set(but, ot, blender::wm::OpCallContext::InvokeDefault);
        }
      }
    }
    else {
      but = uiDefButO(block, ui::ButtonType::But, "wm.context_set_string",
                      blender::wm::OpCallContext::InvokeDefault, "",
                      int(tile.xmin), int(tile.ymin), short(BLI_rctf_size_x(&tile)),
                      short(BLI_rctf_size_y(&tile)), tip);
    }
    if (but) {
      PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "data_path", "window_manager.mixar_generations_selected");
      RNA_string_set(op_ptr, "value", item.key);
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
    }
  }
  UNUSED_VARS(C);
}

}  // namespace blender
