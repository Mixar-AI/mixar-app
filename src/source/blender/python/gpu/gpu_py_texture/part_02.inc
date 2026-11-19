/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_format_doc,
    "Format of the texture.\n"
    "\n"
    ":type: str\n");
static PyObject *pygpu_texture_format_get(BPyGPUTexture *self, void * /*type*/)
{
  BPYGPU_TEXTURE_CHECK_OBJ(self);
  gpu::TextureFormat format = GPU_texture_format(self->tex);
  return PyUnicode_FromString(
      PyC_StringEnum_FindIDFromValue(pygpu_textureformat_items, int(format)));
}

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_extend_mode_x_doc,
    ".. method:: extend_mode_x(extend_mode='EXTEND', /)\n"
    "\n"
    "   Set texture sampling method for coordinates outside of the [0..1] uv range along the x "
    "axis.\n"
    "\n" BPYGPU_TEXTURE_EXTEND_MODE_ARG_DOC);
static PyObject *pygpu_texture_extend_mode_x(BPyGPUTexture *self, PyObject *value)
{
  BPYGPU_TEXTURE_CHECK_OBJ(self);

  PyC_StringEnum extend_mode = {pygpu_textureextendmode_items};
  if (!PyC_ParseStringEnum(value, &extend_mode)) {
    return nullptr;
  }

  GPU_texture_extend_mode_x(self->tex, GPUSamplerExtendMode(extend_mode.value_found));
  Py_RETURN_NONE;
}

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_extend_mode_y_doc,
    ".. method:: extend_mode_y(extend_mode='EXTEND', /)\n"
    "\n"
    "   Set texture sampling method for coordinates outside of the [0..1] uv range along the y "
    "axis.\n"
    "\n" BPYGPU_TEXTURE_EXTEND_MODE_ARG_DOC);
static PyObject *pygpu_texture_extend_mode_y(BPyGPUTexture *self, PyObject *value)
{
  BPYGPU_TEXTURE_CHECK_OBJ(self);

  PyC_StringEnum extend_mode = {pygpu_textureextendmode_items};
  if (!PyC_ParseStringEnum(value, &extend_mode)) {
    return nullptr;
  }

  GPU_texture_extend_mode_y(self->tex, GPUSamplerExtendMode(extend_mode.value_found));
  Py_RETURN_NONE;
}

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_extend_mode_doc,
    ".. method:: extend_mode(extend_mode='EXTEND', /)\n"
    "\n"
    "   Set texture sampling method for coordinates outside of the [0..1] uv range along\n"
    "   both the x and y axis.\n"
    "\n" BPYGPU_TEXTURE_EXTEND_MODE_ARG_DOC);
static PyObject *pygpu_texture_extend_mode(BPyGPUTexture *self, PyObject *value)
{
  BPYGPU_TEXTURE_CHECK_OBJ(self);

  PyC_StringEnum extend_mode = {pygpu_textureextendmode_items};
  if (!PyC_ParseStringEnum(value, &extend_mode)) {
    return nullptr;
  }

  GPU_texture_extend_mode(self->tex, GPUSamplerExtendMode(extend_mode.value_found));
  Py_RETURN_NONE;
}

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_filter_mode_doc,
    ".. method:: filter_mode(use_filter)\n"
    "\n"
    "   Set texture filter usage.\n"
    "\n"
    "   :param use_filter: If set to true, the texture will use linear interpolation between "
    "neighboring texels.\n"
    "   :type use_filter: bool\n");
static PyObject *pygpu_texture_filter_mode(BPyGPUTexture *self, PyObject *value)
{
  BPYGPU_TEXTURE_CHECK_OBJ(self);

  bool use_filter;
  if (!PyC_ParseBool(value, &use_filter)) {
    return nullptr;
  }

  GPU_texture_filter_mode(self->tex, use_filter);
  Py_RETURN_NONE;
}

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_mipmap_mode_doc,
    ".. method:: mipmap_mode(use_mipmap=True, use_filter=True)\n"
    "\n"
    "   Set texture filter and mip-map usage.\n"
    "\n"
    "   :param use_mipmap: If set to true, the texture will use mip-mapping as anti-aliasing "
    "method.\n"
    "   :type use_mipmap: bool\n"
    "   :param use_filter: If set to true, the texture will use linear interpolation between "
    "neighboring texels.\n"
    "   :type use_filter: bool\n");
static PyObject *pygpu_texture_mipmap_mode(BPyGPUTexture *self, PyObject *args, PyObject *kwds)
{
  BPYGPU_TEXTURE_CHECK_OBJ(self);

  bool use_mipmap = true;
  bool use_filter = true;
  static const char *_keywords[] = {"use_mipmap", "use_filter"};
  static _PyArg_Parser _parser = {
      "|$" /* Optional, keyword only arguments. */
      "b"  /* `use_mipmap` */
      "b"  /* `use_filter` */
      ":mipmap_mode",
      _keywords,
      nullptr,
  };

  if (!_PyArg_ParseTupleAndKeywordsFast(args, kwds, &_parser, &use_mipmap, &use_filter)) {
    return nullptr;
  }

  GPU_texture_mipmap_mode(self->tex, use_mipmap, use_filter);
  Py_RETURN_NONE;
}

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_anisotropic_filter_doc,
    ".. method:: anisotropic_filter(use_anisotropic)\n"
    "\n"
    "   Set anisotropic filter usage. This only has effect if mipmapping is enabled.\n"
    "\n"
    "   :param use_anisotropic: If set to true, the texture will use anisotropic filtering.\n"
    "   :type use_anisotropic: bool\n");
static PyObject *pygpu_texture_anisotropic_filter(BPyGPUTexture *self, PyObject *value)
{
  BPYGPU_TEXTURE_CHECK_OBJ(self);

  bool use_anisotropic;
  if (!PyC_ParseBool(value, &use_anisotropic)) {
    return nullptr;
  }

  GPU_texture_anisotropic_filter(self->tex, use_anisotropic);
  Py_RETURN_NONE;
}

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_clear_doc,
    ".. method:: clear(format='FLOAT', value=(0.0, 0.0, 0.0, 1.0))\n"
    "\n"
    "   Fill texture with specific value.\n"
    "\n"
    "   :param format: The format that describes the content of a single item.\n"
    "      ``UINT_24_8`` is deprecated, use ``FLOAT`` instead.\n"
    "   :type format: " PYDOC_DATAFORMAT_LITERAL
    "\n"
    "   :param value: Sequence each representing the value to fill. Sizes 1..4 are supported.\n"
    "   :type value: Sequence[float] | Sequence[int]\n");
static PyObject *pygpu_texture_clear(BPyGPUTexture *self, PyObject *args, PyObject *kwds)
{
  BPYGPU_TEXTURE_CHECK_OBJ(self);
  PyC_StringEnum pygpu_dataformat = {bpygpu_dataformat_items};
  union {
    int i[4];
    float f[4];
    char c[4];
  } values;

  PyObject *py_values;

  static const char *_keywords[] = {"format", "value", nullptr};
  static _PyArg_Parser _parser = {
      "$"  /* Keyword only arguments. */
      "O&" /* `format` */
      "O"  /* `value` */
      ":clear",
      _keywords,
      nullptr,
  };
  if (!_PyArg_ParseTupleAndKeywordsFast(
          args, kwds, &_parser, PyC_ParseStringEnum, &pygpu_dataformat, &py_values))
  {
    return nullptr;
  }
  if (pygpu_dataformat.value_found == GPU_DATA_UINT_24_8_DEPRECATED) {
    PyErr_WarnEx(PyExc_DeprecationWarning, "`UINT_24_8` is deprecated, use `FLOAT` instead", 1);
  }

  int shape = PySequence_Size(py_values);
  if (shape == -1) {
    return nullptr;
  }

  if (shape > 4) {
    PyErr_SetString(PyExc_AttributeError, "too many dimensions, max is 4");
    return nullptr;
  }

  if (shape != 1 &&
      ELEM(pygpu_dataformat.value_found, GPU_DATA_UINT_24_8_DEPRECATED, GPU_DATA_10_11_11_REV))
  {
    PyErr_SetString(PyExc_AttributeError,
                    "`UINT_24_8` and `10_11_11_REV` only support single values");
    return nullptr;
  }

  memset(&values, 0, sizeof(values));
  if (PyC_AsArray(&values,
                  (pygpu_dataformat.value_found == GPU_DATA_FLOAT) ? sizeof(*values.f) :
                                                                     sizeof(*values.i),
                  py_values,
                  shape,
                  (pygpu_dataformat.value_found == GPU_DATA_FLOAT) ? &PyFloat_Type : &PyLong_Type,
                  "clear") == -1)
  {
    return nullptr;
  }

  if (pygpu_dataformat.value_found == GPU_DATA_UBYTE) {
    /* Convert to byte. */
    values.c[0] = values.i[0];
    values.c[1] = values.i[1];
    values.c[2] = values.i[2];
    values.c[3] = values.i[3];
  }

  GPU_texture_clear(self->tex, eGPUDataFormat(pygpu_dataformat.value_found), &values);
  Py_RETURN_NONE;
}

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_read_doc,
    ".. method:: read()\n"
    "\n"
    "   Creates a buffer with the value of all pixels.\n"
    "\n"
    "   :return: The Buffer with the read pixels.\n"
    "   :rtype: :class:`gpu.types.Buffer`\n");
static PyObject *pygpu_texture_read(BPyGPUTexture *self)
{
  BPYGPU_TEXTURE_CHECK_OBJ(self);
  gpu::TextureFormat tex_format = GPU_texture_format(self->tex);

  /* #GPU_texture_read is restricted in combining 'data_format' with 'tex_format'.
   * So choose data_format here. */
  eGPUDataFormat best_data_format;
  switch (tex_format) {
    case gpu::TextureFormat::UNORM_16_DEPTH:
    case gpu::TextureFormat::SFLOAT_32_DEPTH:
    case gpu::TextureFormat::SFLOAT_32_DEPTH_UINT_8:
      best_data_format = GPU_DATA_FLOAT;
      break;
    case gpu::TextureFormat::UINT_8:
    case gpu::TextureFormat::UINT_16:
    case gpu::TextureFormat::UINT_16_16:
    case gpu::TextureFormat::UINT_32:
      best_data_format = GPU_DATA_UINT;
      break;
    case gpu::TextureFormat::SINT_16_16:
    case gpu::TextureFormat::SINT_16:
      best_data_format = GPU_DATA_INT;
      break;
    case gpu::TextureFormat::UNORM_8:
    case gpu::TextureFormat::UNORM_8_8:
    case gpu::TextureFormat::UNORM_8_8_8_8:
    case gpu::TextureFormat::UINT_8_8_8_8:
    case gpu::TextureFormat::SRGBA_8_8_8_8:
      best_data_format = GPU_DATA_UBYTE;
      break;
    case gpu::TextureFormat::UFLOAT_11_11_10:
      best_data_format = GPU_DATA_10_11_11_REV;
      break;
    default:
      best_data_format = GPU_DATA_FLOAT;
      break;
  }

  void *buf = GPU_texture_read(self->tex, best_data_format, 0);
  const Py_ssize_t component_len = GPU_texture_component_len(tex_format);
  Py_ssize_t shape[4];
  int shape_len;
  if (GPU_texture_dimensions(self->tex) == 3) {
    shape[0] = GPU_texture_depth(self->tex);
    shape[1] = GPU_texture_height(self->tex);
    shape[2] = GPU_texture_width(self->tex);
    shape[3] = component_len;
    shape_len = (component_len == 1) ? 3 : 4;
  }
  else {
    shape[0] = GPU_texture_height(self->tex);
    shape[1] = GPU_texture_width(self->tex);
    shape[2] = component_len;
    shape_len = (component_len == 1) ? 2 : 3;
  }
  return reinterpret_cast<PyObject *>(
      BPyGPU_Buffer_CreatePyObject(best_data_format, shape, shape_len, buf));
}

#ifdef BPYGPU_USE_GPUOBJ_FREE_METHOD
PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_free_doc,
    ".. method:: free()\n"
    "\n"
    "   Free the texture object.\n"
    "   The texture object will no longer be accessible.\n");
static PyObject *pygpu_texture_free(BPyGPUTexture *self)
{
  BPYGPU_TEXTURE_CHECK_OBJ(self);

  GPU_texture_free(self->tex);
  self->tex = nullptr;
  Py_RETURN_NONE;
}
#endif

static void BPyGPUTexture__tp_dealloc(BPyGPUTexture *self)
{
  if (self->tex) {
#ifndef GPU_NO_USE_PY_REFERENCES
    GPU_texture_py_reference_set(self->tex, nullptr);
#endif
    GPU_texture_free(self->tex);
  }
  Py_TYPE(self)->tp_free(reinterpret_cast<PyObject *>(self));
}
