/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup bpygpu
 *
 * This file defines the texture functionalities of the 'gpu' module
 *
 * - Use `bpygpu_` for local API.
 * - Use `BPyGPU` for public API.
 */

#include <Python.h>

#include "BLI_math_base_c.hh"
#include "BLI_string_utf8.hh"

#include "DNA_image_types.h"

#include "GPU_capabilities.hh"
#include "GPU_context.hh"
#include "GPU_texture.hh"

#include "BKE_global.hh"
#include "BKE_image.hh"
#include "BKE_image_gpu.hh"

#include "../generic/py_capi_utils.hh"
#include "../generic/python_compat.hh" /* IWYU pragma: keep. */

#include "gpu_py.hh"
#include "gpu_py_buffer.hh"

#include "gpu_py_texture.hh" /* own include */

/* Docstring Literal type for texture formats. */

#define PYDOC_TEX_FORMAT_LITERAL \
  "Literal[" \
  "'RGBA8UI', " \
  "'RGBA8I', " \
  "'RGBA8', " \
  "'RGBA32UI', " \
  "'RGBA32I', " \
  "'RGBA32F', " \
  "'RGBA16UI', " \
  "'RGBA16I', " \
  "'RGBA16F', " \
  "'RGBA16', " \
  "'RG8UI', " \
  "'RG8I', " \
  "'RG8', " \
  "'RG32UI', " \
  "'RG32I', " \
  "'RG32F', " \
  "'RG16UI', " \
  "'RG16I', " \
  "'RG16F', " \
  "'RG16', " \
  "'R8UI', " \
  "'R8I', " \
  "'R8', " \
  "'R32UI', " \
  "'R32I', " \
  "'R32F', " \
  "'R16UI', " \
  "'R16I', " \
  "'R16F', " \
  "'R16', " \
  "'R11F_G11F_B10F', " \
  "'DEPTH32F_STENCIL8', " \
  "'DEPTH24_STENCIL8', " \
  "'SRGB8_A8', " \
  "'RGB16F', " \
  "'SRGB8_A8_DXT1', " \
  "'SRGB8_A8_DXT3', " \
  "'SRGB8_A8_DXT5', " \
  "'RGBA8_DXT1', " \
  "'RGBA8_DXT3', " \
  "'RGBA8_DXT5', " \
  "'DEPTH_COMPONENT32F', " \
  "'DEPTH_COMPONENT24', " \
  "'DEPTH_COMPONENT16']"

namespace blender {

/* -------------------------------------------------------------------- */
/** \name GPUTexture Common Utilities
 * \{ */

const PyC_StringEnumItems pygpu_textureformat_items[] = {
    {int(gpu::TextureFormat::UINT_8_8_8_8), "RGBA8UI"},
    {int(gpu::TextureFormat::SINT_8_8_8_8), "RGBA8I"},
    {int(gpu::TextureFormat::UNORM_8_8_8_8), "RGBA8"},
    {int(gpu::TextureFormat::UINT_32_32_32_32), "RGBA32UI"},
    {int(gpu::TextureFormat::SINT_32_32_32_32), "RGBA32I"},
    {int(gpu::TextureFormat::SFLOAT_32_32_32_32), "RGBA32F"},
    {int(gpu::TextureFormat::UINT_16_16_16_16), "RGBA16UI"},
    {int(gpu::TextureFormat::SINT_16_16_16_16), "RGBA16I"},
    {int(gpu::TextureFormat::SFLOAT_16_16_16_16), "RGBA16F"},
    {int(gpu::TextureFormat::UNORM_16_16_16_16), "RGBA16"},
    {int(gpu::TextureFormat::UINT_8_8), "RG8UI"},
    {int(gpu::TextureFormat::SINT_8_8), "RG8I"},
    {int(gpu::TextureFormat::UNORM_8_8), "RG8"},
    {int(gpu::TextureFormat::UINT_32_32), "RG32UI"},
    {int(gpu::TextureFormat::SINT_32_32), "RG32I"},
    {int(gpu::TextureFormat::SFLOAT_32_32), "RG32F"},
    {int(gpu::TextureFormat::UINT_16_16), "RG16UI"},
    {int(gpu::TextureFormat::SINT_16_16), "RG16I"},
    {int(gpu::TextureFormat::SFLOAT_16_16), "RG16F"},
    {int(gpu::TextureFormat::UNORM_16_16), "RG16"},
    {int(gpu::TextureFormat::UINT_8), "R8UI"},
    {int(gpu::TextureFormat::SINT_8), "R8I"},
    {int(gpu::TextureFormat::UNORM_8), "R8"},
    {int(gpu::TextureFormat::UINT_32), "R32UI"},
    {int(gpu::TextureFormat::SINT_32), "R32I"},
    {int(gpu::TextureFormat::SFLOAT_32), "R32F"},
    {int(gpu::TextureFormat::UINT_16), "R16UI"},
    {int(gpu::TextureFormat::SINT_16), "R16I"},
    {int(gpu::TextureFormat::SFLOAT_16), "R16F"},
    {int(gpu::TextureFormat::UNORM_16), "R16"},
    {int(gpu::TextureFormat::UFLOAT_11_11_10), "R11F_G11F_B10F"},
    {int(gpu::TextureFormat::SFLOAT_32_DEPTH_UINT_8), "DEPTH32F_STENCIL8"},
    {GPU_DEPTH24_STENCIL8_DEPRECATED, "DEPTH24_STENCIL8"},
    {int(gpu::TextureFormat::SRGBA_8_8_8_8), "SRGB8_A8"},
    {int(gpu::TextureFormat::SFLOAT_16_16_16), "RGB16F"},
    {int(gpu::TextureFormat::SRGB_DXT1), "SRGB8_A8_DXT1"},
    {int(gpu::TextureFormat::SRGB_DXT3), "SRGB8_A8_DXT3"},
    {int(gpu::TextureFormat::SRGB_DXT5), "SRGB8_A8_DXT5"},
    {int(gpu::TextureFormat::SNORM_DXT1), "RGBA8_DXT1"},
    {int(gpu::TextureFormat::SNORM_DXT3), "RGBA8_DXT3"},
    {int(gpu::TextureFormat::SNORM_DXT5), "RGBA8_DXT5"},
    {int(gpu::TextureFormat::SFLOAT_32_DEPTH), "DEPTH_COMPONENT32F"},
    {GPU_DEPTH_COMPONENT24_DEPRECATED, "DEPTH_COMPONENT24"},
    {int(gpu::TextureFormat::UNORM_16_DEPTH), "DEPTH_COMPONENT16"},
    {0, nullptr},
};

const PyC_StringEnumItems pygpu_textureextendmode_items[] = {
    {int(GPUSamplerExtendMode::GPU_SAMPLER_EXTEND_MODE_EXTEND), "EXTEND"},
    {int(GPUSamplerExtendMode::GPU_SAMPLER_EXTEND_MODE_REPEAT), "REPEAT"},
    {int(GPUSamplerExtendMode::GPU_SAMPLER_EXTEND_MODE_MIRRORED_REPEAT), "MIRRORED_REPEAT"},
    {int(GPUSamplerExtendMode::GPU_SAMPLER_EXTEND_MODE_CLAMP_TO_BORDER), "CLAMP_TO_BORDER"},
    {0, nullptr},
};

static int pygpu_texture_valid_check(BPyGPUTexture *bpygpu_tex)
{
  if (bpygpu_tex->tex == nullptr) [[unlikely]] {
    PyErr_SetString(PyExc_ReferenceError,
#ifdef BPYGPU_USE_GPUOBJ_FREE_METHOD
                    "GPU texture was freed, no further access is valid"
#else
                    "GPU texture: internal error"
#endif
    );

    return -1;
  }
  return 0;
}

#define BPYGPU_TEXTURE_CHECK_OBJ(bpygpu) \
  { \
    if (pygpu_texture_valid_check(bpygpu) == -1) [[unlikely]] { \
      return nullptr; \
    } \
  } \
  ((void)0)

/** \} */

/* -------------------------------------------------------------------- */
/** \name GPUTexture Type
 * \{ */

#define BPYGPU_TEXTURE_EXTEND_MODE_ARG_DOC \
  "   :param extend_mode: the specified extent mode.\n" \
  "   :type extend_mode: Literal['EXTEND', 'REPEAT', 'MIRRORED_REPEAT', 'CLAMP_TO_BORDER']\n";

/**
 * Safe-guard against the reported 2D/3D texture size limits.
 *
 * Passing this check does not guarantee the texture can be created. Other limits and available
 * memory also apply. Failing the check means the request is definitely out of range for this
 * device.
 *
 * \return true when the requested size is within limits. Otherwise false, with a message
 * written to \a err_out.
 */
static bool pygpu_texture_size_check(const int size[3],
                                     const int len,
                                     const bool is_cubemap,
                                     char *err_out,
                                     const size_t err_out_size)
{
  const bool is_3d = (len == 3);
  const int limit = is_3d ? GPU_max_texture_3d_size() : GPU_max_texture_size();
  /* Cubemaps are created from a single dimension (the face size). */
  const int dims = is_cubemap ? 1 : len;

  for (int i = 0; i < dims; i++) {
    if (size[i] <= limit) {
      continue;
    }
    if (is_3d) {
      BLI_snprintf_utf8(err_out,
                        err_out_size,
                        "3D texture of size %dx%dx%d exceeds the GPU limit of %d per axis",
                        size[0],
                        size[1],
                        size[2],
                        limit);
    }
    else if (is_cubemap) {
      BLI_snprintf_utf8(err_out,
                        err_out_size,
                        "Cubemap of face size %d exceeds the GPU limit of %d",
                        size[0],
                        limit);
    }
    else if (len == 2) {
      BLI_snprintf_utf8(err_out,
                        err_out_size,
                        "2D texture of size %dx%d exceeds the GPU limit of %d",
                        size[0],
                        size[1],
                        limit);
    }
    else {
      BLI_snprintf_utf8(err_out,
                        err_out_size,
                        "1D texture of size %d exceeds the GPU limit of %d",
                        size[0],
                        limit);
    }
    return false;
  }
  return true;
}

static PyObject *pygpu_texture__tp_new(PyTypeObject * /*self*/, PyObject *args, PyObject *kwds)
{
  BPYGPU_IS_INIT_OR_ERROR_OBJ;

  PyObject *py_size;
  int size[3] = {1, 1, 1};
  int layers = 0;
  int is_cubemap = false;
  PyC_StringEnum pygpu_textureformat = {pygpu_textureformat_items,
                                        int(gpu::TextureFormat::UNORM_8_8_8_8)};
  BPyGPUBuffer *pybuffer_obj = nullptr;
  PyC_TypeOrNone pybuffer_or_none = PyC_TYPE_OR_NONE_INIT(&BPyGPU_BufferType, &pybuffer_obj);
  char err_out[256];
  STRNCPY_UTF8(err_out,
               (G.debug & G_DEBUG_GPU) ?
                   "the driver could not create this texture; see the console for details" :
                   "the driver could not create this texture; run with --debug-gpu for details");

  static const char *_keywords[] = {"size", "layers", "is_cubemap", "format", "data", nullptr};
  static _PyArg_Parser _parser = {
      "O"  /* `size` */
      "|$" /* Optional, keyword only arguments. */
      "i"  /* `layers` */
      "p"  /* `is_cubemap` */
      "O&" /* `format` */
      "O&" /* `data` */
      ":GPUTexture.__new__",
      _keywords,
      nullptr,
  };
  if (!_PyArg_ParseTupleAndKeywordsFast(args,
                                        kwds,
                                        &_parser,
                                        &py_size,
                                        &layers,
                                        &is_cubemap,
                                        PyC_ParseStringEnum,
                                        &pygpu_textureformat,
                                        PyC_ParseTypeOrNone,
                                        &pybuffer_or_none))
  {
    return nullptr;
  }

  if (pygpu_textureformat.value_found == GPU_DEPTH24_STENCIL8_DEPRECATED) {
    pygpu_textureformat.value_found = int(gpu::TextureFormat::SFLOAT_32_DEPTH_UINT_8);
    PyErr_WarnEx(
        PyExc_DeprecationWarning, "'DEPTH24_STENCIL8' is deprecated. Use 'DEPTH32F_STENCIL8'.", 1);
  }
  if (pygpu_textureformat.value_found == GPU_DEPTH_COMPONENT24_DEPRECATED) {
    pygpu_textureformat.value_found = int(gpu::TextureFormat::SFLOAT_32_DEPTH);
    PyErr_WarnEx(PyExc_DeprecationWarning,
                 "'DEPTH_COMPONENT24' is deprecated. Use 'DEPTH_COMPONENT32F'.",
                 1);
  }

  int len = 1;
  if (PySequence_Check(py_size)) {
    len = PySequence_Size(py_size);
    if ((len < 1) || (len > 3)) {
      PyErr_Format(PyExc_ValueError,
                   "GPUTexture.__new__: \"size\" must be between 1 and 3 in length (got %d)",
                   len);
      return nullptr;
    }
    if (PyC_AsArray(size, sizeof(*size), py_size, len, &PyLong_Type, "GPUTexture.__new__") == -1) {
      return nullptr;
    }
  }
  else if (PyLong_Check(py_size)) {
    size[0] = PyLong_AsLong(py_size);
  }
  else {
    PyErr_SetString(PyExc_ValueError, "GPUTexture.__new__: Expected an int or tuple as first arg");
    return nullptr;
  }

  void *data = nullptr;
  if (pybuffer_obj) {
    if (pybuffer_obj->format != GPU_DATA_FLOAT) {
      PyErr_SetString(PyExc_ValueError,
                      "GPUTexture.__new__: Only Buffer of format `FLOAT` is currently supported");
      return nullptr;
    }

    int component_len = GPU_texture_component_len(
        gpu::TextureFormat(pygpu_textureformat.value_found));
    int component_size_expected = sizeof(float);
    size_t data_space_expected = size_t(size[0]) * size[1] * size[2] * max_ii(1, layers) *
                                 component_len * component_size_expected;
    if (is_cubemap) {
      data_space_expected *= 6 * size[0];
    }

    if (bpygpu_Buffer_size(pybuffer_obj) < data_space_expected) {
      PyErr_SetString(PyExc_ValueError, "GPUTexture.__new__: Buffer size smaller than requested");
      return nullptr;
    }
    data = pybuffer_obj->buf.as_void;
  }

  gpu::Texture *tex = nullptr;
  if (is_cubemap && len != 1) {
    STRNCPY_UTF8(err_out, "Cubemaps use a single dimension, not a tuple");
  }
  else if (size[0] < 1 || size[1] < 1 || size[2] < 1) {
    STRNCPY_UTF8(err_out, "Texture dimensions must be at least 1");
  }
  else if (layers && len == 3) {
    STRNCPY_UTF8(err_out, "3D textures do not support layers");
  }
  else if (!GPU_context_active_get()) {
    STRNCPY_UTF8(err_out, "No active GPU context found");
  }
  else if (!pygpu_texture_size_check(size, len, is_cubemap, err_out, sizeof(err_out))) {
    /* Specific message written by pygpu_texture_size_check(). */
  }
  else {
    const char *name = "python_texture";
    eGPUTextureUsage usage = GPU_TEXTURE_USAGE_GENERAL;
    if (is_cubemap) {
      if (layers) {
        tex = GPU_texture_create_cube_array(name,
                                            size[0],
                                            layers,
                                            1,
                                            gpu::TextureFormat(pygpu_textureformat.value_found),
                                            usage,
                                            static_cast<const float *>(data));
      }
      else {
        tex = GPU_texture_create_cube(name,
                                      size[0],
                                      1,
                                      gpu::TextureFormat(pygpu_textureformat.value_found),
                                      usage,
                                      static_cast<const float *>(data));
      }
    }
    else if (layers) {
      if (len == 2) {
        tex = GPU_texture_create_2d_array(name,
                                          size[0],
                                          size[1],
                                          layers,
                                          1,
                                          gpu::TextureFormat(pygpu_textureformat.value_found),
                                          usage,
                                          static_cast<const float *>(data));
      }
      else {
        tex = GPU_texture_create_1d_array(name,
                                          size[0],
                                          layers,
                                          1,
                                          gpu::TextureFormat(pygpu_textureformat.value_found),
                                          usage,
                                          static_cast<const float *>(data));
      }
    }
    else if (len == 3) {
      tex = GPU_texture_create_3d(name,
                                  size[0],
                                  size[1],
                                  size[2],
                                  1,
                                  gpu::TextureFormat(pygpu_textureformat.value_found),
                                  usage,
                                  data);
    }
    else if (len == 2) {
      tex = GPU_texture_create_2d(name,
                                  size[0],
                                  size[1],
                                  1,
                                  gpu::TextureFormat(pygpu_textureformat.value_found),
                                  usage,
                                  static_cast<const float *>(data));
    }
    else {
      tex = GPU_texture_create_1d(name,
                                  size[0],
                                  1,
                                  gpu::TextureFormat(pygpu_textureformat.value_found),
                                  usage,
                                  static_cast<const float *>(data));
    }
  }

  if (tex == nullptr) {
    PyErr_Format(PyExc_RuntimeError, "gpu.texture.new(...) failed with '%s'", err_out);
    return nullptr;
  }

  return BPyGPUTexture_CreatePyObject(tex, false);
}

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_width_doc,
    "Width of the texture.\n"
    "\n"
    ":type: int\n");
static PyObject *pygpu_texture_width_get(BPyGPUTexture *self, void * /*type*/)
{
  BPYGPU_TEXTURE_CHECK_OBJ(self);
  return PyLong_FromLong(GPU_texture_width(self->tex));
}

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_height_doc,
    "Height of the texture.\n"
    "\n"
    ":type: int\n");
static PyObject *pygpu_texture_height_get(BPyGPUTexture *self, void * /*type*/)
{
  BPYGPU_TEXTURE_CHECK_OBJ(self);
  return PyLong_FromLong(GPU_texture_height(self->tex));
}
