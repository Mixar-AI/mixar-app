/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup pygen
 *
 * `imbuf.mixar_movie_frames`: sample frames from a movie file for the agent's
 * context-folder video view. Pure imbuf/movie code — no Main, RNA, GPU or
 * window manager — so it is safe on a non-main Python thread; the GIL is
 * released around the FFmpeg work.
 */

#include <Python.h>

#include <algorithm>
#include <cstdint>
#include <string>
#include <vector>

#include "BLI_math_vector_types.hh"

#include "IMB_imbuf.hh"
#include "IMB_imbuf_enums.h"
#include "IMB_imbuf_types.hh"
#include "MOV_read.hh"

namespace blender {

namespace {

struct DecodedFrame {
  int index = 0, width = 0, height = 0;
  std::vector<uint8_t> rgba;
};

struct SampleResult {
  int frame_count = 0, width = 0, height = 0;
  float fps = 0.0f;
  std::vector<DecodedFrame> frames;
};

/** Closes the reader on every exit path. */
struct MovieHandle {
  MovieReader *anim;
  explicit MovieHandle(const char *filepath)
      : anim(MOV_open_file(filepath, ImBufFlags::Zero, 0, true, nullptr))
  {
  }
  MovieHandle(const MovieHandle &) = delete;
  MovieHandle &operator=(const MovieHandle &) = delete;
  ~MovieHandle()
  {
    if (anim) {
      MOV_close(anim);
    }
  }
};

/** One frame as top-down RGBA bytes no larger than `max_dim`; false if it did not decode. */
bool decode_frame(MovieReader *anim, const int index, const int max_dim, DecodedFrame &out)
{
  ImBuf *ibuf = MOV_decode_frame(anim, index, IMB_PROXY_NONE);
  if (ibuf == nullptr) {
    return false;
  }
  if (ibuf->byte_buffer.data == nullptr && ibuf->float_buffer.data != nullptr) {
    IMB_byte_from_float(ibuf); /* High bit-depth movies arrive as float. */
  }
  if (ibuf->byte_buffer.data == nullptr || ibuf->x <= 0 || ibuf->y <= 0) {
    IMB_freeImBuf(ibuf);
    return false;
  }
  const int longest = std::max(ibuf->x, ibuf->y);
  if (longest > max_dim) { /* Fit the longest edge, keep the aspect, never upscale. */
    const double scale = double(max_dim) / double(longest);
    const int2 size(std::max(1, int(ibuf->x * scale + 0.5)), std::max(1, int(ibuf->y * scale + 0.5)));
    IMB_scale(ibuf, size, IMBScaleFilter::Box, /*threaded=*/false);
  }
  IMB_flipy(ibuf); /* ImBuf rows are bottom-up; encoders expect the top row first. */
  out.index = index, out.width = ibuf->x, out.height = ibuf->y;
  const size_t byte_count = size_t(ibuf->x) * size_t(ibuf->y) * 4;
  out.rgba.assign(ibuf->byte_buffer.data, ibuf->byte_buffer.data + byte_count);
  IMB_freeImBuf(ibuf);
  return true;
}

/** Runs without the GIL. False = not a decodable movie; a frame that fails is skipped. */
bool sample_movie(const std::string &filepath,
                  std::vector<int> indices,
                  const int max_dim,
                  SampleResult &result)
{
  MovieHandle movie(filepath.c_str());
  /* Initialization is lazy: decoding the first frame opens the stream and
   * proves the file is a movie. That frame is reused when index 0 is wanted. */
  DecodedFrame first;
  if (movie.anim == nullptr || !decode_frame(movie.anim, 0, max_dim, first)) {
    return false;
  }
  result.frame_count = std::max(1, MOV_get_duration_frames(movie.anim));
  result.fps = MOV_get_fps(movie.anim);
  result.width = MOV_get_image_width(movie.anim);
  result.height = MOV_get_image_height(movie.anim);

  for (int &index : indices) {
    index = std::clamp(index, 0, result.frame_count - 1);
  }
  std::sort(indices.begin(), indices.end());
  indices.erase(std::unique(indices.begin(), indices.end()), indices.end());
  for (const int index : indices) {
    DecodedFrame frame;
    if (index == 0) {
      result.frames.push_back(std::move(first));
    }
    else if (decode_frame(movie.anim, index, max_dim, frame)) {
      result.frames.push_back(std::move(frame));
    }
  }
  return true;
}

PyDoc_STRVAR(
    py_movie_frames_doc,
    ".. function:: mixar_movie_frames(filepath, indices, max_dim)\n"
    "\n"
    "   Decode frames of a movie file as top-down RGBA bytes, each fitted to ``max_dim``\n"
    "   (16..4096) on its longest edge, aspect kept, never upscaled. ``indices`` are\n"
    "   0-based frame positions, clamped to the clip and de-duplicated.\n"
    "\n"
    "   :return: ``(frame_count, fps, width, height, frames)``; ``frames`` is a list of\n"
    "      ``(index, width, height, rgba_bytes)`` in ASCENDING index order, omitting\n"
    "      frames that failed to decode.\n"
    "   :rtype: tuple\n"
    "   :raises ValueError: when the file is not a decodable movie.\n");
PyObject *py_movie_frames(PyObject * /*self*/, PyObject *args)
{
  const char *filepath = nullptr;
  PyObject *indices_obj = nullptr;
  int max_dim = 0;
  if (!PyArg_ParseTuple(args, "sOi:mixar_movie_frames", &filepath, &indices_obj, &max_dim)) {
    return nullptr;
  }
  PyObject *seq = PySequence_Fast(indices_obj, "indices must be a sequence of ints");
  if (seq == nullptr) {
    return nullptr;
  }
  std::vector<int> indices;
  for (Py_ssize_t i = 0, count = PySequence_Fast_GET_SIZE(seq); i < count; i++) {
    const long value = PyLong_AsLong(PySequence_Fast_GET_ITEM(seq, i));
    if (value == -1 && PyErr_Occurred()) {
      Py_DECREF(seq);
      return nullptr;
    }
    indices.push_back(int(std::clamp<long>(value, 0, INT32_MAX)));
  }
  Py_DECREF(seq);

  const std::string path(filepath);
  SampleResult result;
  bool ok = false;
  Py_BEGIN_ALLOW_THREADS
  ok = sample_movie(path, std::move(indices), std::clamp(max_dim, 16, 4096), result);
  Py_END_ALLOW_THREADS
  if (!ok) {
    PyErr_SetString(PyExc_ValueError, "Not a decodable movie file");
    return nullptr;
  }

  PyObject *frames = PyList_New(Py_ssize_t(result.frames.size()));
  Py_ssize_t pos = 0;
  for (const DecodedFrame &frame : result.frames) {
    PyObject *data = PyBytes_FromStringAndSize(reinterpret_cast<const char *>(frame.rgba.data()),
                                               Py_ssize_t(frame.rgba.size()));
    /* "N" steals `data`; a null `data` makes BuildValue fail and clear it. */
    PyObject *item = Py_BuildValue("(iiiN)", frame.index, frame.width, frame.height, data);
    if (frames == nullptr || item == nullptr) {
      Py_XDECREF(item);
      Py_XDECREF(frames);
      return nullptr;
    }
    PyList_SET_ITEM(frames, pos++, item);
  }
  return Py_BuildValue(
      "(idiiN)", result.frame_count, double(result.fps), result.width, result.height, frames);
}

PyMethodDef mixar_movie_methods[] = {
    {"mixar_movie_frames", (PyCFunction)py_movie_frames, METH_VARARGS, py_movie_frames_doc},
    {nullptr, nullptr, 0, nullptr},
};

}  // namespace

void mixar_movie_register(PyObject *module)
{
  PyModule_AddFunctions(module, mixar_movie_methods);
}

}  // namespace blender
