/* SPDX-FileCopyrightText: 2023 Blender Authors
 * SPDX-License-Identifier: GPL-2.0-or-later */

/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup pygen
 */

#include <algorithm>

#include <Python.h>

#include "python_compat.hh" /* IWYU pragma: keep. */

#include "MEM_guardedalloc.h"

#include "BLI_utildefines.h"

#include "idprop_py_api.hh"
#include "idprop_py_ui_api.hh"

#include "BKE_idprop.hh"

#include "DNA_ID.h" /* ID property definitions. */

#define USE_STRING_COERCE

#ifdef USE_STRING_COERCE
#  include "py_capi_utils.hh"
#endif

#include "python_utildefines.hh"

namespace blender {

extern bool pyrna_id_FromPyObject(PyObject *obj, ID **id);
extern PyObject *pyrna_id_CreatePyObject(ID *id);
extern bool pyrna_id_CheckPyObject(PyObject *obj);

/* Currently there is no need to expose this publicly. */
static PyObject *BPy_IDGroup_IterKeys_CreatePyObject(BPy_IDProperty *group, const bool reversed);
static PyObject *BPy_IDGroup_IterValues_CreatePyObject(BPy_IDProperty *group, const bool reversed);
static PyObject *BPy_IDGroup_IterItems_CreatePyObject(BPy_IDProperty *group, const bool reversed);

static PyObject *BPy_IDGroup_ViewKeys_CreatePyObject(BPy_IDProperty *group);
static PyObject *BPy_IDGroup_ViewValues_CreatePyObject(BPy_IDProperty *group);
static PyObject *BPy_IDGroup_ViewItems_CreatePyObject(BPy_IDProperty *group);

static BPy_IDGroup_View *IDGroup_View_New_WithType(BPy_IDProperty *group, PyTypeObject *type);
static int BPy_IDGroup_Contains(BPy_IDProperty *self, PyObject *value);

/* -------------------------------------------------------------------- */
/** \name Python from ID-Property (Internal Conversions)
 *
 * Low level conversion to avoid duplicate code, no type checking.
 * \{ */

static PyObject *idprop_py_from_idp_string(const IDProperty *prop)
{
  if (prop->subtype == IDP_STRING_SUB_BYTE) {
    return PyBytes_FromStringAndSize(IDP_string_get(prop), prop->len);
  }

#ifdef USE_STRING_COERCE
  return PyC_UnicodeFromBytesAndSize(IDP_string_get(prop), prop->len - 1);
#else
  return PyUnicode_FromStringAndSize(IDP_string_get(prop), prop->len - 1);
#endif
}

static PyObject *idprop_py_from_idp_int(const IDProperty *prop)
{
  return PyLong_FromLong(long(IDP_int_get(prop)));
}

static PyObject *idprop_py_from_idp_float(const IDProperty *prop)
{
  return PyFloat_FromDouble(double(IDP_float_get(prop)));
}

static PyObject *idprop_py_from_idp_double(const IDProperty *prop)
{
  return PyFloat_FromDouble(IDP_double_get(prop));
}

static PyObject *idprop_py_from_idp_bool(const IDProperty *prop)
{
  return PyBool_FromLong(IDP_bool_get(prop));
}

static PyObject *idprop_py_from_idp_group(ID *id, IDProperty *prop, IDProperty *parent)
{
  BPy_IDProperty *group = PyObject_New(BPy_IDProperty, &BPy_IDGroup_Type);
  group->owner_id = id;
  group->prop = prop;
  group->parent = parent; /* can be nullptr */
  return reinterpret_cast<PyObject *>(group);
}

static PyObject *idprop_py_from_idp_id(IDProperty *prop)
{
  return pyrna_id_CreatePyObject(static_cast<ID *>(prop->data.pointer));
}

static PyObject *idprop_py_from_idp_array(ID *id, IDProperty *prop)
{
  BPy_IDProperty *array = PyObject_New(BPy_IDProperty, &BPy_IDArray_Type);
  array->owner_id = id;
  array->prop = prop;
  return reinterpret_cast<PyObject *>(array);
}

static PyObject *idprop_py_from_idp_idparray(ID *id, IDProperty *prop)
{
  PyObject *seq = PyList_New(prop->len);
  IDProperty *array = IDP_property_array_get(prop);
  int i;

  if (!seq) {
    PyErr_Format(
        PyExc_RuntimeError, "%s: IDP_IDPARRAY: PyList_New(%d) failed", __func__, prop->len);
    return nullptr;
  }

  for (i = 0; i < prop->len; i++) {
    PyObject *wrap = BPy_IDGroup_WrapData(id, array++, prop);

    /* BPy_IDGroup_MapDataToPy sets the error */
    if (UNLIKELY(wrap == nullptr)) {
      Py_DECREF(seq);
      return nullptr;
    }

    PyList_SET_ITEM(seq, i, wrap);
  }

  return seq;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name IDProp Group Access
 * \{ */

/* use for both array and group */
static Py_hash_t BPy_IDGroup_hash(BPy_IDProperty *self)
{
  return Py_HashPointer(self->prop);
}

static PyObject *BPy_IDGroup_repr(BPy_IDProperty *self)
{
  return PyUnicode_FromFormat("<bpy id prop: owner=\"%s\", name=\"%s\", address=%p>",
                              self->owner_id ? self->owner_id->name : "<NONE>",
                              self->prop->name,
                              self->prop);
}

PyObject *BPy_IDGroup_WrapData(ID *id, IDProperty *prop, IDProperty *parent)
{
  switch (prop->type) {
    case IDP_STRING:
      return idprop_py_from_idp_string(prop);
    case IDP_INT:
      return idprop_py_from_idp_int(prop);
    case IDP_FLOAT:
      return idprop_py_from_idp_float(prop);
    case IDP_DOUBLE:
      return idprop_py_from_idp_double(prop);
    case IDP_BOOLEAN:
      return idprop_py_from_idp_bool(prop);
    case IDP_GROUP:
      return idprop_py_from_idp_group(id, prop, parent);
    case IDP_ARRAY:
      return idprop_py_from_idp_array(id, prop);
    case IDP_IDPARRAY:
      return idprop_py_from_idp_idparray(id, prop); /* this could be better a internal type */
    case IDP_ID:
      return idprop_py_from_idp_id(prop);
    default:
      Py_RETURN_NONE;
  }
}

/* UNUSED, currently assignment overwrites into new properties, rather than setting in-place. */
#if 0
static int BPy_IDGroup_SetData(BPy_IDProperty *self, IDProperty *prop, PyObject *value)
{
  switch (prop->type) {
    case IDP_STRING: {
      char *st;
      if (!PyUnicode_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "expected a string!");
        return -1;
      }
/* NOTE: if this code is enabled, bytes support needs to be added */
#  ifdef USE_STRING_COERCE
      {
        int alloc_len;
        PyObject *value_coerce = nullptr;

        st = (char *)PyC_UnicodeAsBytes(value, &value_coerce);
        alloc_len = strlen(st) + 1;

        st = PyUnicode_AsUTF8(value);
        IDP_ResizeArray(prop, alloc_len);
        memcpy(IDP_string_get(prop), st, alloc_len);
        Py_XDECREF(value_coerce);
      }
#  else
      length_ssize_t st_len;
      st = PyUnicode_AsUTF8AndSize(value, &st_len);
      IDP_ResizeArray(prop, st_len + 1);
      memcpy(IDP_string_get(prop), st, st_len + 1);
#  endif

      return 0;
    }

    case IDP_INT: {
      int ivalue = PyLong_AsSsize_t(value);
      if (ivalue == -1 && PyErr_Occurred()) {
        PyErr_SetString(PyExc_TypeError, "expected an int type");
        return -1;
      }
      IDP_int_set(prop, ivalue);
      break;
    }
    case IDP_FLOAT: {
      float fvalue = float(PyFloat_AsDouble(value));
      if (fvalue == -1 && PyErr_Occurred()) {
        PyErr_SetString(PyExc_TypeError, "expected a float");
        return -1;
      }
      IDP_float_set(self->prop, fvalue);
      break;
    }
    case IDP_DOUBLE: {
      double dvalue = PyFloat_AsDouble(value);
      if (dvalue == -1 && PyErr_Occurred()) {
        PyErr_SetString(PyExc_TypeError, "expected a float");
        return -1;
      }
      IDP_double_set(self->prop, value);
      break;
    }
    default:
      PyErr_SetString(PyExc_AttributeError, "attempt to set read-only attribute!");
      return -1;
  }
  return 0;
}
#endif

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_GetName_doc,
    "The name of this Group.\n"
    "\n"
    ":type: str\n");
static PyObject *BPy_IDGroup_GetName(BPy_IDProperty *self, void * /*closure*/)
{
  return PyUnicode_FromString(self->prop->name);
}

static int BPy_IDGroup_SetName(BPy_IDProperty *self, PyObject *value, void * /*closure*/)
{
  const char *name;
  Py_ssize_t name_len;

  if (!PyUnicode_Check(value)) {
    PyErr_SetString(PyExc_TypeError, "expected a string!");
    return -1;
  }

  name = PyUnicode_AsUTF8AndSize(value, &name_len);

  if (!(name_len < MAX_IDPROP_NAME)) {
    PyErr_SetString(PyExc_TypeError, "string length cannot exceed 63 characters!");
    return -1;
  }
  if (STREQ(name, self->prop->name)) {
    return 0;
  }
  if (IDProperty *parent = self->parent) {
    if (IDP_GetPropertyFromGroup(parent, name)) {
      PyErr_SetString(PyExc_NameError, "property name already exists in parent group");
      return -1;
    }
  }

  memcpy(self->prop->name, name, name_len + 1);
  return 0;
}

#if 0
static PyObject *BPy_IDGroup_GetType(BPy_IDProperty *self)
{
  return PyLong_FromLong(self->prop->type);
}
#endif

static PyGetSetDef BPy_IDGroup_getseters[] = {
    {"name",
     reinterpret_cast<getter>(BPy_IDGroup_GetName),
     reinterpret_cast<setter>(BPy_IDGroup_SetName),
     BPy_IDGroup_GetName_doc,
     nullptr},
    {nullptr, nullptr, nullptr, nullptr, nullptr},
};

static Py_ssize_t BPy_IDGroup_Map_Len(BPy_IDProperty *self)
{
  if (self->prop->type != IDP_GROUP) {
    PyErr_SetString(PyExc_TypeError, "len() of unsized object");
    return -1;
  }

  return self->prop->len;
}

static PyObject *BPy_IDGroup_Map_GetItem(BPy_IDProperty *self, PyObject *item)
{
  IDProperty *idprop;
  const char *name;

  if (self->prop->type != IDP_GROUP) {
    PyErr_SetString(PyExc_TypeError, "unsubscriptable object");
    return nullptr;
  }

  name = PyUnicode_AsUTF8(item);

  if (name == nullptr) {
    PyErr_SetString(PyExc_TypeError, "only strings are allowed as keys of ID properties");
    return nullptr;
  }

  idprop = IDP_GetPropertyFromGroup(self->prop, name);

  if (idprop == nullptr) {
    PyErr_SetString(PyExc_KeyError, "key not in subgroup dict");
    return nullptr;
  }

  return BPy_IDGroup_WrapData(self->owner_id, idprop, self->prop);
}

/* Return identified matching IDProperty type, or -1 if error (e.g. mixed and/or incompatible
 * types, etc.). */
static char idp_sequence_type(PyObject *seq_fast)
{
  PyObject **seq_fast_items = PySequence_Fast_ITEMS(seq_fast);
  PyObject *item;
  char type = IDP_INT;

  Py_ssize_t i, len = PySequence_Fast_GET_SIZE(seq_fast);

  for (i = 0; i < len; i++) {
    item = seq_fast_items[i];
    if (PyFloat_Check(item)) {
      /* Mixed float and any other type but int.
       * NOTE: Mixed float/int is allowed, and considered as float values. */
      if (!ELEM(type, IDP_INT, IDP_DOUBLE)) {
        return -1;
      }
      type = IDP_DOUBLE;
    }
    else if (PyBool_Check(item)) {
      /* Mixed boolean and any other type. */
      if (i != 0 && (type != IDP_BOOLEAN)) {
        return -1;
      }
      type = IDP_BOOLEAN;
    }
    else if (PyLong_Check(item)) {
      /* Mixed int and any other type but float.
       * NOTE: Mixed float/int is allowed, and considered as float values. */
      if (!ELEM(type, IDP_INT, IDP_DOUBLE)) {
        return -1;
      }
    }
    else if (PyMapping_Check(item)) {
      /* Mixed dict and any other type. */
      if (i != 0 && (type != IDP_IDPARRAY)) {
        return -1;
      }
      type = IDP_IDPARRAY;
    }
    else {
      return -1;
    }
  }

  return type;
}

static const char *idp_try_read_name(PyObject *name_obj)
{
  const char *name = nullptr;
  if (name_obj) {
    Py_ssize_t name_len;
    name = PyUnicode_AsUTF8AndSize(name_obj, &name_len);

    if (name == nullptr) {
      PyErr_Format(PyExc_KeyError,
                   "invalid id-property key, expected a string, not a %.200s",
                   Py_TYPE(name_obj)->tp_name);
      return nullptr;
    }

    if (!(name_len < MAX_IDPROP_NAME)) {
      PyErr_SetString(PyExc_KeyError,
                      "the length of IDProperty names is limited to 63 characters");
      return nullptr;
    }
  }
  else {
    name = "";
  }
  return name;
}
