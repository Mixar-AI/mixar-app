
static PyGetSetDef pygpu_texture__tp_getseters[] = {
    {"width",
     reinterpret_cast<getter>(pygpu_texture_width_get),
     static_cast<setter>(nullptr),
     pygpu_texture_width_doc,
     nullptr},
    {"height",
     reinterpret_cast<getter>(pygpu_texture_height_get),
     static_cast<setter>(nullptr),
     pygpu_texture_height_doc,
     nullptr},
    {"format",
     reinterpret_cast<getter>(pygpu_texture_format_get),
     static_cast<setter>(nullptr),
     pygpu_texture_format_doc,
     nullptr},
    {nullptr, nullptr, nullptr, nullptr, nullptr} /* Sentinel */
};

#ifdef __GNUC__
#  ifdef __clang__
#    pragma clang diagnostic push
#    pragma clang diagnostic ignored "-Wcast-function-type"
#  else
#    pragma GCC diagnostic push
#    pragma GCC diagnostic ignored "-Wcast-function-type"
#  endif
#endif

static PyMethodDef pygpu_texture__tp_methods[] = {
    {"clear",
     reinterpret_cast<PyCFunction>(pygpu_texture_clear),
     METH_VARARGS | METH_KEYWORDS,
     pygpu_texture_clear_doc},
    {"read",
     reinterpret_cast<PyCFunction>(pygpu_texture_read),
     METH_NOARGS,
     pygpu_texture_read_doc},
#ifdef BPYGPU_USE_GPUOBJ_FREE_METHOD
    {"free", (PyCFunction)pygpu_texture_free, METH_NOARGS, pygpu_texture_free_doc},
#endif
    {"extend_mode_x",
     reinterpret_cast<PyCFunction>(pygpu_texture_extend_mode_x),
     METH_O,
     pygpu_texture_extend_mode_x_doc},
    {"extend_mode_y",
     reinterpret_cast<PyCFunction>(pygpu_texture_extend_mode_y),
     METH_O,
     pygpu_texture_extend_mode_y_doc},
    {"extend_mode",
     reinterpret_cast<PyCFunction>(pygpu_texture_extend_mode),
     METH_O,
     pygpu_texture_extend_mode_doc},
    {"filter_mode",
     reinterpret_cast<PyCFunction>(pygpu_texture_filter_mode),
     METH_O,
     pygpu_texture_filter_mode_doc},
    {"mipmap_mode",
     reinterpret_cast<PyCFunction>(pygpu_texture_mipmap_mode),
     METH_VARARGS | METH_KEYWORDS,
     pygpu_texture_mipmap_mode_doc},
    {"anisotropic_filter",
     reinterpret_cast<PyCFunction>(pygpu_texture_anisotropic_filter),
     METH_O,
     pygpu_texture_anisotropic_filter_doc},
    {nullptr, nullptr, 0, nullptr},
};

#ifdef __GNUC__
#  ifdef __clang__
#    pragma clang diagnostic pop
#  else
#    pragma GCC diagnostic pop
#  endif
#endif

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture__tp_doc,
    ".. class:: GPUTexture\n"
    "\n"
    "   This object gives access to GPU textures.\n"
    "\n"
    "   .. method:: __init__(size, *, layers=0, is_cubemap=False, format='RGBA8', data=None)\n"
    "\n"
    "      :param size: Dimensions of the texture 1D, 2D, 3D or cubemap.\n"
    "      :type size: int | Sequence[int]\n"
    "      :param layers: Number of layers in texture array or number of cubemaps in cubemap "
    "array\n"
    "      :type layers: int\n"
    "      :param is_cubemap: Indicates the creation of a cubemap texture.\n"
    "      :type is_cubemap: bool\n"
    "      :param format: Internal data format inside GPU memory.\n"
    "         ``DEPTH24_STENCIL8`` is deprecated, use ``DEPTH32F_STENCIL8``.\n"
    "         ``DEPTH_COMPONENT24`` is deprecated, use ``DEPTH_COMPONENT32F``.\n"
    "      :type format: " PYDOC_TEX_FORMAT_LITERAL
    "\n"
    "      :param data: Buffer object to fill the texture.\n"
    "      :type data: :class:`gpu.types.Buffer` | None\n");
PyTypeObject BPyGPUTexture_Type = {
    /*ob_base*/ PyVarObject_HEAD_INIT(nullptr, 0)
    /*tp_name*/ "GPUTexture",
    /*tp_basicsize*/ sizeof(BPyGPUTexture),
    /*tp_itemsize*/ 0,
    /*tp_dealloc*/ reinterpret_cast<destructor>(BPyGPUTexture__tp_dealloc),
    /*tp_vectorcall_offset*/ 0,
    /*tp_getattr*/ nullptr,
    /*tp_setattr*/ nullptr,
    /*tp_as_async*/ nullptr,
    /*tp_repr*/ nullptr,
    /*tp_as_number*/ nullptr,
    /*tp_as_sequence*/ nullptr,
    /*tp_as_mapping*/ nullptr,
    /*tp_hash*/ nullptr,
    /*tp_call*/ nullptr,
    /*tp_str*/ nullptr,
    /*tp_getattro*/ nullptr,
    /*tp_setattro*/ nullptr,
    /*tp_as_buffer*/ nullptr,
    /*tp_flags*/ Py_TPFLAGS_DEFAULT,
    /*tp_doc*/ pygpu_texture__tp_doc,
    /*tp_traverse*/ nullptr,
    /*tp_clear*/ nullptr,
    /*tp_richcompare*/ nullptr,
    /*tp_weaklistoffset*/ 0,
    /*tp_iter*/ nullptr,
    /*tp_iternext*/ nullptr,
    /*tp_methods*/ pygpu_texture__tp_methods,
    /*tp_members*/ nullptr,
    /*tp_getset*/ pygpu_texture__tp_getseters,
    /*tp_base*/ nullptr,
    /*tp_dict*/ nullptr,
    /*tp_descr_get*/ nullptr,
    /*tp_descr_set*/ nullptr,
    /*tp_dictoffset*/ 0,
    /*tp_init*/ nullptr,
    /*tp_alloc*/ nullptr,
    /*tp_new*/ pygpu_texture__tp_new,
    /*tp_free*/ nullptr,
    /*tp_is_gc*/ nullptr,
    /*tp_bases*/ nullptr,
    /*tp_mro*/ nullptr,
    /*tp_cache*/ nullptr,
    /*tp_subclasses*/ nullptr,
    /*tp_weaklist*/ nullptr,
    /*tp_del*/ nullptr,
    /*tp_version_tag*/ 0,
    /*tp_finalize*/ nullptr,
    /*tp_vectorcall*/ nullptr,
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name GPU Texture module
 * \{ */

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture_from_image_doc,
    ".. function:: from_image(image)\n"
    "\n"
    "   Get GPUTexture corresponding to an Image data-block. The GPUTexture "
    "memory is "
    "shared with Blender.\n"
    "   Note: Colors read from the texture will be in scene linear color space and have "
    "premultiplied or straight alpha matching the image alpha mode.\n"
    "\n"
    "   :param image: The Image data-block.\n"
    "   :type image: :class:`bpy.types.Image`\n"
    "   :return: The GPUTexture used by the image.\n"
    "   :rtype: :class:`gpu.types.GPUTexture`\n");
static PyObject *pygpu_texture_from_image(PyObject * /*self*/, PyObject *arg)
{
  Image *ima = static_cast<Image *>(PyC_RNA_AsPointer(arg, "Image"));
  if (ima == nullptr) {
    return nullptr;
  }

  ImageUser iuser;
  BKE_imageuser_default(&iuser);
  /* Mixar: gl_load/movie_frame_update selects the displayed frame. The 5.3
   * per-ImBuf cache must not make from_image silently reload frame zero. */
  if (BKE_image_is_animated(ima)) {
    iuser.framenr = ima->lastframe;
  }
  gpu::Texture *tex = BKE_image_acquire_gpu_texture(ima, &iuser);

  PyObject *result = BPyGPUTexture_CreatePyObject(tex, true);
  if (tex) {
    GPU_texture_free(tex);
  }
  return result;
}

static PyMethodDef pygpu_texture__m_methods[] = {
    {"from_image",
     static_cast<PyCFunction>(pygpu_texture_from_image),
     METH_O,
     pygpu_texture_from_image_doc},
    {nullptr, nullptr, 0, nullptr},
};

PyDoc_STRVAR(
    /* Wrap. */
    pygpu_texture__m_doc,
    "This module provides utilities for textures.");
static PyModuleDef pygpu_texture_module_def = {
    /*m_base*/ PyModuleDef_HEAD_INIT,
    /*m_name*/ "gpu.texture",
    /*m_doc*/ pygpu_texture__m_doc,
    /*m_size*/ 0,
    /*m_methods*/ pygpu_texture__m_methods,
    /*m_slots*/ nullptr,
    /*m_traverse*/ nullptr,
    /*m_clear*/ nullptr,
    /*m_free*/ nullptr,
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Local API
 * \{ */

int bpygpu_ParseTexture(PyObject *o, void *p)
{
  if (o == Py_None) {
    *static_cast<gpu::Texture **>(p) = nullptr;
    return 1;
  }

  if (!BPyGPUTexture_Check(o)) {
    PyErr_Format(
        PyExc_ValueError, "expected a texture or None object, got %s", Py_TYPE(o)->tp_name);
    return 0;
  }

  if (pygpu_texture_valid_check((BPyGPUTexture *)o) == -1) [[unlikely]] {
    return 0;
  }

  *static_cast<gpu::Texture **>(p) = (reinterpret_cast<BPyGPUTexture *>(o))->tex;
  return 1;
}

PyObject *bpygpu_texture_init()
{
  PyObject *submodule;
  submodule = PyModule_Create(&pygpu_texture_module_def);

  return submodule;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Public API
 * \{ */

PyObject *BPyGPUTexture_CreatePyObject(gpu::Texture *tex, bool shared_reference)
{
  BPyGPUTexture *self;

  if (shared_reference) {
#ifndef GPU_NO_USE_PY_REFERENCES
    void **ref = GPU_texture_py_reference_get(tex);
    if (ref) {
      /* Retrieve BPyGPUTexture reference. */
      self = reinterpret_cast<BPyGPUTexture *> POINTER_OFFSET(ref, -offsetof(BPyGPUTexture, tex));
      BLI_assert(self->tex == tex);
      Py_INCREF(self);
      return reinterpret_cast<PyObject *>(self);
    }
#endif

    GPU_texture_ref(tex);
  }

  self = PyObject_New(BPyGPUTexture, &BPyGPUTexture_Type);
  self->tex = tex;

#ifndef GPU_NO_USE_PY_REFERENCES
  BLI_assert(GPU_texture_py_reference_get(tex) == nullptr);
  GPU_texture_py_reference_set(tex, reinterpret_cast<void **>(&self->tex));
#endif

  return reinterpret_cast<PyObject *>(self);
}

/** \} */

#undef BPYGPU_TEXTURE_CHECK_OBJ

}  // namespace blender
