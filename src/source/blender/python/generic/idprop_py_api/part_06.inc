/* SPDX-FileCopyrightText: 2023 Blender Authors
 * SPDX-License-Identifier: GPL-2.0-or-later */


#ifdef __GNUC__
#  ifdef __clang__
#    pragma clang diagnostic push
#    pragma clang diagnostic ignored "-Wcast-function-type"
#  else
#    pragma GCC diagnostic push
#    pragma GCC diagnostic ignored "-Wcast-function-type"
#  endif
#endif

static PyMethodDef BPy_IDGroup_methods[] = {
    {"pop", reinterpret_cast<PyCFunction>(BPy_IDGroup_pop), METH_VARARGS, BPy_IDGroup_pop_doc},
    {"keys", reinterpret_cast<PyCFunction>(BPy_IDGroup_keys), METH_NOARGS, BPy_IDGroup_keys_doc},
    {"values",
     reinterpret_cast<PyCFunction>(BPy_IDGroup_values),
     METH_NOARGS,
     BPy_IDGroup_values_doc},
    {"items",
     reinterpret_cast<PyCFunction>(BPy_IDGroup_items),
     METH_NOARGS,
     BPy_IDGroup_items_doc},
    {"update", reinterpret_cast<PyCFunction>(BPy_IDGroup_update), METH_O, BPy_IDGroup_update_doc},
    {"get", reinterpret_cast<PyCFunction>(BPy_IDGroup_get), METH_VARARGS, BPy_IDGroup_get_doc},
    {"to_dict",
     reinterpret_cast<PyCFunction>(BPy_IDGroup_to_dict),
     METH_NOARGS,
     BPy_IDGroup_to_dict_doc},
    {"clear",
     reinterpret_cast<PyCFunction>(BPy_IDGroup_clear),
     METH_NOARGS,
     BPy_IDGroup_clear_doc},
    {nullptr, nullptr, 0, nullptr},
};

#ifdef __GNUC__
#  ifdef __clang__
#    pragma clang diagnostic pop
#  else
#    pragma GCC diagnostic pop
#  endif
#endif

/** \} */

/* -------------------------------------------------------------------- */
/** \name ID-Property Group Type
 * \{ */

static PySequenceMethods BPy_IDGroup_Seq = {
    /*sq_length*/ reinterpret_cast<lenfunc>(BPy_IDGroup_Map_Len),
    /*sq_concat*/ nullptr,
    /*sq_repeat*/ nullptr,
    /* TODO: setting this will allow `PySequence_Check()` to return True. */
    /*sq_item*/ nullptr,
    /*was_sq_slice*/ nullptr, /* DEPRECATED. */
    /*sq_ass_item*/ nullptr,
    /*was_sq_ass_slice*/ nullptr, /* DEPRECATED. */
    /*sq_contains*/ reinterpret_cast<objobjproc>(BPy_IDGroup_Contains),
    /*sq_inplace_concat*/ nullptr,
    /*sq_inplace_repeat*/ nullptr,
};

static PyMappingMethods BPy_IDGroup_Mapping = {
    /*mp_length*/ reinterpret_cast<lenfunc>(BPy_IDGroup_Map_Len),
    /*mp_subscript*/ reinterpret_cast<binaryfunc>(BPy_IDGroup_Map_GetItem),
    /*mp_ass_subscript*/ reinterpret_cast<objobjargproc>(BPy_IDGroup_Map_SetItem),
};

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_Type_doc,
    "A dictionary-like group of ID properties, "
    "supporting key access, iteration, and membership testing.\n"
    "\n"
    ".. note::\n"
    "\n"
    "   Only supports a maximum of 1024 levels of nesting.");

PyTypeObject BPy_IDGroup_Type = {
    /*ob_base*/ PyVarObject_HEAD_INIT(nullptr, 0)
    /* For printing, in format `<module>.<name>`. */
    /*tp_name*/ "IDPropertyGroup",
    /*tp_basicsize*/ sizeof(BPy_IDProperty),
    /*tp_itemsize*/ 0,
    /*tp_dealloc*/ nullptr,
    /*tp_vectorcall_offset*/ 0,
    /*tp_getattr*/ nullptr,
    /*tp_setattr*/ nullptr,
    /*tp_as_async*/ nullptr,
    /*tp_repr*/ reinterpret_cast<reprfunc>(BPy_IDGroup_repr),
    /*tp_as_number*/ nullptr,
    /*tp_as_sequence*/ &BPy_IDGroup_Seq,
    /*tp_as_mapping*/ &BPy_IDGroup_Mapping,
    /*tp_hash*/ reinterpret_cast<hashfunc>(BPy_IDGroup_hash),
    /*tp_call*/ nullptr,
    /*tp_str*/ nullptr,
    /*tp_getattro*/ nullptr,
    /*tp_setattro*/ nullptr,
    /*tp_as_buffer*/ nullptr,
    /*tp_flags*/ Py_TPFLAGS_DEFAULT,
    /*tp_doc*/ BPy_IDGroup_Type_doc,
    /*tp_traverse*/ nullptr,
    /*tp_clear*/ nullptr,
    /*tp_richcompare*/ nullptr,
    /*tp_weaklistoffset*/ 0,
    /*tp_iter*/ reinterpret_cast<getiterfunc>(BPy_IDGroup_iter),
    /*tp_iternext*/ nullptr,
    /*tp_methods*/ BPy_IDGroup_methods,
    /*tp_members*/ nullptr,
    /*tp_getset*/ BPy_IDGroup_getseters,
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
/** \name ID Array Methods
 * \{ */

static PyTypeObject *idp_array_py_type(BPy_IDArray *self, size_t *elem_size)
{
  switch (self->prop->subtype) {
    case IDP_FLOAT:
      *elem_size = sizeof(float);
      return &PyFloat_Type;
    case IDP_DOUBLE:
      *elem_size = sizeof(double);
      return &PyFloat_Type;
    case IDP_BOOLEAN:
      *elem_size = sizeof(int8_t);
      return &PyBool_Type;
    case IDP_INT:
      *elem_size = sizeof(int);
      return &PyLong_Type;
    default:
      *elem_size = 0;
      return nullptr;
  }
}

static PyObject *BPy_IDArray_repr(BPy_IDArray *self)
{
  return PyUnicode_FromFormat("<bpy id property array [%d]>", self->prop->len);
}

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDArray_get_typecode_doc,
    "The type of the data in the array "
    "{'f': float (32-bit), 'd': double (64-bit), 'i': int, 'b': bool}. "
    "Both 'f' and 'd' use Python's :class:`float` type but differ in storage precision.\n"
    "\n"
    ":type: Literal['f', 'd', 'i', 'b']\n");
static PyObject *BPy_IDArray_get_typecode(BPy_IDArray *self, void * /*closure*/)
{
  const char *typecode;
  switch (self->prop->subtype) {
    case IDP_FLOAT:
      typecode = "f";
      break;
    case IDP_DOUBLE:
      typecode = "d";
      break;
    case IDP_INT:
      typecode = "i";
      break;
    case IDP_BOOLEAN:
      typecode = "b";
      break;
    default: {
      PyErr_Format(PyExc_RuntimeError,
                   "%s: invalid/corrupt array type '%d'!",
                   __func__,
                   self->prop->subtype);

      return nullptr;
    }
  }
  return PyUnicode_FromString(typecode);
}

static PyGetSetDef BPy_IDArray_getseters[] = {
    /* matches pythons array.typecode */
    {"typecode",
     reinterpret_cast<getter>(BPy_IDArray_get_typecode),
     static_cast<setter>(nullptr),
     BPy_IDArray_get_typecode_doc,
     nullptr},
    {nullptr, nullptr, nullptr, nullptr, nullptr},
};

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDArray_to_list_doc,
    ".. method:: to_list()\n"
    "\n"
    "   Return the array as a list.\n"
    "\n"
    "   :return: The array as a list.\n"
    "   :rtype: list[int] | list[float] | list[bool]\n");
static PyObject *BPy_IDArray_to_list(BPy_IDArray *self)
{
  return BPy_IDGroup_MapDataToPy(self->prop);
}

#ifdef __GNUC__
#  ifdef __clang__
#    pragma clang diagnostic push
#    pragma clang diagnostic ignored "-Wcast-function-type"
#  else
#    pragma GCC diagnostic push
#    pragma GCC diagnostic ignored "-Wcast-function-type"
#  endif
#endif

static PyMethodDef BPy_IDArray_methods[] = {
    {"to_list",
     reinterpret_cast<PyCFunction>(BPy_IDArray_to_list),
     METH_NOARGS,
     BPy_IDArray_to_list_doc},
    {nullptr, nullptr, 0, nullptr},
};

#ifdef __GNUC__
#  ifdef __clang__
#    pragma clang diagnostic pop
#  else
#    pragma GCC diagnostic pop
#  endif
#endif

static Py_ssize_t BPy_IDArray_Len(BPy_IDArray *self)
{
  return self->prop->len;
}

static PyObject *BPy_IDArray_GetItem(BPy_IDArray *self, Py_ssize_t index)
{
  if (index < 0 || index >= self->prop->len) {
    PyErr_SetString(PyExc_IndexError, "index out of range!");
    return nullptr;
  }

  switch (self->prop->subtype) {
    case IDP_FLOAT:
      return PyFloat_FromDouble(IDP_array_float_get(self->prop)[index]);
    case IDP_DOUBLE:
      return PyFloat_FromDouble(IDP_array_double_get(self->prop)[index]);
    case IDP_INT:
      return PyLong_FromLong(long(IDP_array_int_get(self->prop)[index]));
    case IDP_BOOLEAN:
      return PyBool_FromLong(long(IDP_array_bool_get(self->prop)[index]));
  }

  PyErr_Format(
      PyExc_RuntimeError, "%s: invalid/corrupt array type '%d'!", __func__, self->prop->subtype);

  return nullptr;
}

static int BPy_IDArray_SetItem(BPy_IDArray *self, Py_ssize_t index, PyObject *value)
{
  if (index < 0 || index >= self->prop->len) {
    PyErr_SetString(PyExc_RuntimeError, "index out of range!");
    return -1;
  }

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
