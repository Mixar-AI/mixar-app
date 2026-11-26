/* SPDX-FileCopyrightText: 2016 by Mike Erwin. All rights reserved.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup gpu
 *
 * Mimics old style opengl immediate mode drawing.
 */

#include "BLI_vector.hh"

#include "CLG_log.h"

#include "GPU_capabilities.hh"

#include "gpu_context_private.hh"
#include "gpu_shader_private.hh"
#include "gpu_vertex_format_private.hh"

#include "gl_context.hh"
#include "gl_debug.hh"
#include "gl_primitive.hh"
#include "gl_vertex_array.hh"

#include "gl_immediate.hh"

namespace blender::gpu {

/* MIXAR-2043: state for a failed buffer mapping. Kept here, not in the class, so the overlay stays
 * one file. Each thread drives its own context and never nests immBegin/immEnd. */
static CLG_LogRef LOG = {"gpu.opengl"};
static thread_local bool map_failure_logged = false;
static thread_local bool map_failed = false;
/* Set by a retry, cleared by any mapping that succeeds: one retry per streak of failures. */
static thread_local bool map_retry_spent = false;
/* Floats with no inline buffer: vertex attributes are written through float and uint pointers,
 * so the scratch needs the 4-byte alignment a heap block has and an inline uchar buffer lacks. */
static thread_local Vector<float, 0> map_scratch;

/* MIXAR-2043: what begin() returns when glMapBufferRange gave it null (seen on AMD Windows
 * drivers): upstream hands the null to immVertex*, which faults at address 0. Retry on fresh
 * storage, once per streak of failures; without a mapping after that, return scratch memory and
 * make end() skip the draw: a missing primitive instead of a crash. */
static void *map_failure_fallback(const size_t store_size,
                                  size_t &buffer_offset,
                                  const size_t bytes_needed,
                                  const GLbitfield access)
{
  /* A zero-length mapping is null by specification: no retry, no log line. When the driver fails
   * every mapping (a lost device, say), a retry on each immBegin would allocate a fresh store,
   * 4 MiB or more, hundreds of times per frame: hence one retry per streak. */
  if (bytes_needed > 0 && !map_retry_spent) {
    map_retry_spent = true;
    /* The first failure on a thread always retries, so the one log line can say how the retry
     * went. What the driver knows about the buffer is read before the orphan replaces it. */
    const bool log = !map_failure_logged;
    map_failure_logged = true;
    GLint gl_mapped = 0;
    GLint gl_size = 0;
    GLenum stale_error = GL_NO_ERROR;
    if (log) {
      glGetBufferParameteriv(GL_ARRAY_BUFFER, GL_BUFFER_MAPPED, &gl_mapped);
      glGetBufferParameteriv(GL_ARRAY_BUFFER, GL_BUFFER_SIZE, &gl_size);
      /* Without --debug-gpu nothing drains the GL error flag, so this code may predate the
       * failed mapping. Reading it here leaves the flag clear for the retry's own error. */
      stale_error = glGetError();
    }
    /* glBufferData replaces the data store and unmaps a buffer that was left mapped (GL 4.6
     * section 6.2), so a buffer stuck in the mapped state or a transient driver failure
     * recovers here instead of every later draw on this thread being skipped. */
    glBufferData(GL_ARRAY_BUFFER, store_size, nullptr, GL_DYNAMIC_DRAW);
    const size_t failed_offset = buffer_offset;
    buffer_offset = 0;
    void *data = glMapBufferRange(GL_ARRAY_BUFFER, buffer_offset, bytes_needed, access);
    if (log) {
      const GLenum retry_error = glGetError();
      CLOG_ERROR(&LOG,
                 "glMapBufferRange returned null. Driver: buffer mapped=%d, size=%d. Expected: "
                 "size=%zu, offset=%zu, bytes needed=%zu. Pending GL error 0x%x (a hint, it may "
                 "predate the call). Retry on fresh storage %s, GL error 0x%x. Immediate draws "
                 "whose mapping still fails are skipped; this is logged once per thread.",
                 gl_mapped,
                 gl_size,
                 store_size,
                 failed_offset,
                 bytes_needed,
                 stale_error,
                 data ? "recovered" : "failed",
                 retry_error);
    }
    if (data != nullptr) {
      map_retry_spent = false;
      return data;
    }
  }
  map_failed = true;
  map_scratch.resize((bytes_needed + sizeof(float) - 1) / sizeof(float));
  return map_scratch.data();
}

/* -------------------------------------------------------------------- */
/** \name Creation & Deletion
 * \{ */

GLImmediate::GLImmediate()
{
  glGenVertexArrays(1, &vao_id_);
  glBindVertexArray(vao_id_); /* Necessary for glObjectLabel. */

  buffer.buffer_size = DEFAULT_INTERNAL_BUFFER_SIZE;
  glGenBuffers(1, &buffer.vbo_id);
  glBindBuffer(GL_ARRAY_BUFFER, buffer.vbo_id);
  glBufferData(GL_ARRAY_BUFFER, buffer.buffer_size, nullptr, GL_DYNAMIC_DRAW);

  buffer_strict.buffer_size = DEFAULT_INTERNAL_BUFFER_SIZE;
  glGenBuffers(1, &buffer_strict.vbo_id);
  glBindBuffer(GL_ARRAY_BUFFER, buffer_strict.vbo_id);
  glBufferData(GL_ARRAY_BUFFER, buffer_strict.buffer_size, nullptr, GL_DYNAMIC_DRAW);

  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glBindVertexArray(0);

  debug::object_label(GL_VERTEX_ARRAY, vao_id_, "Immediate");
  debug::object_label(GL_BUFFER, buffer.vbo_id, "ImmediateVbo");
  debug::object_label(GL_BUFFER, buffer_strict.vbo_id, "ImmediateVboStrict");
}

GLImmediate::~GLImmediate()
{
  glDeleteVertexArrays(1, &vao_id_);

  glDeleteBuffers(1, &buffer.vbo_id);
  glDeleteBuffers(1, &buffer_strict.vbo_id);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Buffer management
 * \{ */

uchar *GLImmediate::begin()
{
  /* How many bytes do we need for this draw call? */
  const size_t bytes_needed = vertex_buffer_size(&vertex_format, vertex_len);
  /* Does the current buffer have enough room? */
  const size_t available_bytes = buffer_size() - buffer_offset();

#ifndef NDEBUG
  if (this->shader->is_polyline) {
    /* Silence error. These are bound inside `immEnd()`. */
    GLContext::get()->bound_ssbo_slots |= 1 << GPU_SSBO_POLYLINE_POS_BUF_SLOT;
    GLContext::get()->bound_ssbo_slots |= 1 << GPU_SSBO_POLYLINE_COL_BUF_SLOT;
    GLContext::get()->bound_ssbo_slots |= 1 << GPU_SSBO_INDEX_BUF_SLOT;
  }
#endif

  GL_CHECK_RESOURCES("Immediate");

  glBindBuffer(GL_ARRAY_BUFFER, vbo_id());

  bool recreate_buffer = false;
  if (bytes_needed > buffer_size()) {
    /* expand the internal buffer */
    buffer_size() = bytes_needed;
    recreate_buffer = true;
  }
  else if (bytes_needed < DEFAULT_INTERNAL_BUFFER_SIZE &&
           buffer_size() > DEFAULT_INTERNAL_BUFFER_SIZE)
  {
    /* shrink the internal buffer */
    buffer_size() = DEFAULT_INTERNAL_BUFFER_SIZE;
    recreate_buffer = true;
  }

  uint vert_alignment = vertex_format.stride;
  if (this->shader->is_polyline) {
    /* Polyline needs to bind the buffer as SSBO.
     * The start of the range needs to match the SSBO alignment requirements. */
    vert_alignment = ceil_to_multiple_u(vert_alignment, GPU_storage_buffer_alignment());
  }
  /* Ensure vertex data is aligned. Might waste a little space, but it's safe. */
  const uint pre_padding = padding(buffer_offset(), vert_alignment);

  if (!recreate_buffer && ((bytes_needed + pre_padding) <= available_bytes)) {
    buffer_offset() += pre_padding;
  }
  else {
    /* orphan this buffer & start with a fresh one */
    glBufferData(GL_ARRAY_BUFFER, buffer_size(), nullptr, GL_DYNAMIC_DRAW);
    buffer_offset() = 0;
  }

#ifndef NDEBUG
  {
    GLint bufsize;
    glGetBufferParameteriv(GL_ARRAY_BUFFER, GL_BUFFER_SIZE, &bufsize);
    BLI_assert(buffer_offset() + bytes_needed <= bufsize);
  }
#endif

  GLbitfield access = GL_MAP_WRITE_BIT | GL_MAP_UNSYNCHRONIZED_BIT;
  if (!strict_vertex_len) {
    access |= GL_MAP_FLUSH_EXPLICIT_BIT;
  }
  void *data = glMapBufferRange(GL_ARRAY_BUFFER, buffer_offset(), bytes_needed, access);
  /* MIXAR-2043: upstream asserts this in debug builds only, and the first immVertex* then
   * writes to address 0. */
  if (data == nullptr) {
    data = map_failure_fallback(buffer_size(), buffer_offset(), bytes_needed, access);
  }
  else {
    map_retry_spent = false;
  }

  bytes_mapped_ = bytes_needed;
  return static_cast<uchar *>(data);
}

void GLImmediate::end()
{
  BLI_assert(prim_type != GPU_PRIM_NONE); /* make sure we're between a Begin/End pair */

  if (map_failed) {
    /* MIXAR-2043: begin() wrote into scratch memory, nothing is mapped. */
    map_failed = false;
    return;
  }

  uint buffer_bytes_used = bytes_mapped_;
  if (!strict_vertex_len) {
    if (vertex_idx != vertex_len) {
      vertex_len = vertex_idx;
      buffer_bytes_used = vertex_buffer_size(&vertex_format, vertex_len);
      /* unused buffer bytes are available to the next immBegin */
    }
    /* tell OpenGL what range was modified so it doesn't copy the whole mapped range */
    glFlushMappedBufferRange(GL_ARRAY_BUFFER, 0, buffer_bytes_used);
  }
  glUnmapBuffer(GL_ARRAY_BUFFER);

  if (vertex_len == 0) {
    /* NOOP. Nothing to draw. */
  }
  else if (this->shader->is_polyline) {
    GLintptr offset = buffer_offset();
    GLenum target = GL_SHADER_STORAGE_BUFFER;
    glBindBufferRange(target, GPU_SSBO_POLYLINE_POS_BUF_SLOT, vbo_id(), offset, buffer_bytes_used);
    glBindBufferRange(target, GPU_SSBO_POLYLINE_COL_BUF_SLOT, vbo_id(), offset, buffer_bytes_used);
    /* Not used. Satisfy the binding. */
    glBindBufferRange(target, GPU_SSBO_INDEX_BUF_SLOT, vbo_id(), offset, buffer_bytes_used);

    this->polyline_draw_workaround(0);

#ifndef NDEBUG
    GLContext::get()->bound_ssbo_slots &= ~(1 << GPU_SSBO_POLYLINE_POS_BUF_SLOT);
    GLContext::get()->bound_ssbo_slots &= ~(1 << GPU_SSBO_POLYLINE_COL_BUF_SLOT);
    GLContext::get()->bound_ssbo_slots &= ~(1 << GPU_SSBO_INDEX_BUF_SLOT);
#endif
  }
  else {
    GLContext::get()->state_manager->apply_state();

    /* We convert the offset in vertex offset from the buffer's start.
     * This works because we added some padding to align the first vertex. */
    uint v_first = buffer_offset() / vertex_format.stride;
    GLVertArray::update_bindings(
        vao_id_, v_first, &vertex_format, reinterpret_cast<Shader *>(shader)->interface);

    /* Update matrices. */
    GPU_shader_bind(shader);

    glDrawArrays(to_gl(prim_type), 0, vertex_len);

    /* These lines are causing crash on startup on some old GPU + drivers.
     * They are not required so just comment them. (#55722) */
    // glBindBuffer(GL_ARRAY_BUFFER, 0);
    // glBindVertexArray(0);
  }

  buffer_offset() += buffer_bytes_used;
}

/** \} */

}  // namespace blender::gpu
