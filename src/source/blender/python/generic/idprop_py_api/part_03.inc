/* SPDX-FileCopyrightText: 2023 Blender Authors
 * SPDX-License-Identifier: GPL-2.0-or-later */
  }

  if (use_buffer) {
    IDProperty *prop = idp_from_PySequence_Buffer(
        prop_exist, name, buffer, idp_buffer_type, do_conversion, can_create);
    PyBuffer_Release(&buffer);
    return prop;
  }

  PyObject *ob_seq_fast = PySequence_Fast(ob, "py -> idprop");
  if (ob_seq_fast != nullptr) {
    IDProperty *prop = idp_from_PySequence_Fast(
        prop_exist, name, ob_seq_fast, do_conversion, can_create);
    Py_DECREF(ob_seq_fast);
    return prop;
  }

  return nullptr;
}

static IDProperty *idp_from_PyMapping(IDProperty * /*prop_exist*/,
                                      const char *name,
                                      PyObject *ob,
                                      const bool /*do_conversion*/,
                                      const bool /*can_create*/)
{
  IDProperty *prop;

  /* TODO: Handle editing in-place of existing property (#IDP_FLAG_STATIC_TYPE flag). */

  PyObject *keys, *vals, *key, *pval;
  int i, len;
  /* yay! we get into recursive stuff now! */
  len = PyMapping_Length(ob);
  if (len == -1) {
    return nullptr;
  }
  keys = PyMapping_Keys(ob);
  if (keys == nullptr) {
    return nullptr;
  }
  vals = PyMapping_Values(ob);
  if (vals == nullptr) {
    Py_DECREF(keys);
    return nullptr;
  }

  /* We allocate the group first; if we hit any invalid data,
   * we can delete it easily enough. */
  prop = bke::idprop::create_group(name).release();
  for (i = 0; i < len; i++) {
    key = PySequence_GetItem(keys, i);
    pval = PySequence_GetItem(vals, i);
    if (BPy_IDProperty_Map_ValidateAndCreate(key, prop, pval) == false) {
      IDP_FreeProperty(prop);
      Py_XDECREF(keys);
      Py_XDECREF(vals);
      Py_XDECREF(key);
      Py_XDECREF(pval);
      /* error is already set */
      return nullptr;
    }
    Py_XDECREF(key);
    Py_XDECREF(pval);
  }
  Py_XDECREF(keys);
  Py_XDECREF(vals);
  return prop;
}

static IDProperty *idp_from_DatablockPointer(IDProperty *prop_exist,
                                             const char *name,
                                             PyObject *ob,
                                             const bool /*do_conversion*/,
                                             const bool can_create)
{
  IDProperty *prop = nullptr;
  ID *value = nullptr;
  pyrna_id_FromPyObject(ob, &value);

  if (value && (value->flag & ID_FLAG_EMBEDDED_DATA) != 0) {
    PyErr_SetString(PyExc_ValueError, "Cannot assign an embedded ID pointer to an id-property");
    return nullptr;
  }

  if (prop_exist) {
    if (prop_exist->type == IDP_ID) {
      IDP_AssignID(prop_exist, value, 0);
      prop = prop_exist;
    }
    /* No conversion. */
  }
  if (!prop && can_create) {
    prop = bke::idprop::create(name, value).release();
  }
  return prop;
}

IDProperty *BPy_IDProperty_FromPyObject(IDProperty *prop_exist,
                                        const char *name,
                                        PyObject *ob,
                                        const bool do_conversion,
                                        const bool can_create)
{
  if (name == nullptr) {
    return nullptr;
  }

  if (PyFloat_Check(ob)) {
    return idp_from_PyFloat(prop_exist, name, ob, do_conversion, can_create);
  }
  if (PyBool_Check(ob)) {
    return idp_from_PyBool(prop_exist, name, ob, do_conversion, can_create);
  }
  if (PyLong_Check(ob)) {
    return idp_from_PyLong(prop_exist, name, ob, do_conversion, can_create);
  }
  if (PyUnicode_Check(ob)) {
    return idp_from_PyUnicode(prop_exist, name, ob, do_conversion, can_create);
  }
  if (PyBytes_Check(ob)) {
    return idp_from_PyBytes(prop_exist, name, ob, do_conversion, can_create);
  }
  if (PySequence_Check(ob)) {
    return idp_from_PySequence(prop_exist, name, ob, do_conversion, can_create);
  }
  if (ob == Py_None || pyrna_id_CheckPyObject(ob)) {
    return idp_from_DatablockPointer(prop_exist, name, ob, do_conversion, can_create);
  }
  if (PyMapping_Check(ob)) {
    return idp_from_PyMapping(prop_exist, name, ob, do_conversion, can_create);
  }

  PyErr_Format(
      PyExc_TypeError, "invalid id-property type %.200s not supported", Py_TYPE(ob)->tp_name);
  return nullptr;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Mapping Get/Set (Internal Access)
 * \{ */

bool BPy_IDProperty_Map_ValidateAndCreate(PyObject *key, IDProperty *group, PyObject *ob)
{
  const char *name = idp_try_read_name(key);
  if (!name) {
    return false;
  }

  /* If the container is an array of IDProperties, always add a new property to it. */
  if (group->type == IDP_IDPARRAY) {
    IDProperty *new_prop = BPy_IDProperty_FromPyObject(nullptr, name, ob, false, true);
    if (new_prop == nullptr) {
      return false;
    }

    IDP_AppendArray(group, new_prop);
    /* IDP_AppendArray does a shallow copy (memcpy), only free memory */
    MEM_delete(new_prop);

    return true;
  }

  IDProperty *prop_exist = IDP_GetPropertyFromGroup(group, name);

  /* If existing property is flagged to be statically typed, do not re-type it. Assign the value if
   * possible (potentially converting it), or fail. See #122743. */
  if (prop_exist && (prop_exist->flag & IDP_FLAG_STATIC_TYPE) != 0) {
    IDProperty *prop = BPy_IDProperty_FromPyObject(prop_exist, name, ob, true, false);
    BLI_assert(ELEM(prop, prop_exist, nullptr));
    if (prop != prop_exist) {
      PyErr_Format(PyExc_TypeError,
                   "Cannot assign a '%.200s' value to the existing '%s' %s IDProperty",
                   Py_TYPE(ob)->tp_name,
                   name,
                   IDP_type_str(prop_exist));
      return false;
    }
    return true;
  }

  /* Attempt to assign new value in existing IDProperty, if types (and potentially subtypes) match
   * exactly. Otherwise, create a new IDProperty. */
  IDProperty *new_prop = BPy_IDProperty_FromPyObject(prop_exist, name, ob, false, true);
  if (new_prop == nullptr) {
    return false;
  }
  if (new_prop == prop_exist) {
    return true;
  }

  /* Property was created with no existing counterpart, just insert it in the group container. */
  if (!prop_exist) {
    IDP_ReplaceInGroup_ex(group, new_prop, nullptr, 0);
    return true;
  }

  /* Try to preserve UI data from the existing, replaced property. See: #37073. */
  if (prop_exist->ui_data) {
    /* Take ownership of the existing property's UI data. */
    const eIDPropertyUIDataType src_type = IDP_ui_data_type(prop_exist);
    IDPropertyUIData *ui_data = prop_exist->ui_data;
    prop_exist->ui_data = nullptr;

    new_prop->ui_data = IDP_TryConvertUIData(ui_data, src_type, IDP_ui_data_type(new_prop));
  }
  /* Copy over the 'overridable' flag from existing property. */
  new_prop->flag |= (prop_exist->flag & IDP_FLAG_OVERRIDABLE_LIBRARY);

  IDP_ReplaceInGroup_ex(group, new_prop, prop_exist, 0);
  return true;
}

int BPy_Wrap_SetMapItem(IDProperty *prop, PyObject *key, PyObject *val)
{
  if (prop->type != IDP_GROUP) {
    PyErr_SetString(PyExc_TypeError, "unsubscriptable object");
    return -1;
  }

  if (val == nullptr) { /* del idprop[key] */
    IDProperty *pkey;
    const char *name = PyUnicode_AsUTF8(key);

    if (name == nullptr) {
      PyErr_Format(PyExc_KeyError, "expected a string, not %.200s", Py_TYPE(key)->tp_name);
      return -1;
    }

    pkey = IDP_GetPropertyFromGroup(prop, name);
    if (pkey) {
      IDP_FreeFromGroup(prop, pkey);
      return 0;
    }

    PyErr_SetString(PyExc_KeyError, "property not found in group");
    return -1;
  }

  bool ok;

  ok = BPy_IDProperty_Map_ValidateAndCreate(key, prop, val);
  if (ok == false) {
    return -1;
  }

  return 0;
}

static int BPy_IDGroup_Map_SetItem(BPy_IDProperty *self, PyObject *key, PyObject *val)
{
  return BPy_Wrap_SetMapItem(self->prop, key, val);
}

static PyObject *BPy_IDGroup_iter(BPy_IDProperty *self)
{
  PyObject *iterable = BPy_IDGroup_ViewKeys_CreatePyObject(self);
  PyObject *ret;
  if (iterable) {
    ret = PyObject_GetIter(iterable);
    Py_DECREF(iterable);
  }
  else {
    ret = nullptr;
  }
  return ret;
}

PyObject *BPy_IDGroup_MapDataToPy(IDProperty *prop)
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
    case IDP_ID:
      return idprop_py_from_idp_id(prop);
    case IDP_ARRAY: {
      PyObject *seq = PyList_New(prop->len);
      int i;

      if (!seq) {
        PyErr_Format(
            PyExc_RuntimeError, "%s: IDP_ARRAY: PyList_New(%d) failed", __func__, prop->len);
        return nullptr;
      }

      switch (prop->subtype) {
        case IDP_FLOAT: {
          const float *array = IDP_array_float_get(prop);
          for (i = 0; i < prop->len; i++) {
            PyList_SET_ITEM(seq, i, PyFloat_FromDouble(array[i]));
          }
          break;
        }
        case IDP_DOUBLE: {
          const double *array = IDP_array_double_get(prop);
          for (i = 0; i < prop->len; i++) {
            PyList_SET_ITEM(seq, i, PyFloat_FromDouble(array[i]));
          }
          break;
        }
        case IDP_INT: {
          const int *array = IDP_array_int_get(prop);
          for (i = 0; i < prop->len; i++) {
            PyList_SET_ITEM(seq, i, PyLong_FromLong(array[i]));
          }
          break;
        }
        case IDP_BOOLEAN: {
          const int8_t *array = IDP_array_bool_get(prop);
          for (i = 0; i < prop->len; i++) {
            PyList_SET_ITEM(seq, i, PyBool_FromLong(array[i]));
          }
          break;
        }
        default:
          PyErr_Format(
              PyExc_RuntimeError, "%s: invalid/corrupt array type '%d'!", __func__, prop->subtype);
          Py_DECREF(seq);
          return nullptr;
      }

      return seq;
    }
    case IDP_IDPARRAY: {
      PyObject *seq = PyList_New(prop->len);
      IDProperty *array = IDP_property_array_get(prop);
      int i;

      if (!seq) {
        PyErr_Format(
            PyExc_RuntimeError, "%s: IDP_IDPARRAY: PyList_New(%d) failed", __func__, prop->len);
        return nullptr;
      }

      for (i = 0; i < prop->len; i++) {
        PyObject *wrap = BPy_IDGroup_MapDataToPy(array++);

        /* BPy_IDGroup_MapDataToPy sets the error */
        if (wrap == nullptr) [[unlikely]] {
          Py_DECREF(seq);
          return nullptr;
        }

        PyList_SET_ITEM(seq, i, wrap);
      }
      return seq;
    }
    case IDP_GROUP: {
      PyObject *dict = _PyDict_NewPresized(prop->len);
      IDProperty *loop;

      for (loop = prop->data.group.first(); loop; loop = loop->next) {
        PyObject *wrap = BPy_IDGroup_MapDataToPy(loop);

        /* BPy_IDGroup_MapDataToPy sets the error */
        if (wrap == nullptr) [[unlikely]] {
          Py_DECREF(dict);
          return nullptr;
        }

        PyDict_SetItemString(dict, loop->name, wrap);
        Py_DECREF(wrap);
      }
      return dict;
    }
  }

  PyErr_Format(PyExc_RuntimeError,
               "%s ERROR: '%s' property exists with a bad type code '%d'!",
               __func__,
               prop->name,
               prop->type);
  return nullptr;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name ID-Property Group Iterator Type
 * \{ */

static PyObject *BPy_IDGroup_Iter_repr(BPy_IDGroup_Iter *self)
{
  if (self->group == nullptr) {
    return PyUnicode_FromFormat("<%s>", Py_TYPE(self)->tp_name);
  }
  return PyUnicode_FromFormat("<%s \"%s\">", Py_TYPE(self)->tp_name, self->group->prop->name);
}

static void BPy_IDGroup_Iter_dealloc(BPy_IDGroup_Iter *self)
{
  if (self->group != nullptr) {
    PyObject_GC_UnTrack(self);
  }
  Py_CLEAR(self->group);
  PyObject_GC_Del(self);
}

static int BPy_IDGroup_Iter_traverse(BPy_IDGroup_Iter *self, visitproc visit, void *arg)
{
  Py_VISIT(self->group);
  return 0;
}

static int BPy_IDGroup_Iter_clear(BPy_IDGroup_Iter *self)
{
  Py_CLEAR(self->group);
  return 0;
}

static int BPy_IDGroup_Iter_is_gc(BPy_IDGroup_Iter *self)
{
  return (self->group != nullptr);
}

static bool BPy_Group_Iter_same_size_or_raise_error(BPy_IDGroup_Iter *self)
{
  if (self->len_init == self->group->prop->len) {
    return true;
  }
  PyErr_SetString(PyExc_RuntimeError, "IDPropertyGroup changed size during iteration");
  return false;
}

static PyObject *BPy_Group_IterKeys_next(BPy_IDGroup_Iter *self)
{
  if (self->cur != nullptr) {
    /* When `cur` is set, `group` cannot be nullptr. */
    if (!BPy_Group_Iter_same_size_or_raise_error(self)) {
      return nullptr;
    }
    IDProperty *cur = self->cur;
    self->cur = self->reversed ? self->cur->prev : self->cur->next;
    return PyUnicode_FromString(cur->name);
  }
  PyErr_SetNone(PyExc_StopIteration);
  return nullptr;
}

static PyObject *BPy_Group_IterValues_next(BPy_IDGroup_Iter *self)
{
  if (self->cur != nullptr) {
    /* When `cur` is set, `group` cannot be nullptr. */
    if (!BPy_Group_Iter_same_size_or_raise_error(self)) {
      return nullptr;
    }
    IDProperty *cur = self->cur;
    self->cur = self->reversed ? self->cur->prev : self->cur->next;
    return BPy_IDGroup_WrapData(self->group->owner_id, cur, self->group->prop);
  }
  PyErr_SetNone(PyExc_StopIteration);
  return nullptr;
}

static PyObject *BPy_Group_IterItems_next(BPy_IDGroup_Iter *self)
{
  if (self->cur != nullptr) {
    /* When `cur` is set, `group` cannot be nullptr. */
    if (!BPy_Group_Iter_same_size_or_raise_error(self)) {
      return nullptr;
    }
