/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include "DNA_image_types.h"
#include "DNA_packedFile_types.h"

namespace blender::blo {

inline bool packed_source_changed(const PackedFile *a, const PackedFile *b)
{
  if (a == nullptr || b == nullptr) {
    return a != b;
  }
  /* Packed bytes are immutable and implicitly shared with undo memfiles. Comparing the
   * payload (not the separately allocated PackedFile wrapper) is O(1), even for large
   * textures. Repacking identical bytes may invalidate unnecessarily, but is safe. */
  return a->data != b->data || a->size != b->size;
}

inline bool packed_sources_changed(const ListBaseT<ImagePackedFile> &a,
                                   const ListBaseT<ImagePackedFile> &b)
{
  const ImagePackedFile *pa = static_cast<const ImagePackedFile *>(a.first);
  const ImagePackedFile *pb = static_cast<const ImagePackedFile *>(b.first);
  for (; pa && pb; pa = pa->next, pb = pb->next) {
    if (pa->view != pb->view || pa->tile_number != pb->tile_number ||
        packed_source_changed(pa->packedfile, pb->packedfile))
    {
      return true;
    }
  }
  return pa != pb;
}

inline bool image_packed_sources_changed(const Image &restored, const Image &live)
{
  return packed_source_changed(restored.packedfile, live.packedfile) ||
         packed_sources_changed(restored.packedfiles, live.packedfiles) ||
         packed_sources_changed(restored.autosave_packedfiles, live.autosave_packedfiles);
}

}  // namespace blender::blo
