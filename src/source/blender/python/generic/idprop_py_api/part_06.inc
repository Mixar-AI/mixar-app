/* SPDX-FileCopyrightText: 2023 Blender Authors
 * SPDX-License-Identifier: GPL-2.0-or-later */

  switch (self->prop->subtype) {
    case IDP_FLOAT: {
      const float f = float(PyFloat_AsDouble(value));
      if (f == -1 && PyErr_Occurred()) {
        return -1;
      }
      IDP_array_float_get(self->prop)[index] = f;
      break;
    }
    case IDP_DOUBLE: {
      const double d = PyFloat_AsDouble(value);
      if (d == -1 && PyErr_Occurred()) {
        return -1;
      }
      IDP_array_double_get(self->prop)[index] = d;
      break;
    }
    case IDP_INT: {
      const int i = PyC_Long_AsI32(value);
      if (i == -1 && PyErr_Occurred()) {
        return -1;
      }

      IDP_array_int_get(self->prop)[index] = i;
      break;
    }
    case IDP_BOOLEAN: {
      const int i = PyC_Long_AsBool(value);
      if (i == -1 && PyErr_Occurred()) {
        return -1;
      }

      IDP_array_bool_get(self->prop)[index] = i;
      break;
    }
  }
  return 0;
}

static PySequenceMethods BPy_IDArray_Seq = {
    /*sq_length*/ reinterpret_cast<lenfunc>(BPy_IDArray_Len),
    /*sq_concat*/ nullptr,
    /*sq_repeat*/ nullptr,
    /*sq_item*/ reinterpret_cast<ssizeargfunc>(BPy_IDArray_GetItem),
    /*was_sq_slice*/ nullptr, /* DEPRECATED. */
    /*sq_ass_item*/ reinterpret_cast<ssizeobjargproc>(BPy_IDArray_SetItem),
    /*was_sq_ass_slice*/ nullptr, /* DEPRECATED. */
    /*sq_contains*/ nullptr,
    /*sq_inplace_concat*/ nullptr,
    /*sq_inplace_repeat*/ nullptr,
};

/* sequence slice (get): idparr[a:b] */
static PyObject *BPy_IDArray_slice(BPy_IDArray *self, int begin, int end)
{
  IDProperty *prop = self->prop;
  PyObject *tuple;
  int count;

  CLAMP(begin, 0, prop->len);
  if (end < 0) {
    end = prop->len + end + 1;
  }
  CLAMP(end, 0, prop->len);
  begin = std::min(begin, end);

  tuple = PyTuple_New(end - begin);

  switch (prop->subtype) {
    case IDP_FLOAT: {
      const float *array = IDP_array_float_get(prop);
      for (count = begin; count < end; count++) {
        PyTuple_SET_ITEM(tuple, count - begin, PyFloat_FromDouble(array[count]));
      }
      break;
    }
    case IDP_DOUBLE: {
      const double *array = IDP_array_double_get(prop);
      for (count = begin; count < end; count++) {
        PyTuple_SET_ITEM(tuple, count - begin, PyFloat_FromDouble(array[count]));
      }
      break;
    }
    case IDP_INT: {
      const int *array = IDP_array_int_get(prop);
      for (count = begin; count < end; count++) {
        PyTuple_SET_ITEM(tuple, count - begin, PyLong_FromLong(array[count]));
      }
      break;
    }
    case IDP_BOOLEAN: {
      const int8_t *array = IDP_array_bool_get(prop);
      for (count = begin; count < end; count++) {
        PyTuple_SET_ITEM(tuple, count - begin, PyBool_FromLong(long(array[count])));
      }
      break;
    }
  }

  return tuple;
}
/* sequence slice (set): idparr[a:b] = value */
static int BPy_IDArray_ass_slice(BPy_IDArray *self, int begin, int end, PyObject *seq)
{
  IDProperty *prop = self->prop;
  size_t elem_size;
  const PyTypeObject *py_type = idp_array_py_type(self, &elem_size);
  size_t alloc_len;
  size_t size;
  void *vec;

  CLAMP(begin, 0, prop->len);
  CLAMP(end, 0, prop->len);
  begin = std::min(begin, end);

  size = (end - begin);
  alloc_len = size * elem_size;

  /* NOTE: we count on int/float being the same size here */
  vec = MEM_new_uninitialized(alloc_len, "array assignment");

  if (PyC_AsArray(vec, elem_size, seq, size, py_type, "slice assignment: ") == -1) {
    MEM_delete_void(vec);
    return -1;
  }

  memcpy(
      static_cast<void *>((static_cast<char *> IDP_array_voidp_get(prop)) + (begin * elem_size)),
      vec,
      alloc_len);

  MEM_delete_void(vec);
  return 0;
}

static PyObject *BPy_IDArray_subscript(BPy_IDArray *self, PyObject *item)
{
  if (PyIndex_Check(item)) {
    Py_ssize_t i;
    i = PyNumber_AsSsize_t(item, PyExc_IndexError);
    if (i == -1 && PyErr_Occurred()) {
      return nullptr;
    }
    if (i < 0) {
      i += self->prop->len;
    }
    return BPy_IDArray_GetItem(self, i);
  }
  if (PySlice_Check(item)) {
    Py_ssize_t start, stop, step, slicelength;

    if (PySlice_GetIndicesEx(item, self->prop->len, &start, &stop, &step, &slicelength) < 0) {
      return nullptr;
    }

    if (slicelength <= 0) {
      return PyTuple_New(0);
    }
    if (step == 1) {
      return BPy_IDArray_slice(self, start, stop);
    }

    PyErr_SetString(PyExc_TypeError, "slice steps not supported with vectors");
    return nullptr;
  }

  PyErr_Format(PyExc_TypeError,
               "vector indices must be integers, not %.200s",
               __func__,
               Py_TYPE(item)->tp_name);
  return nullptr;
}

static int BPy_IDArray_ass_subscript(BPy_IDArray *self, PyObject *item, PyObject *value)
{
  if (PyIndex_Check(item)) {
    Py_ssize_t i = PyNumber_AsSsize_t(item, PyExc_IndexError);
    if (i == -1 && PyErr_Occurred()) {
      return -1;
    }
    if (i < 0) {
      i += self->prop->len;
    }
    return BPy_IDArray_SetItem(self, i, value);
  }
  if (PySlice_Check(item)) {
    Py_ssize_t start, stop, step, slicelength;

    if (PySlice_GetIndicesEx(item, self->prop->len, &start, &stop, &step, &slicelength) < 0) {
      return -1;
    }

    if (step == 1) {
      return BPy_IDArray_ass_slice(self, start, stop, value);
    }

    PyErr_SetString(PyExc_TypeError, "slice steps not supported with vectors");
    return -1;
  }

  PyErr_Format(
      PyExc_TypeError, "vector indices must be integers, not %.200s", Py_TYPE(item)->tp_name);
  return -1;
}

static PyMappingMethods BPy_IDArray_AsMapping = {
    /*mp_length*/ reinterpret_cast<lenfunc>(BPy_IDArray_Len),
    /*mp_subscript*/ reinterpret_cast<binaryfunc>(BPy_IDArray_subscript),
    /*mp_ass_subscript*/ reinterpret_cast<objobjargproc>(BPy_IDArray_ass_subscript),
};

static int itemsize_by_idarray_type(int array_type)
{
  if (array_type == IDP_INT) {
    return sizeof(int);
  }
  if (array_type == IDP_FLOAT) {
    return sizeof(float);
  }
  if (array_type == IDP_DOUBLE) {
    return sizeof(double);
  }
  if (array_type == IDP_BOOLEAN) {
    return sizeof(bool);
  }
  return -1; /* should never happen */
}

static int BPy_IDArray_getbuffer(BPy_IDArray *self, Py_buffer *view, int flags)
{
  IDProperty *prop = self->prop;
  const int itemsize = itemsize_by_idarray_type(prop->subtype);
  const int length = itemsize * prop->len;

  if (PyBuffer_FillInfo(view,
                        reinterpret_cast<PyObject *>(self),
                        IDP_array_voidp_get(prop),
                        length,
                        false,
                        flags) == -1)
  {
    return -1;
  }

  view->itemsize = itemsize;
  view->format = const_cast<char *>(idp_format_from_array_type(prop->subtype));

  Py_ssize_t *shape = MEM_new_uninitialized<Py_ssize_t>(__func__);
  shape[0] = prop->len;
  view->shape = shape;

  return 0;
}

static void BPy_IDArray_releasebuffer(BPy_IDArray * /*self*/, Py_buffer *view)
{
  MEM_delete(view->shape);
}

static PyBufferProcs BPy_IDArray_Buffer = {
    /*bf_getbuffer*/ reinterpret_cast<getbufferproc>(BPy_IDArray_getbuffer),
    /*bf_releasebuffer*/ reinterpret_cast<releasebufferproc>(BPy_IDArray_releasebuffer),
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name ID Array Type
 * \{ */

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDArray_Type_doc,
    "An array of values with a fixed type, "
    "supporting indexing and slicing.");

PyTypeObject BPy_IDArray_Type = {
    /*ob_base*/ PyVarObject_HEAD_INIT(nullptr, 0)
    /* For printing, in format `<module>.<name>`. */
    /*tp_name*/ "IDPropertyArray",
    /*tp_basicsize*/ sizeof(BPy_IDArray),
    /*tp_itemsize*/ 0,
    /*tp_dealloc*/ nullptr,
    /*tp_vectorcall_offset*/ 0,
    /*tp_getattr*/ nullptr,
    /*tp_setattr*/ nullptr,
    /*tp_as_async*/ nullptr,
    /*tp_repr*/ reinterpret_cast<reprfunc>(BPy_IDArray_repr),
    /*tp_as_number*/ nullptr,
    /*tp_as_sequence*/ &BPy_IDArray_Seq,
    /*tp_as_mapping*/ &BPy_IDArray_AsMapping,
    /*tp_hash*/ nullptr,
    /*tp_call*/ nullptr,
    /*tp_str*/ nullptr,
    /*tp_getattro*/ nullptr,
    /*tp_setattro*/ nullptr,
    /*tp_as_buffer*/ &BPy_IDArray_Buffer,
    /*tp_flags*/ Py_TPFLAGS_DEFAULT,
    /*tp_doc*/ BPy_IDArray_Type_doc,
    /*tp_traverse*/ nullptr,
    /*tp_clear*/ nullptr,
    /*tp_richcompare*/ nullptr,
    /*tp_weaklistoffset*/ 0,
    /*tp_iter*/ nullptr,
    /*tp_iternext*/ nullptr,
    /*tp_methods*/ BPy_IDArray_methods,
    /*tp_members*/ nullptr,
    /*tp_getset*/ BPy_IDArray_getseters,
    /*tp_base*/ nullptr,
    /*tp_dict*/ nullptr,
    /*tp_descr_get*/ nullptr,
    /*tp_descr_set*/ nullptr,
    /*tp_dictoffset*/ 0,
    /*tp_init*/ nullptr,
    /*tp_alloc*/ nullptr,
    /*tp_new*/ nullptr,
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
/** \name Initialize Types
 * \{ */

void IDProp_Init_Types()
{
  IDGroup_Iter_init_type();
  IDGroup_View_init_type();

  PyType_Ready(&BPy_IDGroup_Type);
  PyType_Ready(&BPy_IDArray_Type);

  PyType_Ready(&BPy_IDGroup_IterKeys_Type);
  PyType_Ready(&BPy_IDGroup_IterValues_Type);
  PyType_Ready(&BPy_IDGroup_IterItems_Type);

  PyType_Ready(&BPy_IDGroup_ViewKeys_Type);
  PyType_Ready(&BPy_IDGroup_ViewValues_Type);
  PyType_Ready(&BPy_IDGroup_ViewItems_Type);
}

/**
 * \note `group` may be nullptr, unlike most other uses of this argument.
 * This is supported so RNA keys/values/items methods returns an iterator with the expected type:
 * - Without having ID-properties.
 * - Without supporting #BPy_IDProperty.prop being nullptr, which would incur many more checks.
 * Python's own dictionary-views also works this way too.
 */
static BPy_IDGroup_View *IDGroup_View_New_WithType(BPy_IDProperty *group, PyTypeObject *type)
{
  BLI_assert(group ? group->prop->type == IDP_GROUP : true);
  BPy_IDGroup_View *iter = PyObject_GC_New(BPy_IDGroup_View, type);
  iter->reversed = false;
  iter->group = group;
  if (group != nullptr) {
    Py_INCREF(group);
    BLI_assert(!PyObject_GC_IsTracked((PyObject *)iter));
    PyObject_GC_Track(iter);
  }
  return iter;
}

static PyObject *BPy_IDGroup_ViewKeys_CreatePyObject(BPy_IDProperty *group)
{
  return reinterpret_cast<PyObject *>(
      IDGroup_View_New_WithType(group, &BPy_IDGroup_ViewKeys_Type));
}

static PyObject *BPy_IDGroup_ViewValues_CreatePyObject(BPy_IDProperty *group)
{
  return reinterpret_cast<PyObject *>(
      IDGroup_View_New_WithType(group, &BPy_IDGroup_ViewValues_Type));
}

static PyObject *BPy_IDGroup_ViewItems_CreatePyObject(BPy_IDProperty *group)
{
  return reinterpret_cast<PyObject *>(
      IDGroup_View_New_WithType(group, &BPy_IDGroup_ViewItems_Type));
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Public Module 'idprop.types'
 * \{ */

static PyModuleDef IDProp_types_module_def = {
    /*m_base*/ PyModuleDef_HEAD_INIT,
    /*m_name*/ "idprop.types",
    /*m_doc*/ nullptr,
    /*m_size*/ 0,
    /*m_methods*/ nullptr,
    /*m_slots*/ nullptr,
    /*m_traverse*/ nullptr,
    /*m_clear*/ nullptr,
    /*m_free*/ nullptr,
};

static PyObject *BPyInit_idprop_types()
{
  PyObject *submodule;

  submodule = PyModule_Create(&IDProp_types_module_def);

  IDProp_Init_Types();
  IDPropertyUIData_Init_Types();

  /* `bmesh_py_types.cc` */
  PyModule_AddType(submodule, &BPy_IDGroup_Type);

  PyModule_AddType(submodule, &BPy_IDGroup_ViewKeys_Type);
  PyModule_AddType(submodule, &BPy_IDGroup_ViewValues_Type);
  PyModule_AddType(submodule, &BPy_IDGroup_ViewItems_Type);

  PyModule_AddType(submodule, &BPy_IDGroup_IterKeys_Type);
  PyModule_AddType(submodule, &BPy_IDGroup_IterValues_Type);
  PyModule_AddType(submodule, &BPy_IDGroup_IterItems_Type);

  PyModule_AddType(submodule, &BPy_IDArray_Type);

  PyModule_AddType(submodule, &BPy_IDPropertyUIManager_Type);

  return submodule;
}
