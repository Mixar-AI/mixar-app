/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The name of a selected standalone image or movie, painted above it.
 *
 * Split out of #mixie_draw_moodboard_node_ui.cc (500-line rule); drawn in the
 * same screen-space pass as the node controls' icon blits, so the name stays
 * legible at every zoom.
 *
 * This replaced a rounded "Image"/"Video" bubble that hovered over the
 * selection: a card-sized chrome element that covered part of the canvas to
 * repeat what the picture already showed. What the user cannot read off the
 * tile is WHICH file it is, so the media's own name takes that slot, painted
 * as plain small text with no background of its own.
 *
 * The name is LEFT-ALIGNED to its tile's left edge, not centred. Centring put
 * the text over whatever sat to the tile's upper right -- with two overlapping
 * images that is the neighbour, so the selected image's name was painted
 * across the OTHER picture and read as that one's name. An edge the label
 * shares with its tile is what ties the two together.
 *
 * Media are painted in collection order, so a later entry covers an earlier
 * one. When a neighbour drawn on top would sit under the label's strip, the
 * name drops INSIDE its own tile (top-left, with an outline for contrast)
 * rather than floating over a picture it does not name.
 */

#include "mixie_draw_moodboard_intern.hh"

#include "BLI_string.h"
#include "BLI_string_utf8.h"
#include "BLI_vector.hh"

#include "UI_resources.hh" /* UI_GetThemeColor4fv */

#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

namespace blender::ed::mixie {

/* A name longer than this folds in the MIDDLE. Never at the end: a generated
 * name is distinguished by its tail and its extension as much as its head. */
#define MOODBOARD_MEDIA_LABEL_MAX_CHARS 20
#define MOODBOARD_MEDIA_LABEL_HEAD_CHARS 10
#define MOODBOARD_MEDIA_LABEL_TAIL_CHARS 9

/* Point size at zoom 1, before the DPI factor. The name is sized WITH the
 * canvas: a tile drawn half as wide carries a name half as tall, so the two
 * keep their proportion at every zoom. Pinning it to a constant screen size
 * meant a zoomed-out tile 111px wide wore a 126px name -- text visibly wider
 * than the picture it labelled. */
#define MOODBOARD_MEDIA_LABEL_SIZE_PX 11.0f
/* Ceiling, so a deep zoom on a large image cannot mint absurd glyphs. */
#define MOODBOARD_MEDIA_LABEL_MAX_PX 28.0f
/* Legibility floor, used twice. The zoom-derived size is clamped UP to it, so
 * a name does not evaporate the moment the canvas is pulled back -- a 160px
 * tile is still a picture the user can see and wants identified. Then, if
 * fitting the name to that tile forces it back under the floor, the tile is
 * genuinely too narrow to carry a readable name and it is dropped instead.
 * This replaces the old fixed MIN_TILE_PX gate: with the size following the
 * tile, "too small to read" and "too small to label" are one condition. */
#define MOODBOARD_MEDIA_LABEL_MIN_PX 7.0f

/* Spacing is expressed against the FONT, not in fixed pixels, so the whole
 * label lockup scales as one piece. Ratios reproduce the previous 8px gap and
 * 6px inset at the 11px base size. */
#define MOODBOARD_MEDIA_LABEL_GAP_RATIO 0.73f
#define MOODBOARD_MEDIA_LABEL_INSET_RATIO 0.55f

/* How many line-height bands to probe down a covered tile before giving up and
 * taking the top-left. Bounded so a very tall tile cannot make the search cost
 * grow without limit on every redraw. */
#define MOODBOARD_MEDIA_LABEL_MAX_PROBES 24

/* One standalone media tile, in collection (= paint) order. */
struct MediaLabelTile {
  Image *image;
  rcti region_rect;
  bool selected;
};

static void moodboard_media_label_text(const char *name, char *out, const size_t out_size)
{
  size_t byte_length = 0;
  const size_t char_length = BLI_strlen_utf8_ex(name, &byte_length);
  if (char_length <= MOODBOARD_MEDIA_LABEL_MAX_CHARS) {
    BLI_strncpy_utf8(out, name, out_size);
    return;
  }
  /* Offsets come from the UTF-8 helpers rather than raw byte counts, so a
   * multi-byte character is never cut in half into a replacement glyph. */
  const int head_bytes = BLI_str_utf8_offset_from_index(
      name, byte_length, MOODBOARD_MEDIA_LABEL_HEAD_CHARS);
  const int tail_bytes = BLI_str_utf8_offset_from_index(
      name, byte_length, int(char_length) - MOODBOARD_MEDIA_LABEL_TAIL_CHARS);
  char head[MOODBOARD_MEDIA_LABEL_MAX_CHARS * 4 + 1];
  BLI_strncpy(head, name, std::min(size_t(head_bytes) + 1, sizeof(head)));
  BLI_snprintf(out, out_size, "%s...%s", head, name + tail_bytes);
}

/* Region rect of one media entry, from the shared per-frame cache. Only media
 * that somehow missed the id migration (and so is absent from the cache) falls
 * back to deriving the aspect from a freshly acquired ImBuf. */
static bool moodboard_media_label_rect(View2D *v2d,
                                       ARegion *region,
                                       PointerRNA *media,
                                       Image *image,
                                       const MoodboardGraphCache *cache,
                                       rcti *r_rect)
{
  char media_id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(media, "node_id", media_id, sizeof(media_id));
  const rctf *cached_rect = (cache && media_id[0]) ? cache->outputs.lookup_ptr(media_id) : nullptr;
  rctf media_rect;
  if (cached_rect) {
    media_rect = *cached_rect;
  }
  else {
    float aspect = 1.0f;
    void *lock = nullptr;
    ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
    if (ibuf && ibuf->x > 0) {
      aspect = float(ibuf->y) / float(ibuf->x);
    }
    BKE_image_release_ibuf(image, ibuf, lock);
    const float width = MOODBOARD_IMAGE_BASE_SIZE * RNA_float_get(media, "scale");
    media_rect.xmin = RNA_float_get(media, "position_x");
    media_rect.ymin = RNA_float_get(media, "position_y");
    media_rect.xmax = media_rect.xmin + width;
    media_rect.ymax = media_rect.ymin + width * aspect;
  }
  return moodboard_view_rect_to_region(v2d, region, media_rect, r_rect);
}

void mixie_draw_moodboard_selected_media_labels(View2D *v2d,
                                                ARegion *region,
                                                PointerRNA *scene_ptr,
                                                const MoodboardGraphCache *cache)
{
  PropertyRNA *images = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (!images) {
    return;
  }

  /* Nothing selected is the common case and this runs on every redraw, so
   * settle it with a bool read per entry before resolving any geometry. */
  bool any_selected = false;
  CollectionPropertyIterator scan{};
  RNA_property_collection_begin(scene_ptr, images, &scan);
  while (scan.valid && !any_selected) {
    any_selected = RNA_boolean_get(&scan.ptr, "selected");
    RNA_property_collection_next(&scan);
  }
  RNA_property_collection_end(&scan);
  if (!any_selected) {
    return;
  }

  /* Collect first, paint second. A label's placement depends on the tiles
   * painted AFTER its own -- those are the ones drawn over it -- which a single
   * forward pass cannot know yet. */
  blender::Vector<MediaLabelTile> tiles;
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, images, &iter);
  while (iter.valid) {
    PointerRNA media = iter.ptr;
    PointerRNA image_ptr = RNA_pointer_get(&media, "image");
    Image *image = static_cast<Image *>(image_ptr.data);
    PropertyRNA *embedded = RNA_struct_find_property(&media, "embedded_node_id");
    /* Node-owned media is drawn as its node's preview, never as a loose tile. */
    const bool standalone = !embedded || RNA_property_string_length(&media, embedded) == 0;
    rcti media_region;
    if (image && standalone &&
        moodboard_media_label_rect(v2d, region, &media, image, cache, &media_region))
    {
      tiles.append({image, media_region, RNA_boolean_get(&media, "selected")});
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);

  const int font_id = BLF_default();
  /* Region pixels per canvas unit: 1.0 at zoom 1, so the base size below is
   * exactly what it has always been there. */
  const float view_scale = std::max(UI_view2d_scale_get_x(v2d), 0.001f);
  float shadow_color[4];
  UI_GetThemeColor4fv(TH_BACK, shadow_color);

  for (const int index : tiles.index_range()) {
    const MediaLabelTile &tile = tiles[index];
    if (!tile.selected) {
      continue;
    }
    char label[MOODBOARD_MEDIA_LABEL_MAX_CHARS * 4 + 8];
    moodboard_media_label_text(tile.image->id.name + 2, label, sizeof(label));
    const size_t label_length = strlen(label);

    float font_px = std::clamp(MOODBOARD_MEDIA_LABEL_SIZE_PX * UI_SCALE_FAC * view_scale,
                               MOODBOARD_MEDIA_LABEL_MIN_PX * UI_SCALE_FAC,
                               MOODBOARD_MEDIA_LABEL_MAX_PX * UI_SCALE_FAC);
    BLF_size(font_id, font_px);
    float text_width = BLF_width(font_id, label, label_length);

    /* A name is never wider than the picture it names. Zoom alone does not
     * guarantee that: the tile's width is its own canvas size TIMES the zoom,
     * so a user-shrunk image at a high zoom would still wear an oversized
     * name. Glyph advance is linear in the point size, so one correction step
     * lands it. */
    const float tile_width = float(BLI_rcti_size_x(&tile.region_rect));
    if (text_width > tile_width && text_width > 0.0f) {
      font_px *= tile_width / text_width;
      BLF_size(font_id, font_px);
      text_width = BLF_width(font_id, label, label_length);
    }
    /* Only reachable via the fit above: the tile is too narrow to carry a
     * readable name, so it carries none. */
    if (font_px < MOODBOARD_MEDIA_LABEL_MIN_PX * UI_SCALE_FAC) {
      continue;
    }

    const float line_height = float(BLF_height_max(font_id));
    const float gap = font_px * MOODBOARD_MEDIA_LABEL_GAP_RATIO;
    const float inset = font_px * MOODBOARD_MEDIA_LABEL_INSET_RATIO;

    /* Is the strip at (x, y) clear of every picture that is VISIBLE there?
     *
     * Which neighbours count depends on where the strip is. Above the tile the
     * name is out in the open, so any neighbour reaching into that band shows
     * through and counts -- painted before this tile or after. Inside the tile
     * only the neighbours painted AFTER it can cover it; the earlier ones are
     * underneath this very picture. */
    auto strip_is_clear = [&](const float x, const float y, const bool inside) {
      rcti strip;
      BLI_rcti_init(&strip, int(x), int(x + text_width), int(y), int(y + line_height));
      for (const int other : tiles.index_range()) {
        if (other == index || (inside && other < index)) {
          continue;
        }
        if (BLI_rcti_isect(&strip, &tiles[other].region_rect, nullptr)) {
          return false;
        }
      }
      return true;
    };

    /* Left-aligned to the tile's own left edge: the shared edge is what reads
     * as "this name belongs to that picture". */
    float text_x = float(tile.region_rect.xmin);
    float text_y = float(tile.region_rect.ymax) + gap;
    const bool inside = !strip_is_clear(text_x, text_y, false);
    if (inside) {
      /* The float above is taken, so the name moves inside its own picture --
       * but NOT blindly to the top-left: a neighbour that covers the strip
       * above this tile usually overlaps the top of the tile as well, which is
       * exactly how the name ended up drawn across the other picture anyway.
       * Walk down a line at a time and take the first band this tile actually
       * shows. */
      text_x = float(tile.region_rect.xmin) + inset;
      const float top = float(tile.region_rect.ymax) - inset - line_height;
      const float bottom = float(tile.region_rect.ymin) + inset;
      text_y = top;
      for (int step = 0; step < MOODBOARD_MEDIA_LABEL_MAX_PROBES; step++) {
        const float candidate = top - float(step) * line_height;
        if (candidate < bottom) {
          break;
        }
        if (strip_is_clear(text_x, candidate, true)) {
          text_y = candidate;
          break;
        }
      }
      /* Every band covered (a neighbour blankets this tile) keeps the top-left
       * fallback: the name still has to be somewhere, and its own tile is the
       * least wrong place for it. */
      BLF_enable(font_id, BLF_SHADOW);
      BLF_shadow_offset(font_id, 0, 0);
      BLF_shadow(font_id, FontShadowType::Outline, shadow_color);
    }

    /* Pushed back inside the region when the anchor is off screen -- a name
     * drawn outside the region is a name the user selected the media to read
     * and cannot. */
    text_x = std::clamp(text_x, 4.0f, std::max(4.0f, float(region->winx) - text_width - 4.0f));
    text_y = std::clamp(text_y, 4.0f, std::max(4.0f, float(region->winy) - line_height - 4.0f));

    BLF_color4f(font_id, 0.86f, 0.87f, 0.90f, 0.95f);
    BLF_position(font_id, text_x, text_y, 0.0f);
    BLF_draw(font_id, label, label_length);
    if (inside) {
      BLF_disable(font_id, BLF_SHADOW);
    }
  }
}

}  // namespace blender::ed::mixie
