/* SPDX-FileCopyrightText: 2023 Blender Authors
 * SPDX-License-Identifier: GPL-2.0-or-later */

PyObject *BPy_Wrap_GetValues_View_WithID(ID *id, IDProperty *prop)
{
  PyObject *self = prop ? idprop_py_from_idp_group(id, prop, nullptr) : nullptr;
  PyObject *ret = BPy_IDGroup_ViewValues_CreatePyObject(reinterpret_cast<BPy_IDProperty *>(self));
  Py_XDECREF(self); /* Owned by `ret`. */
  return ret;
}

PyObject *BPy_Wrap_GetItems_View_WithID(ID *id, IDProperty *prop)
{
  PyObject *self = prop ? idprop_py_from_idp_group(id, prop, nullptr) : nullptr;
  PyObject *ret = BPy_IDGroup_ViewItems_CreatePyObject(reinterpret_cast<BPy_IDProperty *>(self));
  Py_XDECREF(self); /* Owned by `ret`. */
  return ret;
}

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_keys_doc,
    ".. method:: keys()\n"
    "\n"
    "   Return a view of the keys in the group.\n"
    "\n"
    "   :return: A view of the keys.\n"
    "   :rtype: :class:`IDPropertyGroupViewKeys`\n");
static PyObject *BPy_IDGroup_keys(BPy_IDProperty *self)
{
  return BPy_IDGroup_ViewKeys_CreatePyObject(self);
}

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_values_doc,
    ".. method:: values()\n"
    "\n"
    "   Return the values associated with this group.\n"
    "\n"
    "   :return: A view of the values.\n"
    "   :rtype: :class:`IDPropertyGroupViewValues`\n");
static PyObject *BPy_IDGroup_values(BPy_IDProperty *self)
{
  return BPy_IDGroup_ViewValues_CreatePyObject(self);
}

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_items_doc,
    ".. method:: items()\n"
    "\n"
    "   Return a view of the items in the group, behaves like dictionary method items.\n"
    "\n"
    "   :return: A view of the items.\n"
    "   :rtype: :class:`IDPropertyGroupViewItems`\n");
static PyObject *BPy_IDGroup_items(BPy_IDProperty *self)
{
  return BPy_IDGroup_ViewItems_CreatePyObject(self);
}

static int BPy_IDGroup_Contains(BPy_IDProperty *self, PyObject *value)
{
  const char *name = PyUnicode_AsUTF8(value);

  if (!name) {
    PyErr_Format(PyExc_TypeError, "expected a string, not a %.200s", Py_TYPE(value)->tp_name);
    return -1;
  }

  return IDP_GetPropertyFromGroup(self->prop, name) ? 1 : 0;
}

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_update_doc,
    ".. method:: update(other)\n"
    "\n"
    "   Update key-value pairs from *other*, overwriting existing keys.\n"
    "\n"
    "   .. note::\n"
    "\n"
    "      Unlike :meth:`dict.update`, keyword arguments are not supported.\n"
    "\n"
    "   :param other: Updates the values in the group with this.\n"
    /* TODO: replace `Any` with an alias for all types an ID property can use. */
    "   :type other: :class:`IDPropertyGroup` | dict[str, Any]\n");
static PyObject *BPy_IDGroup_update(BPy_IDProperty *self, PyObject *value)
{
  PyObject *pkey, *pval;
  Py_ssize_t i = 0;

  if (BPy_IDGroup_Check(value)) {
    BPy_IDProperty *other = reinterpret_cast<BPy_IDProperty *>(value);
    if (self->prop == other->prop) [[unlikely]] {
      Py_RETURN_NONE;
    }

    /* XXX, possible one is inside the other */
    IDP_MergeGroup(self->prop, other->prop, true);
  }
  else if (PyDict_Check(value)) {
    while (PyDict_Next(value, &i, &pkey, &pval)) {
      BPy_IDGroup_Map_SetItem(self, pkey, pval);
      if (PyErr_Occurred()) {
        return nullptr;
      }
    }
  }
  else {
    PyErr_Format(PyExc_TypeError,
                 "expected a dict or an IDPropertyGroup type, not a %.200s",
                 Py_TYPE(value)->tp_name);
    return nullptr;
  }

  Py_RETURN_NONE;
}

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_to_dict_doc,
    ".. method:: to_dict()\n"
    "\n"
    "   Return a purely Python version of the group.\n"
    "\n"
    "   :return: A dictionary representation of the group.\n"
    "   :rtype: dict[str, Any]\n");
static PyObject *BPy_IDGroup_to_dict(BPy_IDProperty *self)
{
  return BPy_IDGroup_MapDataToPy(self->prop);
}

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_clear_doc,
    ".. method:: clear()\n"
    "\n"
    "   Clear all members from this group.\n");
static PyObject *BPy_IDGroup_clear(BPy_IDProperty *self)
{
  IDP_ClearProperty(self->prop);
  Py_RETURN_NONE;
}

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_get_doc,
    ".. method:: get(key, default=None)\n"
    "\n"
    "   Return the value for key, if it exists, else default.\n"
    "\n"
    "   :param key: The key to look up.\n"
    "   :type key: str\n"
    "   :param default: Value to return if *key* is not found.\n"
    "   :type default: Any\n"
    "   :return: The value for the key, or *default* if not found.\n"
    "   :rtype: Any\n");
static PyObject *BPy_IDGroup_get(BPy_IDProperty *self, PyObject *args)
{
  IDProperty *idprop;
  const char *key;
  PyObject *def = Py_None;

  if (!PyArg_ParseTuple(args,
                        "s" /* `key` */
                        "|" /* Optional arguments. */
                        "O" /* `default` */
                        ":get",
                        &key,
                        &def))
  {
    return nullptr;
  }

  idprop = IDP_GetPropertyFromGroup(self->prop, key);
  if (idprop) {
    PyObject *pyobj = BPy_IDGroup_WrapData(self->owner_id, idprop, self->prop);
    if (pyobj) {
      return pyobj;
    }
  }

  Py_INCREF(def);
  return def;
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
