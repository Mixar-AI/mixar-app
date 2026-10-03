/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup bke
 *
 * Mixar per-tab undo: the partial-restore state the reader consults (arm,
 * validate, decide per datablock, end), the mode-step ownership check, and
 * the harness view of the stack as JSON (``BKE_undo_tabs.hh``).
 */
#include <algorithm>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <string>

#include "CLG_log.h"

#include "BLI_listbase.h"
#include "BLI_utildefines.h"
#include "BLI_map.hh"
#include "BLI_string.h"
#include "BLI_time.h"
#include "BLI_assert.h"
#include "BLI_set.hh"
#include "BLI_vector.hh"

#include "BLO_undofile.hh"

#include "DNA_ID.h"
#include "DNA_genfile.h"
#include "DNA_sdna_types.h"
#include "DNA_mesh_types.h"
#include "DNA_node_types.h"
#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_windowmanager_types.h"

#include "BKE_context.hh"
#include "BKE_global.hh"
#include "BKE_idprop.hh"
#include "BKE_idtype.hh"
#include "BKE_lib_query.hh"
#include "BKE_main.hh"
#include "BKE_object.hh"
#include "BKE_undo_system.hh"
#include "BKE_undo_tabs.hh"
#include "BKE_wm_runtime.hh"

#include "MEM_guardedalloc.h"
#include "undo_tabs_intern.hh"

namespace blender {

static CLG_LogRef LOG = {"undo.tabs"};

/* -------------------------------------------------------------------- */
/** \name Partial restore state (M2)
 * \{ */

struct PartialState {
  bool active = false;
  /** M4: a whole-document restore, every ID re-read. */
  bool whole = false;
  uint32_t tab = UNDO_TAB_DOCUMENT;
  const UndoOwnerMap *step_owners = nullptr;
  UndoOwnerMap *live_owners = nullptr;
  /** Shared datablocks nobody changed since the step: kept as they are live. */
  Set<uint32_t> keep;
  /** Shared datablocks only this tab changed since the step: restored (the author
   * takes back its own change, which the other tab sees, as sharing means). */
  Set<uint32_t> restore;
  /** What the reader re-read in this restore (decided Restore). */
  Set<uint32_t> reread;
};

static PartialState g_partial;

/** What tab walks re-read since the last memfile push, and from which step: the
 * live document holds that step's version of each. The next push's memfile
 * differs from the previous one by the walks' restores too, which are no change
 * of the pushing tab (the invariant test's liveness seeds: a tab's undo of its
 * own move of a shared object read as the next pushing tab moving it, and that
 * tab's undo of a later link was refused). */
struct WalkRestored {
  /** A whole-document walk re-read everything from this step. */
  const UndoStep *all = nullptr;
  Map<uint32_t, const UndoStep *> ids;
  /** Taken at the push: the data of objects in Edit Mode then. Every push flushes
   * every edit mesh, so their difference is the editing tab's, whoever pushed. */
  Set<uint32_t> in_edit;
};
static WalkRestored g_walk_restored;

void BKE_undo_tabs_walk_restored_note(const UndoStep *source)
{
  if (!g_partial.active || source == nullptr || !STREQ(source->type->name, "Global Undo")) {
    return;
  }
  if (g_partial.whole) {
    g_walk_restored.all = source;
    g_walk_restored.ids.clear();
    return;
  }
  for (const uint32_t uid : g_partial.reread) {
    g_walk_restored.ids.add_overwrite(uid, source);
  }
}

void BKE_undo_tabs_walk_restored_free(UndoStep *us)
{
  if (us != nullptr && us->mixar_walk_restored != nullptr) {
    MEM_delete(static_cast<WalkRestored *>(us->mixar_walk_restored));
    us->mixar_walk_restored = nullptr;
  }
}

void BKE_undo_tabs_walk_restored_take(UndoStep *us, Main *bmain)
{
  BKE_undo_tabs_walk_restored_free(us);
  if (bmain != nullptr) {
    for (Object &ob : bmain->objects) {
      if (ob.data != nullptr && BKE_object_is_in_editmode(&ob)) {
        g_walk_restored.in_edit.add(static_cast<ID *>(ob.data)->session_uid);
      }
    }
  }
  if (g_walk_restored.all != nullptr || !g_walk_restored.ids.is_empty() ||
      !g_walk_restored.in_edit.is_empty())
  {
    us->mixar_walk_restored = MEM_new<WalkRestored>(__func__, std::move(g_walk_restored));
  }
  g_walk_restored = WalkRestored{};
}

void BKE_undo_tabs_walk_restored_forget()
{
  g_walk_restored = WalkRestored{};
}
static UndoTabsMemfileGetFn g_memfile_get = nullptr;

void BKE_undo_tabs_memfile_getter_set(const UndoTabsMemfileGetFn fn)
{
  g_memfile_get = fn;
}

static bool step_is_memfile(const UndoStep *us)
{
  return us != nullptr && us->type != nullptr && STREQ(us->type->name, "Global Undo");
}

/** The chunks of each watched datablock in one memfile, in write order. */
using IdChunks = Map<uint32_t, Vector<const MemFileChunk *>>;

static IdChunks memfile_id_chunks(const MemFile *memfile, const Set<uint32_t> &uids)
{
  IdChunks out;
  if (memfile == nullptr) {
    return out;
  }
  for (const MemFileChunk &chunk : memfile->chunks) {
    if (uids.contains(chunk.id_session_uid)) {
      out.lookup_or_add_default(chunk.id_session_uid).append(&chunk);
    }
  }
  return out;
}

/** Where the ID struct starts in an ID's first chunk: after its block header,
 * #LargeBHead8 (32 bytes) or the legacy #SmallBHead8 (24) depending on a
 * preference. Told apart by finding the datablock's name where the ID struct
 * keeps it; -1 when neither matches (a rename: a real change anyway). */
static int64_t chunk_id_offset(const MemFileChunk *chunk, const ID *id)
{
  for (const int64_t header : {int64_t(32), int64_t(24)}) {
    const int64_t at = header + int64_t(offsetof(ID, name));
    if (at + int64_t(sizeof(id->name)) <= int64_t(chunk->size) &&
        STREQLEN(chunk->buf + at, id->name, sizeof(id->name)))
    {
      return header;
    }
  }
  return -1;
}

/** ID struct addresses in one memfile, to the datablock's session_uid: what an ID
 * pointer written into another datablock points at. An undo write keeps live
 * addresses, so the first block of each datablock's chunks carries its own. */
struct IdAddresses {
  Map<uint64_t, uint32_t> ids;
  /** Implicitly shared arrays the memfile holds by address, unwritten (the first
   * datablock referencing one in a write hands it over; later ones write a copy). */
  const MemFileSharedStorage *shared = nullptr;

  const uint32_t *lookup_ptr(const uint64_t address) const
  {
    return ids.lookup_ptr(address);
  }
  bool is_shared(const uint64_t address) const
  {
    return shared != nullptr && shared->sharing_info_by_address_id.contains(address);
  }
};

static IdAddresses memfile_id_addresses(const MemFile *memfile)
{
  IdAddresses out;
  if (memfile == nullptr) {
    return out;
  }
  out.shared = memfile->shared_storage;
  uint32_t prev = 0;
  for (const MemFileChunk &chunk : memfile->chunks) {
    if (chunk.id_session_uid != 0 && chunk.id_session_uid != prev && chunk.size >= 16) {
      uint64_t old;
      memcpy(&old, chunk.buf + 8, sizeof(old)); /* #LargeBHead8 and #SmallBHead8 alike */
      out.ids.add(old, chunk.id_session_uid);
    }
    prev = chunk.id_session_uid;
  }
  return out;
}

/** One datablock's chunks read as one byte stream. */
struct IdStream {
  const Vector<const MemFileChunk *> &chunks;
  Vector<int64_t> starts;
  int64_t size = 0;

  explicit IdStream(const Vector<const MemFileChunk *> &c) : chunks(c)
  {
    for (const MemFileChunk *chunk : c) {
      starts.append(size);
      size += int64_t(chunk->size);
    }
  }

  bool read(int64_t at, void *dst, int64_t n) const
  {
    if (at < 0 || n < 0 || at + n > size) {
      return false;
    }
    int64_t i = int64_t(std::upper_bound(starts.begin(), starts.end(), at) - starts.begin()) - 1;
    uint8_t *out = static_cast<uint8_t *>(dst);
    while (n > 0) {
      const MemFileChunk *chunk = chunks[i];
      const int64_t off = at - starts[i];
      const int64_t take = std::min<int64_t>(n, int64_t(chunk->size) - off);
      memcpy(out, chunk->buf + off, size_t(take));
      out += take;
      at += take;
      n -= take;
      i++;
    }
    return true;
  }
};

/** One written block: its header and where its data starts in the stream. */
struct WrittenBlock {
  int64_t data_at;
  int32_t code;
  int32_t sdna;
  uint64_t old;
  int64_t len;
  int64_t nr;
};

static bool parse_blocks(const IdStream &s, const int64_t header, Vector<WrittenBlock> &r_blocks)
{
  int64_t at = 0;
  while (at < s.size) {
    uint8_t h[32];
    if (!s.read(at, h, header)) {
      return false;
    }
    WrittenBlock b{};
    memcpy(&b.code, h, 4);
    memcpy(&b.old, h + 8, 8);
    if (header == 32) { /* #LargeBHead8 */
      memcpy(&b.sdna, h + 4, 4);
      memcpy(&b.len, h + 16, 8);
      memcpy(&b.nr, h + 24, 8);
    }
    else { /* #SmallBHead8 */
      int32_t len, nr;
      memcpy(&len, h + 4, 4);
      memcpy(&b.sdna, h + 16, 4);
      memcpy(&nr, h + 20, 4);
      b.len = len;
      b.nr = nr;
    }
    b.data_at = at + header;
    if (b.len < 0 || b.data_at + b.len > s.size) {
      return false;
    }
    r_blocks.append(b);
    at = b.data_at + b.len;
  }
  return true;
}

/** Where a DNA struct keeps its pointers (nested structs and arrays flattened). */
struct PtrLayout {
  bool valid = false;
  int64_t size = 0;
  Vector<int64_t> pointers;
};

static void ptr_layout_build(const SDNA *sdna, const int struct_index, PtrLayout &out, const int depth)
{
  const SDNA_Struct *st = sdna->structs[struct_index];
  int64_t offset = 0;
  for (int m = 0; m < st->members_num; m++) {
    const short type = st->members[m].type_index;
    const short member = st->members[m].member_index;
    const char *name = sdna->members[member];
    const int64_t count = sdna->members_array_num[member];
    if (name[0] == '*' || (name[0] == '(' && name[1] == '*')) {
      for (int64_t k = 0; k < count; k++) {
        out.pointers.append(offset + k * sdna->pointer_size);
      }
      offset += count * sdna->pointer_size;
      continue;
    }
    const int64_t type_size = sdna->types_size[type];
    const int sub = DNA_struct_find_index_without_alias(sdna, sdna->types[type]);
    if (sub >= 0 && depth < 32) {
      PtrLayout inner;
      ptr_layout_build(sdna, sub, inner, depth + 1);
      for (int64_t k = 0; k < count; k++) {
        for (const int64_t p : inner.pointers) {
          out.pointers.append(offset + k * type_size + p);
        }
      }
    }
    offset += count * type_size;
  }
  out.size = offset;
  out.valid = offset == DNA_struct_size(sdna, struct_index);
}

/** The top-level member of a DNA struct at a byte offset (for the debug log). */
static const char *dna_member_at(const int struct_index, const int64_t offset)
{
  const SDNA *sdna = DNA_sdna_current_get();
  if (sdna == nullptr || struct_index <= 0 || struct_index >= sdna->structs_num) {
    return "?";
  }
  const SDNA_Struct *st = sdna->structs[struct_index];
  int64_t at = 0;
  for (int m = 0; m < st->members_num; m++) {
    const int64_t size = DNA_struct_member_size(sdna, st->members[m].type_index, st->members[m].member_index);
    if (offset < at + size) {
      return sdna->members[st->members[m].member_index];
    }
    at += size;
  }
  return "?";
}

static const PtrLayout &ptr_layout(const int struct_index)
{
  static Map<int, PtrLayout> cache;
  return cache.lookup_or_add_cb(struct_index, [&]() {
    PtrLayout layout;
    const SDNA *sdna = DNA_sdna_current_get();
    if (sdna != nullptr && struct_index > 0 && struct_index < sdna->structs_num) {
      ptr_layout_build(sdna, struct_index, layout, 0);
    }
    return layout;
  });
}

/** What a written pointer points at, comparable across two writes of the same
 * datablock: a datablock (by session_uid), a place in this datablock's own blocks
 * (block ordinal + offset), a stable generated address, or null. */
struct PtrTarget {
  enum Kind : uint8_t { Null, Generated, Own, Id, Shared } kind = Null;
  uint64_t a = 0;
  int64_t b = 0;
  bool operator==(const PtrTarget &o) const
  {
    return kind == o.kind && a == o.a && b == o.b;
  }
};

struct OwnBlocks {
  Vector<std::pair<uint64_t, int64_t>> by_old; /* (address, block ordinal), sorted */
  const Vector<WrittenBlock> *blocks = nullptr;
};

static OwnBlocks own_blocks(const Vector<WrittenBlock> &blocks)
{
  OwnBlocks own;
  own.blocks = &blocks;
  for (const int64_t i : blocks.index_range()) {
    own.by_old.append({blocks[i].old, i});
  }
  std::sort(own.by_old.begin(), own.by_old.end());
  return own;
}

static PtrTarget ptr_target(const uint64_t v, const OwnBlocks &own, const IdAddresses &ids)
{
  constexpr uint64_t generated = uint64_t(1) << 63;
  if (v == 0) {
    return {PtrTarget::Null};
  }
  if (v & generated) {
    return {PtrTarget::Generated, v};
  }
  /* Implicitly shared data: immutable while a memfile holds it, so one address
   * is one content in both writes, whichever datablock's stream carries a copy. */
  if (ids.is_shared(v)) {
    return {PtrTarget::Shared, v};
  }
  /* A pointer to nothing written here (runtime data, an empty array, another
   * datablock's internals) is read back as null: the same data as a null. */
  auto it = std::upper_bound(own.by_old.begin(),
                             own.by_old.end(),
                             std::pair<uint64_t, int64_t>{v, INT64_MAX});
  if (it != own.by_old.begin()) {
    --it;
    const WrittenBlock &blk = (*own.blocks)[it->second];
    if (v < it->first + uint64_t(std::max<int64_t>(blk.len, 1))) {
      return {PtrTarget::Own, uint64_t(it->second), int64_t(v - it->first)};
    }
  }
  if (const uint32_t *uid = ids.lookup_ptr(v)) {
    return {PtrTarget::Id, *uid};
  }
  return {PtrTarget::Null};
}

/** Two implicitly shared arrays (one per memfile) with the same bytes. Each
 * memfile holds a user of its array, so neither changes while compared. */
static bool shared_arrays_equal(const uint64_t va, const IdAddresses &ids_a, const uint64_t vb, const IdAddresses &ids_b)
{
  if (!ids_a.is_shared(va) || !ids_b.is_shared(vb)) {
    return false;
  }
  const size_t *na = ids_a.shared->size_by_address_id.lookup_ptr(va);
  const size_t *nb = ids_b.shared->size_by_address_id.lookup_ptr(vb);
  if (na == nullptr || nb == nullptr || *na != *nb) {
    return false;
  }
  const void *da = ids_a.shared->sharing_info_by_address_id.lookup(va).data;
  const void *db = ids_b.shared->sharing_info_by_address_id.lookup(vb).data;
  return da != nullptr && db != nullptr && memcmp(da, db, *na) == 0;
}

/** A raw block of pointers (BlendWriter::write_pointer_array writes them untyped):
 * every word null or a written block's address. Float or index data never is. */
static bool raw_is_pointer_array(const Vector<uint8_t> &data, const OwnBlocks &own, const IdAddresses &ids)
{
  if (data.is_empty() || data.size() % 8 != 0) {
    return false;
  }
  for (int64_t at = 0; at < data.size(); at += 8) {
    uint64_t v;
    memcpy(&v, data.data() + at, 8);
    if (v != 0 && !ELEM(ptr_target(v, own, ids).kind, PtrTarget::Own, PtrTarget::Id)) {
      return false;
    }
  }
  return true;
}

/** A DNA struct that is a datablock (its first member is ``ID id``): an embedded
 * one (a material's node tree, a scene's master collection) is written as its
 * owner's block and carries its own depsgraph tags. */
static bool struct_is_id(const int struct_index)
{
  static Map<int, bool> cache;
  return cache.lookup_or_add_cb(struct_index, [&]() {
    const SDNA *sdna = DNA_sdna_current_get();
    if (sdna == nullptr || struct_index <= 0 || struct_index >= sdna->structs_num) {
      return false;
    }
    const SDNA_Struct *st = sdna->structs[struct_index];
    return st->members_num > 0 && STREQ(sdna->types[st->members[0].type_index], "ID") &&
           STREQ(sdna->members[st->members[0].member_index], "id");
  });
}

/** Socket flags the node tree update derives (linked, unavailable, the panel's
 * collapsed state) or the editor sets (selection): a material copied by a send
 * read as edited by whichever tab pushed after its first update. */
static void mask_derived_struct_bits(Vector<uint8_t> &bytes, const int struct_index, const int64_t nr)
{
  static const int socket_index = DNA_struct_find_index_without_alias(DNA_sdna_current_get(), "bNodeSocket");
  if (struct_index != socket_index || socket_index < 0) {
    return;
  }
  const uint32_t bits = SOCK_SELECT | SOCK_IS_LINKED | SOCK_UNAVAIL | SOCK_PANEL_COLLAPSED;
  for (int64_t e = 0; e < nr; e++) {
    const int64_t at = e * int64_t(sizeof(bNodeSocket)) + int64_t(offsetof(bNodeSocket, flag));
    if (at + int64_t(sizeof(bNodeSocket::flag)) > bytes.size()) {
      break;
    }
    for (int64_t k = 0; k < int64_t(sizeof(bNodeSocket::flag)); k++) {
      bytes[at + k] &= uint8_t(~(bits >> (8 * k)));
    }
  }
}

static void mask_id_tags(Vector<uint8_t> &bytes)
{
  const int64_t at = int64_t(offsetof(ID, recalc));
  const int64_t end = int64_t(offsetof(ID, recalc_after_undo_push) + sizeof(ID::recalc_after_undo_push));
  for (int64_t k = at; k < end && k < bytes.size(); k++) {
    bytes[k] = 0;
  }
}

/** Byte masks of the ID struct: what an undo write stamps that is no change of
 * the data. The ID's depsgraph tags (an image drawn in the viewport carries a
 * pending recalc, linking an object tags it); an Object's selection and visibility
 * synced from the view layers (base_flag, base_local_view_bits, the SELECT bit of
 * flag: selecting the object a tab links into another tab is not editing it); a
 * Mesh's automatic texture space (written back by the first evaluation). */
static void mask_id_struct(Vector<uint8_t> &bytes, const ID *id)
{
  auto clear = [&](const int64_t at, const int64_t size, const uint8_t bits) {
    for (int64_t k = at; k < at + size && k < bytes.size(); k++) {
      bytes[k] &= uint8_t(~bits);
    }
  };
  clear(int64_t(offsetof(ID, recalc)),
        int64_t(offsetof(ID, recalc_after_undo_push) + sizeof(ID::recalc_after_undo_push) -
                offsetof(ID, recalc)),
        0xFF);
  if (GS(id->name) == ID_OB) {
    clear(int64_t(offsetof(Object, base_flag)), int64_t(sizeof(Object::base_flag)), 0xFF);
    clear(int64_t(offsetof(Object, base_local_view_bits)), int64_t(sizeof(Object::base_local_view_bits)), 0xFF);
    /* SELECT is bit 0 of the little-endian short Object::flag. */
    clear(int64_t(offsetof(Object, flag)), 1, uint8_t(SELECT));
  }
  if (GS(id->name) == ID_ME) {
    clear(int64_t(offsetof(Mesh, texspace_location)),
          int64_t(offsetof(Mesh, texspace_flag) + sizeof(Mesh::texspace_flag) -
                  offsetof(Mesh, texspace_location)),
          0xFF);
  }
}

/** Two writes of one datablock hold the same data. Bytes are compared as written,
 * except pointers, which are compared by what they point at: an undo write keeps
 * live addresses, and a partial restore re-reads a tab's datablocks at new ones,
 * so the next push wrote every pointer to them (a light's preview, a material's
 * node tree, a mesh's material slots) differently with nothing changed. Read as
 * a change, it was credited to whichever tab pushed next and refused the other
 * tabs' undo of a shared datablock ("another tab changed it": the receiving tab
 * of a share could not take its link back, invariant test liveness seeds). The
 * DNA of each block gives its pointers; an untyped block of pointers is one whose
 * every word is null or a written address. Identical buffers (#BLO_memfile_merge
 * hands a freed step's buffers to the next one) are the common case. */
static bool id_chunks_equal(const Vector<const MemFileChunk *> *a,
                            const Vector<const MemFileChunk *> *b,
                            const ID *id,
                            const IdAddresses &ids_a,
                            const IdAddresses &ids_b)
{
  if (a == nullptr || b == nullptr) {
    return a == b;
  }
  if (a->size() == b->size()) {
    bool same = true;
    for (const int64_t i : a->index_range()) {
      if ((*a)[i]->buf != (*b)[i]->buf) {
        same = false;
        break;
      }
    }
    if (same) {
      return true;
    }
  }
  if (id == nullptr || a->is_empty() || b->is_empty()) {
    return false;
  }
  const IdStream sa(*a), sb(*b);
  const int64_t header = chunk_id_offset((*a)[0], id);
  if (header < 0 || header != chunk_id_offset((*b)[0], id)) {
    return false;
  }
  Vector<WrittenBlock> ba, bb;
  if (!parse_blocks(sa, header, ba) || !parse_blocks(sb, header, bb)) {
    return false;
  }
  /* A copy of an implicitly shared array is written by whichever datablock comes
   * second in the write: not this datablock's content (its pointer says which). */
  ba.remove_if([&](const WrittenBlock &blk) { return ids_a.is_shared(blk.old); });
  bb.remove_if([&](const WrittenBlock &blk) { return ids_b.is_shared(blk.old); });
  if (ba.size() != bb.size()) {
    if (CLOG_CHECK(&LOG, CLG_LEVEL_DEBUG)) {
      const SDNA *sdna = DNA_sdna_current_get();
      for (int64_t i = 0; i < std::max(ba.size(), bb.size()); i++) {
        if (i >= ba.size() || i >= bb.size() || ba[i].len != bb[i].len || ba[i].sdna != bb[i].sdna) {
          auto desc = [&](const Vector<WrittenBlock> &v) {
            return i < v.size() ? std::string(v[i].sdna > 0 ?
                                                  DNA_struct_identifier(const_cast<SDNA *>(sdna), v[i].sdna) :
                                                  "raw") +
                                      "[" + std::to_string(v[i].len) + "]" :
                                  std::string("-");
          };
          CLOG_DEBUG(&LOG,
                     "%s changed: block %d: %s vs %s (%d vs %d blocks)",
                     id->name,
                     int(i),
                     desc(ba).c_str(),
                     desc(bb).c_str(),
                     int(ba.size()),
                     int(bb.size()));
          break;
        }
      }
    }
    return false;
  }
  const OwnBlocks own_a = own_blocks(ba), own_b = own_blocks(bb);
  const bool written_back_by_eval = ELEM(GS(id->name), ID_OB, ID_ME, ID_CU_LEGACY, ID_MB);
  const int64_t first_chunk = int64_t((*b)[0]->size);
  /* The furthest stream offset of a difference: the depsgraph write-back gate
   * below only covers the first chunk, as it always has. */
  int64_t last_diff = -1;
  Vector<uint8_t> da, db;
  for (const int64_t i : ba.index_range()) {
    const WrittenBlock &x = ba[i], &y = bb[i];
    if (x.code != y.code || x.sdna != y.sdna || x.len != y.len || x.nr != y.nr) {
      CLOG_DEBUG(&LOG, "%s changed: block %d header", id->name, int(i));
      return false;
    }
    da.resize(x.len);
    db.resize(y.len);
    sa.read(x.data_at, da.data(), x.len);
    sb.read(y.data_at, db.data(), y.len);
    const PtrLayout *layout = x.sdna > 0 ? &ptr_layout(x.sdna) : nullptr;
    if (layout != nullptr && layout->valid && layout->size > 0 && x.len == x.nr * layout->size) {
      for (int64_t e = 0; e < x.nr; e++) {
        for (const int64_t p : layout->pointers) {
          const int64_t at = e * layout->size + p;
          if (at + 8 > x.len) {
            continue;
          }
          uint64_t va, vb;
          memcpy(&va, da.data() + at, 8);
          memcpy(&vb, db.data() + at, 8);
          if (va != vb && !(ptr_target(va, own_a, ids_a) == ptr_target(vb, own_b, ids_b)) &&
              !shared_arrays_equal(va, ids_a, vb, ids_b))
          {
            CLOG_DEBUG(&LOG,
                       "%s changed: block %d (%s.%s) pointer: kind %d vs %d",
                       id->name,
                       int(i),
                       DNA_struct_identifier(const_cast<SDNA *>(DNA_sdna_current_get()), x.sdna),
                       dna_member_at(x.sdna, at % layout->size),
                       int(ptr_target(va, own_a, ids_a).kind),
                       int(ptr_target(vb, own_b, ids_b).kind));
            return false;
          }
          memset(da.data() + at, 0, 8);
          memset(db.data() + at, 0, 8);
        }
      }
    }
    else if (x.sdna == 0 && da != db && raw_is_pointer_array(da, own_a, ids_a) &&
             raw_is_pointer_array(db, own_b, ids_b))
    {
      for (int64_t at = 0; at < x.len; at += 8) {
        uint64_t va, vb;
        memcpy(&va, da.data() + at, 8);
        memcpy(&vb, db.data() + at, 8);
        if (!(ptr_target(va, own_a, ids_a) == ptr_target(vb, own_b, ids_b))) {
          CLOG_DEBUG(&LOG, "%s changed: pointer array block %d", id->name, int(i));
          return false;
        }
      }
      continue;
    }
    if (i == 0) {
      mask_id_struct(da, id);
      mask_id_struct(db, id);
    }
    else if (x.sdna > 0 && struct_is_id(x.sdna)) {
      mask_id_tags(da);
      mask_id_tags(db);
    }
    if (x.sdna > 0) {
      mask_derived_struct_bits(da, x.sdna, x.nr);
      mask_derived_struct_bits(db, x.sdna, x.nr);
    }
    if (da != db) {
      for (int64_t k = 0; k < x.len; k++) {
        if (da[k] != db[k]) {
          last_diff = x.data_at + k;
          CLOG_DEBUG(&LOG,
                     "%s changed: block %d (%s.%s) differs at byte %lld",
                     id->name,
                     int(i),
                     x.sdna > 0 ? DNA_struct_identifier(const_cast<SDNA *>(DNA_sdna_current_get()), x.sdna) : "raw",
                     (layout != nullptr && layout->valid && layout->size > 0) ?
                         dna_member_at(x.sdna, k % layout->size) :
                         "",
                     (long long)k);
          if (!written_back_by_eval || last_diff >= first_chunk) {
            return false;
          }
          break;
        }
      }
    }
  }
  if (last_diff < 0) {
    return true;
  }
  /* Bytes differ. A change made by an operator, RNA or an edit-mode flush tags the
   * ID, and the newer step records those tags (recalc_up_to_undo_push); data
   * the depsgraph writes back into the original on evaluation (a mesh's
   * automatic texture space, caches after the struct) tags nothing. No tag in
   * the newer step: derived, not a change of the data (the Engine Mode GUI
   * pass, 2026-10-02: a link step read as editing the linked object's mesh).
   * Only for the types evaluation writes back into (objects, geometry with an
   * automatic texture space): an RNA edit of an image does not tag it, and
   * would read as no change at all. */
  if (!written_back_by_eval || last_diff >= first_chunk) {
    return false;
  }
  uint32_t tagged = 0;
  const int64_t tag_at = header + int64_t(offsetof(ID, recalc_up_to_undo_push));
  if (tag_at + int64_t(sizeof(tagged)) <= int64_t((*b)[0]->size)) {
    memcpy(&tagged, (*b)[0]->buf + tag_at, sizeof(tagged));
  }
  /* Tags that are no change of the data: selection, base flags (linking an
   * object into another tab sets these), editor redraws, copy-to-evaluated
   * syncs, frame and audio updates. */
  const uint32_t noise = ID_RECALC_SELECT | ID_RECALC_BASE_FLAGS | ID_RECALC_EDITORS |
                         ID_RECALC_SYNC_TO_EVAL | ID_RECALC_FRAME_CHANGE | ID_RECALC_AUDIO_FPS |
                         ID_RECALC_AUDIO_VOLUME | ID_RECALC_AUDIO_MUTE | ID_RECALC_AUDIO_LISTENER |
                         ID_RECALC_AUDIO;
  return (tagged & ~noise) == 0;
}

static int step_index(const UndoStack *ustack, const UndoStep *us)
{
  return us != nullptr ? BLI_findindex(&ustack->steps, us) : -1;
}

/** One change to a shared datablock: the stack index of the step that shows it
 * (a memfile step whose chunks for it differ from the memfile before, or a mode
 * step that names it) and an author of that change. */
struct IdChange {
  int index;
  uint32_t author;
};
using IdChanges = Map<uint32_t, Vector<IdChange>>;

/** The change history of ``watched`` across the whole stack. A memfile change is
 * credited to every author of the steps since the memfile before it (a step's
 * #UndoStep::mixar_author_uid, which a dead redo branch keeps). */
static IdChanges collect_id_changes(const UndoStack *ustack, const Map<uint32_t, ID *> &watched)
{
  IdChanges out;
  Set<uint32_t> uids;
  for (const auto item : watched.items()) {
    uids.add(item.key);
  }
  IdChunks prev;
  IdAddresses prev_ids;
  bool have_prev = false;
  struct SourceView {
    IdChunks chunks;
    IdAddresses ids;
  };
  Map<const UndoStep *, SourceView> sources;
  auto walk_source = [&](const UndoStep *step, const uint32_t uid) -> const UndoStep * {
    const WalkRestored *wr = static_cast<const WalkRestored *>(step->mixar_walk_restored);
    if (wr == nullptr || g_memfile_get == nullptr) {
      return nullptr;
    }
    const UndoStep *const *found = wr->ids.lookup_ptr(uid);
    const UndoStep *source = found ? *found : wr->all;
    if (source == nullptr || BLI_findindex(&ustack->steps, source) < 0 || !step_is_memfile(source)) {
      return nullptr; /* freed since */
    }
    return source;
  };
  Vector<uint32_t> authors;
  /* Datablocks a mode step named since the previous memfile, and its authors. */
  Map<uint32_t, Vector<uint32_t>> mode_authors;
  /* The author of the latest mode step that named each datablock. */
  Map<uint32_t, uint32_t> last_mode_author;
  /* A mode step names the OBJECT it edits (edit mesh, sculpt), but the change is
   * to its data, and it reaches no memfile until the next push of any tab flushes
   * the edit: an object's name stands for its watched data too. */
  Map<std::string, Vector<uint32_t>> by_name;
  for (const auto item : watched.items()) {
    if (item.value != nullptr) {
      by_name.lookup_or_add_default(item.value->name).append(item.key);
    }
  }
  if (G_MAIN != nullptr) {
    for (const Object &ob : G_MAIN->objects) {
      const ID *data = static_cast<const ID *>(ob.data);
      if (data != nullptr && watched.contains(data->session_uid)) {
        by_name.lookup_or_add_default(ob.id.name).append_non_duplicates(data->session_uid);
      }
    }
  }
  struct RefMatch {
    const Map<std::string, Vector<uint32_t>> *by_name;
    Vector<uint32_t> found;
  };
  int index = -1;
  for (const UndoStep *us = static_cast<const UndoStep *>(ustack->steps.first); us; us = us->next) {
    index++;
    authors.append_non_duplicates(us->mixar_author_uid);
    const MemFile *memfile = (step_is_memfile(us) && g_memfile_get != nullptr) ? g_memfile_get(us) :
                                                                                  nullptr;
    if (memfile == nullptr) {
      if (us->type != nullptr && us->type->step_foreach_ID_ref != nullptr) {
        /* A mode step (a stroke, an edit-mesh step) names what it changes; matched
         * by name, as the walk resolves its references. */
        RefMatch match{&by_name, {}};
        us->type->step_foreach_ID_ref(
            const_cast<UndoStep *>(us),
            [](void *user_data, UndoRefID *id_ref) {
              RefMatch *m = static_cast<RefMatch *>(user_data);
              if (const Vector<uint32_t> *uids = m->by_name->lookup_ptr(id_ref->name)) {
                for (const uint32_t uid : *uids) {
                  m->found.append_non_duplicates(uid);
                }
              }
            },
            &match);
        for (const uint32_t uid : match.found) {
          out.lookup_or_add_default(uid).append({index, us->mixar_author_uid});
          mode_authors.lookup_or_add_default(uid).append_non_duplicates(us->mixar_author_uid);
          last_mode_author.add_overwrite(uid, us->mixar_author_uid);
        }
      }
      continue;
    }
    IdChunks cur = memfile_id_chunks(memfile, uids);
    IdAddresses cur_ids = memfile_id_addresses(memfile);
    if (have_prev) {
      for (const uint32_t uid : uids) {
        /* Re-read by a walk since the previous push: what the push changed is its
         * difference from the step the walk read it from. */
        const UndoStep *source = walk_source(us, uid);
        bool changed;
        if (source != nullptr) {
          const SourceView &sv = sources.lookup_or_add_cb(source, [&]() {
            const MemFile *mf = g_memfile_get(source);
            return SourceView{memfile_id_chunks(mf, uids), memfile_id_addresses(mf)};
          });
          changed = !id_chunks_equal(
              sv.chunks.lookup_ptr(uid), cur.lookup_ptr(uid), watched.lookup(uid), sv.ids, cur_ids);
        }
        else {
          changed = !id_chunks_equal(
              prev.lookup_ptr(uid), cur.lookup_ptr(uid), watched.lookup(uid), prev_ids, cur_ids);
        }
        if (changed) {
          /* A datablock a mode step named since the previous memfile: this memfile
           * is where that edit landed (any tab's push flushes every edit mesh), so
           * it is the mode steps' authors' change, not the pushing tab's. A share
           * pushed while the other tab had the mesh in Edit Mode read as the
           * receiving tab editing it, and refused its undo of the link. */
          const Vector<uint32_t> *by_mode = mode_authors.lookup_ptr(uid);
          /* In Edit Mode at the push: the flush of the editing tab's edit mesh. */
          const WalkRestored *info = static_cast<const WalkRestored *>(us->mixar_walk_restored);
          const uint32_t *editor = (info != nullptr && info->in_edit.contains(uid)) ?
                                       last_mode_author.lookup_ptr(uid) :
                                       nullptr;
          if (by_mode == nullptr && editor != nullptr) {
            out.lookup_or_add_default(uid).append({index, *editor});
          }
          else {
            for (const uint32_t author : (by_mode != nullptr ? *by_mode : authors)) {
              out.lookup_or_add_default(uid).append({index, author});
            }
          }
        }
      }
    }
    prev = std::move(cur);
    prev_ids = std::move(cur_ids);
    have_prev = true;
    authors.clear();
    mode_authors.clear();
  }
  return out;
}

enum class SharedFate { Keep, Restore, Refuse };

/**
 * What a tab's walk does with a datablock it shares with another tab (review
 * 2026-10-02, the author rule: an undo takes back only the pressing tab's own
 * actions, wherever they landed). ``lo`` is the older of the walk's target and
 * the tab's cursor:
 *
 * - this tab did not change it after ``lo``: KEEP it exactly as it is, whatever
 *   the other tabs did to it (keeping never touches their work);
 * - this tab changed it, and another tab changed it after ``lo`` too or has an
 *   older change to it undone since (its cursor is behind that change): REFUSE,
 *   the two cannot be told apart in one memfile;
 * - only this tab changed it: RESTORE it with the tab (the other tab sees the
 *   shared datablock go back), unless it did not exist at the target while
 *   another tab uses it now (a restore would free it under that tab).
 */
static SharedFate shared_fate(const UndoStack *ustack,
                              const uint32_t tab_uid,
                              const int lo,
                              const Vector<IdChange> *changes,
                              const bool absent_at_target,
                              const char **r_why)
{
  if (changes == nullptr) {
    return SharedFate::Keep;
  }
  const int active = step_index(ustack, ustack->step_active);
  bool by_tab = false;
  const char *foreign = nullptr;
  for (const IdChange &c : *changes) {
    if (c.author == tab_uid) {
      by_tab |= c.index > lo;
      continue;
    }
    if (c.index > lo) {
      foreign = "another tab changed it since that step";
      continue;
    }
    const UndoStep *cursor = (c.author != UNDO_TAB_DOCUMENT) ?
                                 BKE_undosys_tab_cursor(const_cast<UndoStack *>(ustack), c.author) :
                                 nullptr;
    if (c.index > active || (cursor != nullptr && c.index > step_index(ustack, cursor))) {
      foreign = "another tab has taken back its own change to it";
    }
  }
  /* Keeping it exactly as it is never touches another tab's work, whatever the
   * other tabs did to it: only a restore (this tab changed it) can conflict. */
  if (!by_tab) {
    return SharedFate::Keep;
  }
  if (foreign != nullptr) {
    *r_why = foreign;
    if (CLOG_CHECK(&LOG, CLG_LEVEL_DEBUG)) {
      std::string list;
      for (const IdChange &c : *changes) {
        list += " " + std::to_string(c.index) + ":" + std::to_string(c.author);
      }
      CLOG_DEBUG(&LOG, "refuse for tab %u (lo %d, active %d): changes%s", tab_uid, lo, active, list.c_str());
    }
    return SharedFate::Refuse;
  }
  if (absent_at_target) {
    *r_why = "this tab made it after that step and another tab uses it now";
    return SharedFate::Refuse;
  }
  return SharedFate::Restore;
}

static void note_conflict(Map<uint32_t, std::string> &conflicts, const uint32_t uid, const std::string &name)
{
  conflicts.add(uid, name);
}

static bool partial_validate(Main *bmain,
                             const UndoStack *ustack,
                             const uint32_t tab_uid,
                             const UndoStep *target,
                             const UndoOwnerMap *live,
                             Set<uint32_t> *r_keep,
                             Set<uint32_t> *r_restore,
                             std::string *r_reason)
{
  const UndoOwnerMap *step_owners = target ? target->mixar_owners : nullptr;
  /* A memfile step written while per-tab undo was off carries no owner map.
   * Without it the reader cannot tell what the tab owned THEN: a datablock the
   * tab had at the step and deleted since would be skipped as "not this tab's"
   * and silently never come back (review 2026-10-01, R5). Fails closed. */
  if (step_owners == nullptr) {
    if (r_reason) {
      *r_reason =
          "that step was recorded while per-tab undo was off (Edit > Undo Whole Document walks "
          "every tab)";
    }
    return false;
  }
  /* The conflicts: local datablocks this tab reaches that another tab reaches
   * too, now or at the step (what two OTHER tabs share is none of this tab's
   * business; review 2026-09-30, finding 1). */
  Map<uint32_t, std::string> conflicts;
  for (const UndoOwnerMap *map : {live, step_owners}) {
    for (const auto item : map->shared_name.items()) {
      const Vector<uint32_t> *tabs = map->shared_by.lookup_ptr(item.key);
      if (tabs != nullptr && tabs->contains(tab_uid)) {
        note_conflict(conflicts, item.key, item.value);
      }
    }
  }
  /* Datablocks that changed hands since the step:
   * - one another tab reaches now that this tab reached at the step but no longer
   *   does (this tab gave it away): decided like a shared one (the author rule):
   *   taking back the unlink re-links it into this tab's collection, and the
   *   datablock itself is kept unless only this tab changed it since (the
   *   invariant test, 2026-10-02: it was restored over two other tabs' changes);
   * - one this tab reaches now that only other tabs reached at the step (it came
   *   from another tab): refused. Restoring this tab would drop it from the only
   *   tab that has it, the other having given it away. */
  Map<uint32_t, ID *> live_ids;
  std::string moved;
  int moved_count = 0;
  {
    auto tabs_of = [&](const UndoOwnerMap *map, const uint32_t uid) -> Vector<uint32_t> {
      const uint32_t owner = BKE_undo_owner_map_lookup(map, uid);
      if (owner == UNDO_TAB_SHARED) {
        const Vector<uint32_t> *tabs = map->shared_by.lookup_ptr(uid);
        return tabs ? *tabs : Vector<uint32_t>();
      }
      if (ELEM(owner, UNDO_TAB_DOCUMENT, UNDO_TAB_LANE)) {
        return {};
      }
      return {owner};
    };
    ID *id = nullptr;
    FOREACH_MAIN_ID_BEGIN (bmain, id) {
      live_ids.add(id->session_uid, id);
      const Vector<uint32_t> then = tabs_of(step_owners, id->session_uid);
      const Vector<uint32_t> now = tabs_of(live, id->session_uid);
      const bool tab_then = then.contains(tab_uid), tab_now = now.contains(tab_uid);
      if (tab_then && !tab_now && !now.is_empty()) {
        /* Given away: the author rule below decides (kept when this tab did not
         * change it since, restored when only this tab did: a tab that recoloured
         * a material and deleted its object, whose orphan mesh another tab's image
         * now claims, took the recolour back on its undo). */
        note_conflict(conflicts, id->session_uid, std::string(id->name + 2));
      }
      else if (tab_now && !tab_then && !then.is_empty()) {
        bool still_there = false;
        for (const uint32_t t : then) {
          still_there |= now.contains(t);
        }
        if (still_there) {
          /* Linked in from a tab that still has it (Engine Mode's Link Objects to
           * Scene, an outliner drag): shared, not moved. The author rule decides
           * (the Engine Mode GUI pass, 2026-10-02: the receiving tab could not
           * take its own link back). */
          note_conflict(conflicts, id->session_uid, std::string(id->name + 2));
        }
        else if (moved_count++ < 8) {
          moved += (moved.empty() ? "" : ", ") + std::string(id->name + 2);
        }
      }
    }
    FOREACH_MAIN_ID_END;
  }
  if (moved_count > 0) {
    if (r_reason) {
      *r_reason = "moved between tabs since that step: " + moved +
                  " (Edit > Undo Whole Document walks every tab)";
    }
    return false;
  }
  /* This tab's own datablock at the step, gone now, that another tab reached in
   * between (this tab shared it, a step filed under the receiving tab): when
   * another tab changed it since (deleted it there), restoring this tab would
   * take back that tab's delete (the invariant test, seed 10013: a tab's undo past
   * its share brought back the object the receiving tab had deleted). */
  if (g_memfile_get != nullptr) {
    Map<uint32_t, ID *> lost;
    Map<uint32_t, std::string> lost_names;
    const int target_index = step_index(ustack, target);
    for (const auto item : step_owners->owner.items()) {
      if (item.value != tab_uid || live_ids.contains(item.key)) {
        continue;
      }
      int index = -1;
      for (const UndoStep *us = static_cast<const UndoStep *>(ustack->steps.first); us; us = us->next) {
        index++;
        if (index <= target_index || us->mixar_owners == nullptr) {
          continue;
        }
        const Vector<uint32_t> *tabs = us->mixar_owners->shared_by.lookup_ptr(item.key);
        if (tabs != nullptr && tabs->size() > 1) {
          lost.add(item.key, nullptr);
          const std::string *name = us->mixar_owners->shared_name.lookup_ptr(item.key);
          lost_names.add(item.key, name ? *name : std::to_string(item.key));
          break;
        }
      }
    }
    if (!lost.is_empty()) {
      const IdChanges changes = collect_id_changes(ustack, lost);
      const int lo = std::min(target_index,
                              step_index(ustack, BKE_undosys_tab_cursor(const_cast<UndoStack *>(ustack), tab_uid)));
      std::string deleted;
      for (const auto item : lost.items()) {
        const Vector<IdChange> *ch = changes.lookup_ptr(item.key);
        bool foreign = false;
        for (const IdChange &c : (ch ? *ch : Vector<IdChange>())) {
          foreign |= c.index > lo && c.author != tab_uid;
        }
        if (foreign) {
          deleted += (deleted.empty() ? "" : ", ") + lost_names.lookup(item.key);
        }
      }
      if (!deleted.empty()) {
        if (r_reason) {
          *r_reason = "shared with another tab since that step and deleted there: " + deleted +
                      " (Edit > Undo Whole Document walks every tab)";
        }
        return false;
      }
    }
  }
  if (conflicts.is_empty()) {
    return true;
  }
  /* A shared datablock that no longer exists cannot be kept (the restored
   * datablocks of this tab may point at it). */
  std::string gone;
  for (const auto item : conflicts.items()) {
    if (!live_ids.contains(item.key)) {
      gone += (gone.empty() ? "" : ", ") + item.value;
    }
  }
  if (!gone.empty()) {
    if (r_reason) {
      *r_reason = "shared with another tab at that step and gone since: " + gone +
                  " (Edit > Undo Whole Document walks every tab)";
    }
    return false;
  }
  if (g_memfile_get == nullptr) {
    if (r_reason) {
      *r_reason = "shared with another tab (Edit > Undo Whole Document walks every tab)";
    }
    return false;
  }
  /* The author rule (shared_fate): keep what nobody changed, restore what only
   * this tab changed, refuse what another tab changed too. */
  Map<uint32_t, ID *> watched;
  Set<uint32_t> uids;
  for (const auto item : conflicts.items()) {
    watched.add(item.key, live_ids.lookup(item.key));
    uids.add(item.key);
  }
  const IdChanges changes = collect_id_changes(ustack, watched);
  const IdChunks at_target = memfile_id_chunks(g_memfile_get(target), uids);
  const int lo = std::min(step_index(ustack, target),
                          step_index(ustack, BKE_undosys_tab_cursor(const_cast<UndoStack *>(ustack), tab_uid)));
  std::string refused;
  int restored = 0;
  for (const auto item : conflicts.items()) {
    const char *why = "";
    const Vector<IdChange> *ch = changes.lookup_ptr(item.key);
    switch (shared_fate(ustack, tab_uid, lo, ch, !at_target.contains(item.key), &why)) {
      case SharedFate::Keep:
        if (r_keep != nullptr) {
          r_keep->add(item.key);
        }
        break;
      case SharedFate::Restore:
        restored++;
        if (r_restore != nullptr) {
          r_restore->add(item.key);
        }
        break;
      case SharedFate::Refuse:
        refused += (refused.empty() ? "" : "; ") + item.value + " (" + why + ")";
        break;
    }
  }
  if (!refused.empty()) {
    if (r_reason) {
      *r_reason = "shared with another tab: " + refused + " (Edit > Undo Whole Document walks every tab)";
    }
    return false;
  }
  CLOG_DEBUG(&LOG,
             "tab %u: %d shared datablock(s), %d restored with the tab, the rest kept",
             tab_uid,
             int(conflicts.size()),
             restored);
  return true;
}

bool BKE_undo_tabs_partial_check(Main *bmain,
                                 const UndoStack *ustack,
                                 const uint32_t tab_uid,
                                 const UndoStep *target,
                                 std::string *r_reason)
{
  UndoOwnerMap *live = BKE_undo_owner_map_build(bmain, nullptr);
  const bool ok = partial_validate(bmain, ustack, tab_uid, target, live, nullptr, nullptr, r_reason);
  BKE_undo_owner_map_free(live);
  return ok;
}

bool BKE_undo_tabs_partial_begin(Main *bmain,
                                 const UndoStack *ustack,
                                 const uint32_t tab_uid,
                                 const UndoStep *target,
                                 std::string *r_reason)
{
  BLI_assert(!g_partial.active);
  UndoOwnerMap *live = BKE_undo_owner_map_build(bmain, nullptr);
  Set<uint32_t> keep, restore;
  if (!partial_validate(bmain, ustack, tab_uid, target, live, &keep, &restore, r_reason)) {
    BKE_undo_owner_map_free(live);
    return false;
  }
  g_partial.active = true;
  g_partial.tab = tab_uid;
  g_partial.step_owners = target->mixar_owners;
  g_partial.live_owners = live;
  g_partial.keep = std::move(keep);
  g_partial.restore = std::move(restore);
  CLOG_DEBUG(&LOG, "partial restore armed for tab %u", tab_uid);
  return true;
}

bool BKE_undo_tabs_ids_owned(Main *bmain,
                             const uint32_t tab_uid,
                             const Span<ID *> ids,
                             std::string *r_reason,
                             const Set<uint32_t> *shared_ok)
{
  UndoOwnerMap *live = BKE_undo_owner_map_build(bmain, nullptr);
  bool ok = true;
  for (ID *id : ids) {
    if (id == nullptr) {
      if (r_reason) {
        *r_reason = "a datablock that step edited no longer exists";
      }
      ok = false;
      break;
    }
    const uint32_t owner = (GS(id->name) == ID_SCE) ?
                               BKE_undo_tab_uid_for_scene(bmain, reinterpret_cast<Scene *>(id)) :
                               BKE_undo_owner_map_lookup(live, id->session_uid);
    /* The tab's own, or global (no tab reaches it): a Text in the editor, a
     * Brush. Another tab's, or shared, is refused. */
    if (owner == UNDO_TAB_SHARED && shared_ok != nullptr && shared_ok->contains(id->session_uid)) {
      continue; /* shared, and no other tab touched it since this tab's cursor */
    }
    if (owner != tab_uid && owner != UNDO_TAB_DOCUMENT) {
      if (r_reason) {
        *r_reason = std::string("'") + (id->name + 2) + "' " +
                    (owner == UNDO_TAB_SHARED ? "is shared between tabs" : "belongs to another tab");
      }
      ok = false;
      break;
    }
  }
  BKE_undo_owner_map_free(live);
  return ok;
}

Set<uint32_t> BKE_undo_tabs_shared_ok(const UndoStack *ustack,
                                      const uint32_t tab_uid,
                                      const UndoStep *target,
                                      const Span<ID *> ids)
{
  Set<uint32_t> ok;
  if (ustack == nullptr || target == nullptr || ids.is_empty()) {
    return ok;
  }
  Map<uint32_t, ID *> watched;
  for (ID *id : ids) {
    if (id != nullptr) {
      watched.add(id->session_uid, id);
    }
  }
  const IdChanges changes = collect_id_changes(ustack, watched);
  const int lo = std::min(step_index(ustack, target),
                          step_index(ustack, BKE_undosys_tab_cursor(const_cast<UndoStack *>(ustack), tab_uid)));
  for (const auto item : watched.items()) {
    const char *why = "";
    if (shared_fate(ustack, tab_uid, lo, changes.lookup_ptr(item.key), false, &why) != SharedFate::Refuse) {
      ok.add(item.key);
    }
  }
  return ok;
}

void BKE_undo_tabs_whole_document_begin()
{
  BLI_assert(!g_partial.active);
  g_partial = PartialState{};
  g_partial.active = true;
  g_partial.whole = true;
  CLOG_DEBUG(&LOG, "whole-document restore armed: every ID re-read");
}

void BKE_undo_tabs_partial_end()
{
  if (g_partial.live_owners != nullptr) {
    BKE_undo_owner_map_free(g_partial.live_owners);
  }
  g_partial = PartialState{};
}

bool BKE_undo_tabs_partial_active()
{
  return g_partial.active;
}

uint32_t BKE_undo_tabs_partial_tab()
{
  return g_partial.active ? g_partial.tab : UNDO_TAB_DOCUMENT;
}

static UndoPartialDecision partial_decide(const uint32_t session_uid, const bool has_live)
{
  if (!g_partial.active || g_partial.whole) {
    return UndoPartialDecision::Restore;
  }
  /* A shared datablock only this tab changed since the step: the tab's to restore. */
  if (g_partial.restore.contains(session_uid)) {
    return UndoPartialDecision::Restore;
  }
  /* A shared datablock nobody changed since the step: exactly as it is live. */
  if (g_partial.keep.contains(session_uid)) {
    return has_live ? UndoPartialDecision::Keep : UndoPartialDecision::Skip;
  }
  const uint32_t at_step = BKE_undo_owner_map_lookup(g_partial.step_owners, session_uid);
  const uint32_t now = BKE_undo_owner_map_lookup(g_partial.live_owners, session_uid);
  /* The tab's own datablock, at the step or now: the normal undo paths. */
  if (at_step == g_partial.tab || now == g_partial.tab) {
    return UndoPartialDecision::Restore;
  }
  /* Everything else stays exactly as it is now; what is not live anymore is
   * not brought back on this tab's behalf (a worker lane among them). */
  return has_live ? UndoPartialDecision::Keep : UndoPartialDecision::Skip;
}

UndoPartialDecision BKE_undo_tabs_partial_decide(const uint32_t session_uid, const bool has_live)
{
  const UndoPartialDecision decision = partial_decide(session_uid, has_live);
  if (g_partial.active && !g_partial.whole && decision == UndoPartialDecision::Restore) {
    g_partial.reread.add(session_uid);
  }
  return decision;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Harness view
 * \{ */

static void json_escape_into(std::string &out, const char *text)
{
  for (const char *p = text; p != nullptr && *p; p++) {
    switch (*p) {
      case '"':
        out += "\\\"";
        break;
      case '\\':
        out += "\\\\";
        break;
      case '\n':
        out += "\\n";
        break;
      default:
        if (uint8_t(*p) < 0x20) {
          out += ' ';
        }
        else {
          out += *p;
        }
    }
  }
}

std::string BKE_undo_tabs_history_json(const wmWindowManager *wm)
{
  std::string out = "{";
  const UndoStack *ustack = (wm != nullptr && wm->runtime != nullptr) ? wm->runtime->undo_stack :
                                                                       nullptr;
  uint32_t current = UNDO_TAB_DOCUMENT;
  if (wm != nullptr) {
    const wmWindow *win = (wm->runtime != nullptr && wm->runtime->winactive != nullptr) ?
                              wm->runtime->winactive :
                              static_cast<const wmWindow *>(wm->windows.first);
    if (win != nullptr && win->scene != nullptr) {
      current = BKE_undo_tab_uid_for_scene(G_MAIN, win->scene);
    }
  }
  out += "\"enabled\":" + std::string(BKE_undo_tabs_enabled() ? "true" : "false");
  out += ",\"current_tab\":" + std::to_string(current);
  out += ",\"steps\":[";
  if (ustack != nullptr) {
    const UndoStep *cursor = (current != UNDO_TAB_DOCUMENT) ?
                                 BKE_undosys_tab_cursor(const_cast<UndoStack *>(ustack), current) :
                                 nullptr;
    int index = BLI_listbase_count(&ustack->steps) - 1;
    bool first = true;
    for (const UndoStep *us = static_cast<const UndoStep *>(ustack->steps.last); us; us = us->prev) {
      if (!first) {
        out += ",";
      }
      first = false;
      out += "{\"index\":" + std::to_string(index--);
      out += ",\"name\":\"";
      json_escape_into(out, us->name);
      out += "\",\"type\":\"";
      json_escape_into(out, us->type != nullptr ? us->type->name : "");
      out += "\",\"tab_uid\":" + std::to_string(us->mixar_tab_uid);
      out += ",\"skip\":" + std::string(us->skip ? "true" : "false");
      out += ",\"active\":" + std::string(us == ustack->step_active ? "true" : "false");
      out += ",\"cursor\":" + std::string(us == cursor ? "true" : "false");
      out += ",\"memfile\":" +
             std::string((us->type != nullptr && STREQ(us->type->name, "Global Undo")) ? "true" :
                                                                                         "false");
      out += ",\"owners\":" + std::to_string(BKE_undo_owner_map_size(us->mixar_owners));
      out += ",\"shared\":" + std::to_string(BKE_undo_owner_map_shared_count(us->mixar_owners));
      out += ",\"shared_names\":[";
      if (us->mixar_owners != nullptr) {
        bool first_name = true;
        for (const std::string &name : us->mixar_owners->shared_names) {
          if (!first_name) {
            out += ",";
          }
          first_name = false;
          out += "\"";
          json_escape_into(out, name.c_str());
          out += "\"";
        }
      }
      out += "],\"owner_map_ms\":" +
             std::to_string(us->mixar_owners != nullptr ? us->mixar_owners->build_ms : 0.0);
      out += "}";
    }
  }
  out += "]}";
  return out;
}

/** \} */

}  // namespace blender
