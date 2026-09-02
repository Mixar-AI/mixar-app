/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Private vocabulary of the My Generations pane: its measured tokens, the one
 * item model every source is normalised into, and the split between the
 * gathering pass (`agent_ui_generations_data.cc`), the grid pass
 * (`agent_ui_generations.cc`) and the detail column
 * (`agent_ui_generations_detail.cc`).
 *
 * \section units Tokens
 *
 * Every number is measured from `generations.svg` and quoted PANEL-RELATIVE
 * in artboard units — the panel's top-left is (0,0), y grows DOWNWARD. The
 * painter converts with #GEN_YTOP once per rect, so nothing else has to think
 * about the flip. The panel rect itself comes from the island layout, so a
 * taller window grows the grid rather than moving the design off its grid.
 */

#pragma once

#include "BLI_rect.h"

#include "agent_ui_pane_kit.hh"

struct ARegion;
struct Image;
struct PointerRNA;
struct bContext;
struct uiBlock;

namespace blender::asset_system {
class AssetRepresentation;
}

/* -------------------------------------------------------------------- */
/** \name Tokens (panel-relative artboard units; y downward)
 * \{ */

/* Left rail — the source switch. */
#define GEN_PAD 18            /* Panel edge -> rail pill / first content. */
#define GEN_RAIL_W 198
#define GEN_RAIL_H 47
#define GEN_RAIL_RADIUS 23    /* Design 23.5; the half-unit is sub-pixel. */
#define GEN_RAIL_Y 23
#define GEN_RAIL_PITCH 61
#define GEN_RAIL_DOT_X 18     /* Pill left -> active bullet centre. */
#define GEN_RAIL_DOT_R 3
#define GEN_RAIL_LABEL_X 28   /* Pill left -> label ink. */

/* Library rows under the rail (Asset Library source only — the design leaves
 * this column empty, and "connect a library" is what it is for). */
#define GEN_LIB_ROW_H 38
#define GEN_LIB_ROW_PITCH 42
#define GEN_LIB_ROWS_Y 158    /* First row top, clear of the two source pills. */
#define GEN_LIB_FONT 16

/* Column dividers — hairlines, not chrome. */
#define GEN_DIVIDER_X 244
#define GEN_DETAIL_DIVIDER_X 944
#define GEN_DIVIDER_INSET 8   /* Panel top/bottom -> divider ends. */

/* Filter chip row. */
#define GEN_GRID_X 257
#define GEN_CHIP_Y 23
#define GEN_CHIP_H 47
#define GEN_CHIP_RADIUS 15
#define GEN_CHIP_PAD_X 20
#define GEN_CHIP_GAP 4
#define GEN_CHIP_FONT 18
#define GEN_SORT_W 56         /* Right-aligned to the grid's own right edge. */
#define GEN_TAB_GLYPH 24      /* Glyph box inside a chip — the tab-strip size. */

/* Paging. NOT in the design — the design's panel shows one row and says
 * nothing about the rest. The island's height is the user's, and at the
 * default height barely one row fits, so the grid pages rather than silently
 * hiding everything past the first four. Two compact chips sit in the empty
 * span the design leaves between the filter chips and the sort chip, and they
 * appear only when there IS another page. */
#define GEN_PAGE_W 34
#define GEN_PAGE_GAP 6

/* Tile grid. */
#define GEN_TILE 146
#define GEN_TILE_GAP 24       /* Design pitch 170.5 - the 146 tile. */
#define GEN_TILE_MIN 84       /* Floor when the island is too short for 146. */
#define GEN_GRID_RIGHT 914    /* Design right edge of column 4 — the sort chip
                               * right-aligns to THIS, not to the live grid, so
                               * it keeps its place when tiles shrink. */
#define GEN_TILE_RADIUS 15
#define GEN_GRID_Y 120
#define GEN_SEL_BORDER 3
#define GEN_CAP_GAP 10        /* Tile bottom -> caption line 1 top. */
#define GEN_CAP_FONT 16
#define GEN_CAP_PITCH 19
#define GEN_CAP_BLOCK 48      /* Tile bottom -> bottom of caption line two. */
#define GEN_ROW_GAP 20
#define GEN_ROW_EXTRA (GEN_CAP_BLOCK + GEN_ROW_GAP)

/* Detail column. */
#define GEN_DETAIL_X 970
#define GEN_DETAIL_W 315
#define GEN_TITLE_Y 14
#define GEN_TITLE_FONT 26
#define GEN_PREVIEW_Y 54
#define GEN_PREVIEW_W 316
#define GEN_PREVIEW_H 172
#define GEN_META_H 26
#define GEN_META_RADIUS 7
#define GEN_META_GAP 4         /* Between chips on a row. */
#define GEN_META_ROW_GAP 5     /* Between the two chip rows. */
#define GEN_META_FONT 15
#define GEN_META_PAD_X 12
#define GEN_DESC_FONT 17
#define GEN_DESC_PITCH 21
#define GEN_ACTION_W 153
#define GEN_ACTION_H 26
#define GEN_ACTION_GAP 9
#define GEN_ACTION_FONT 15

/* The detail column is laid out from the PANEL'S FOOT upward, not from its
 * top down. The design's y offsets (meta 242/273, prompt 310, actions 353)
 * are measured on a 407-unit panel, and the island at its default height
 * gives the pane barely 300 — read as fixed offsets they put both action
 * buttons past the panel's bottom edge, where they are simply scissored off.
 * So the block below is anchored to the foot with the design's own GAPS, and
 * the preview above it absorbs whatever height is left. */
#define GEN_DETAIL_FOOT 28     /* Panel bottom -> action row bottom. */
#define GEN_DETAIL_GAP 14      /* Between the stacked blocks. */
#define GEN_PREVIEW_MIN 40     /* Below this the preview is dropped entirely. */

/* Palette (alpha ALWAYS stated — a three-value initialiser draws invisible). */
#define GEN_COL_PILL_ON PANE_COL_CHIP                        /* #313131 */
#define GEN_COL_PILL_OFF {0.192f, 0.192f, 0.192f, 0.36f}     /* #313131 @0.36 */
#define GEN_COL_CHIP_OFF {0.129f, 0.129f, 0.129f, 1.0f}      /* Recessed chip. */
#define GEN_COL_DIVIDER {0.169f, 0.169f, 0.169f, 1.0f}       /* #2B2B2B hairline. */
#define GEN_COL_TILE {0.129f, 0.129f, 0.129f, 1.0f}          /* Empty tile plate. */
#define GEN_COL_META {0.333f, 0.333f, 0.333f, 0.28f}         /* #555555 @0.28 */
#define GEN_COL_SECONDARY {0.596f, 0.596f, 0.596f, 1.0f}     /* #989898 */
#define GEN_COL_LIVE {0.173f, 0.659f, 0.361f, 1.0f}          /* "GENERATING" green. */

/** Panel-relative design unit -> region y (the one place the flip happens). */
#define GEN_YTOP(panel, v, u) ((panel).ymax - float(v) * (u))
/** Panel-relative design unit -> region x. */
#define GEN_XL(panel, v, u) ((panel).xmin + float(v) * (u))

/** \} */

/* -------------------------------------------------------------------- */
/** \name Item model
 *
 * Four very different things share one grid, so they share one struct. The
 * payload union is deliberately NOT a union: an asset item wants its blend
 * path as well as its representation, and the struct is short-lived (one
 * draw's stack array), so clarity beats the bytes.
 * \{ */

enum GenItemKind {
  GEN_ITEM_ASSET = 0, /* An asset in a registered library — draggable. */
  GEN_ITEM_IMAGE,     /* A generated still on the scene's moodboard. */
  GEN_ITEM_VIDEO,     /* A generated movie on the scene's moodboard. */
  GEN_ITEM_SPLAT,     /* A Gaussian-splat world present in this file. */
  GEN_ITEM_JOB,       /* Still generating — the queue's own row. */
};

/** Which chip is filtering the grid. Persisted by identifier, never index. */
enum GenFilter {
  GEN_FILTER_ALL = 0,
  GEN_FILTER_3D,
  GEN_FILTER_IMAGE,
  GEN_FILTER_VIDEO,
  GEN_FILTER_SPLAT,
  GEN_FILTER_COUNT,
};

enum GenSource {
  GEN_SOURCE_AI = 0,
  GEN_SOURCE_LIBRARY,
};

struct GenItem {
  GenItemKind kind;
  /** Stable identity for selection — survives a refilter and a re-gather. */
  char key[128];
  char name[96];
  char type_label[64];
  char model_label[64];
  char age[32];
  char detail[256];
  /** Newer sorts first by default. Unix seconds; 0 when genuinely unknown. */
  double sort_time;

  /* Payloads. Exactly one is set; the others stay null/empty.
   * The asset is non-const because drawing a tile has to call its
   * `ensure_previewable()` — that request IS how an external asset's preview
   * ever loads, and only the tiles actually on screen should ask. */
  blender::asset_system::AssetRepresentation *asset;
  Image *image;
  char path[1024]; /* Containing .blend (asset) or media file (image/video). */
  /** For an asset: the ID-type folder inside that .blend ("Object",
   * "Collection", …), which is what `wm.append` addresses a datablock by. */
  char id_dir[32];
};

#define GEN_MAX_ITEMS 240

/** The auto-archive library's name — must match
 * `asset_search/constants.py:GENERATION_LIBRARY_NAME`. */
#define GENERATIONS_LIBRARY_NAME "Mixar Generations"

/** Everything the pane needs, gathered once per draw before painting. */
struct GenPaneData {
  GenItem items[GEN_MAX_ITEMS];
  int count;

  GenSource source;
  GenFilter filter;
  bool newest_first;
  /** Selected item's key; empty when nothing is selected. */
  char selected[128];
  /** Asset-library rail: the library name being browsed ("" = all of them). */
  char library[64];
  /** Zero-based grid page. Clamped by the painter, which is the only place
   * that knows how many rows the current island height can show. */
  int page;
  /** True while an asset list is still reading — the grid says so. */
  bool loading;

  /** Registered asset libraries, for the rail's connect list. */
  char lib_names[16][64];
  int lib_count;
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Grid geometry (agent_ui_generations_grid.cc)
 *
 * The column count is FIXED at the design's four and never computed: the
 * island is a constant 1310 units wide whatever the window's pixel width (the
 * unit scale absorbs it), so the design's four columns always fit exactly.
 * Only the row count varies, with the island's height — and at the island's
 * default height that is one row, which is why the grid pages.
 * \{ */

#define GEN_COLS 4

struct GenGridMetrics {
  float tile;   /* Tile edge, in region pixels — shrinks below the design's
                 * 146 when the island is too short to fit a full row plus its
                 * caption, because a caption drawn past the panel's foot is
                 * simply scissored away. */
  float pitch_x;
  float pitch_y;
  float x0;     /* Left edge of column 0. */
  float y0;     /* TOP edge of row 0. */
  float bottom; /* Lowest y a caption may reach. */
  int rows;
  int per_page;
  int pages;
  int page;     /* The requested page, clamped into range. */
};

GenGridMetrics agent_ui_generations_grid_metrics(const rctf &panel,
                                                 float u,
                                                 const GenPaneData &data);

/**
 * Paint the tiles for the current page and lay their buttons into \a block.
 *
 * \a r_selected_tile receives the selected tile's rect, or an empty rect when
 * nothing on this page is selected. The selection ring is the CALLER's to
 * draw, after the block: an asset tile is a preview uiBut, and the block
 * paints last, so a ring drawn during this pass loses its inner half.
 */
void agent_ui_generations_grid(const bContext *C,
                               uiBlock *block,
                               const rctf &panel,
                               float u,
                               const GenPaneData &data,
                               const GenGridMetrics &grid,
                               rctf *r_selected_tile);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Readers (agent_ui_generations_read.cc)
 *
 * Shared by every source. The string getter is deliberately not the bare
 * #RNA_property_string_get — that one is strcpy-shaped and a value longer
 * than the buffer overflows it.
 * \{ */

void gen_read_string(PointerRNA *ptr, const char *name, char *out, int out_maxncpy);
float gen_read_float(PointerRNA *ptr, const char *name);
/** The enum's stable IDENTIFIER, never its index — an index repoints the
 * moment an item is inserted. */
void gen_read_enum_id(PointerRNA *ptr, const char *name, char *out, int out_maxncpy);

/** Unix seconds for an ISO-8601 stamp, or 0 when it does not parse. */
double gen_epoch_from_iso(const char *iso);
/** "4d ago", the design's caption. Empty for an unknown time. */
void gen_format_age(double epoch, char r_out[32]);
/** Modification time of a .blend, memoised — the island repaints on every
 * mouse move, and a library of hundreds would otherwise be hundreds of
 * syscalls a frame. */
double gen_blend_mtime(const char *path);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Passes
 * \{ */

/** Read the WM state and fill \a r_data with the filtered, sorted items. */
void agent_ui_generations_gather(const bContext *C, GenPaneData *r_data);

/** Index of #GenPaneData::selected within the gathered items, or -1. */
int agent_ui_generations_selected_index(const GenPaneData &data);

/** Paint + lay out the detail column. \a block is the pane's own uiBlock. */
void agent_ui_generations_detail(const bContext *C,
                                 uiBlock *block,
                                 const rctf &panel,
                                 float u,
                                 const GenPaneData &data);

/**
 * Does this asset have preview PIXELS right now?
 *
 * Answers only "is it loaded" — it does NOT decide whether the tile gets a
 * preview icon id. It used to, and that was a deadlock: attaching the id to
 * the button is what starts the deferred read, so withholding it until the
 * pixels arrived meant they never did. The id is now passed unconditionally
 * (see `agent_ui_generations_grid`), and this is just the gate for painting
 * our own placeholder underneath while the read is still in flight.
 *
 * Requests the preview as a side effect, so it must only be called for tiles
 * actually being drawn.
 */
bool agent_ui_generations_asset_has_preview(const GenItem &item);

/** Aspect-fit an item's preview inside \a box. Assets go through Blender's
 * icon system (which is what loads an external asset's preview at all);
 * moodboard media go through the pane kit's ImBuf path. */
void agent_ui_generations_thumb(const GenItem &item, const rctf &box, float u);

/** \} */
