/* SPDX-FileCopyrightText: 2023 Blender Authors
 * SPDX-License-Identifier: GPL-2.0-or-later */


static IDProperty *idp_from_PySequence_Fast(IDProperty *prop_exist,
                                            const char *name,
                                            PyObject *ob,
                                            const bool do_conversion,
                                            const bool can_create)
{
  IDProperty *prop = nullptr;
  IDPropertyTemplate val = {0};

  PyObject **ob_seq_fast_items;
  PyObject *item;
  int i;

  ob_seq_fast_items = PySequence_Fast_ITEMS(ob);

  /* IDProperties do not support mixed type of data in an array. Try to extract a single type from
   * the whole sequence, or error. */
  val.array.type = idp_sequence_type(ob);
  if (val.array.type == char(-1)) {
    PyErr_SetString(PyExc_TypeError,
                    "only floats, ints, booleans and dicts are allowed in ID property arrays");
    return nullptr;
  }
  if (!ELEM(val.array.type, IDP_DOUBLE, IDP_INT, IDP_BOOLEAN, IDP_IDPARRAY)) {
    /* Should never happen. */
    PyErr_SetString(PyExc_RuntimeError, "internal error with idp array.type");
    BLI_assert_unreachable();
    return nullptr;
  }

  val.array.len = PySequence_Fast_GET_SIZE(ob);

  /* NOTE: For now do not consider resizing existing array property. Also do not handle IDPARRAY.
   * - 'static type' also means 'fixed length' (e.g. vectors or matrices cases).
   * - For 'dynamic type' case, it's not really a problem if array properties get replaced
   * currently.
   */
  if (prop_exist && prop_exist->len == val.array.len) {
    switch (val.array.type) {
      case IDP_DOUBLE: {
        const bool to_float = (prop_exist->subtype == IDP_FLOAT);
        if (!(prop_exist->type == IDP_ARRAY &&
              (prop_exist->subtype == IDP_DOUBLE || (do_conversion && to_float))))
        {
          break;
        }
        prop = prop_exist;
        void *prop_data = IDP_array_voidp_get(prop);
        for (i = 0; i < val.array.len; i++) {
          item = ob_seq_fast_items[i];
          const double value = PyFloat_AsDouble(item);
          if ((value == -1.0) && PyErr_Occurred()) {
            continue;
          }
          if (to_float) {
            static_cast<float *>(prop_data)[i] = float(value);
          }
          else {
            static_cast<double *>(prop_data)[i] = value;
          }
        }
        break;
      }
      case IDP_INT: {
        const bool to_float = (prop_exist->subtype == IDP_FLOAT);
        const bool to_double = (prop_exist->subtype == IDP_DOUBLE);
        if (!(prop_exist->type == IDP_ARRAY &&
              (prop_exist->subtype == IDP_INT || (do_conversion && (to_float || to_double)))))
        {
          break;
        }
        prop = prop_exist;
        void *prop_data = IDP_array_voidp_get(prop);
        for (i = 0; i < val.array.len; i++) {
          item = ob_seq_fast_items[i];
          if (to_float || to_double) {
            const int64_t value = PyC_Long_AsI64(item);
            if ((value == -1) && PyErr_Occurred()) {
              continue;
            }
            if (to_float) {
              static_cast<float *>(prop_data)[i] = float(value);
            }
            else { /* if (to_double) */
              static_cast<double *>(prop_data)[i] = double(value);
            }
          }
          else {
            const int value = PyC_Long_AsI32(item);
            if ((value == -1) && PyErr_Occurred()) {
              continue;
            }
            static_cast<int *>(prop_data)[i] = value;
          }
        }
        break;
      }
      case IDP_BOOLEAN: {
        const bool to_int = (prop_exist->subtype == IDP_INT);
        if (!(prop_exist->type == IDP_ARRAY &&
              (prop_exist->subtype == IDP_BOOLEAN || (do_conversion && to_int))))
        {
          break;
        }
        prop = prop_exist;
        void *prop_data = IDP_array_voidp_get(prop);
        for (i = 0; i < val.array.len; i++) {
          item = ob_seq_fast_items[i];
          const int value = PyC_Long_AsBool(item);
          if ((value == -1) && PyErr_Occurred()) {
            continue;
          }
          if (to_int) {
            static_cast<int *>(prop_data)[i] = value;
          }
          else {
            static_cast<bool *>(prop_data)[i] = bool(value);
          }
        }
        break;
      }
      case IDP_IDPARRAY: {
        /* TODO? */
        break;
      }
    }
  }

  if (prop || !can_create) {
    return prop;
  }

  switch (val.array.type) {
    case IDP_DOUBLE: {
      double *prop_data;
      prop = IDP_New(IDP_ARRAY, &val, name);
      prop_data = IDP_array_double_get(prop);
      for (i = 0; i < val.array.len; i++) {
        item = ob_seq_fast_items[i];
        if (((prop_data[i] = PyFloat_AsDouble(item)) == -1.0) && PyErr_Occurred()) {
          IDP_FreeProperty(prop);
          return nullptr;
        }
      }
      break;
    }
    case IDP_INT: {
      int *prop_data;
      prop = IDP_New(IDP_ARRAY, &val, name);
      prop_data = IDP_array_int_get(prop);
      for (i = 0; i < val.array.len; i++) {
        item = ob_seq_fast_items[i];
        if (((prop_data[i] = PyC_Long_AsI32(item)) == -1) && PyErr_Occurred()) {
          IDP_FreeProperty(prop);
          return nullptr;
        }
      }
      break;
    }
    case IDP_IDPARRAY: {
      prop = IDP_NewIDPArray(name);
      for (i = 0; i < val.array.len; i++) {
        item = ob_seq_fast_items[i];
        if (BPy_IDProperty_Map_ValidateAndCreate(nullptr, prop, item) == false) {
          IDP_FreeProperty(prop);
          return nullptr;
        }
      }
      break;
    }
    case IDP_BOOLEAN: {
      prop = IDP_New(IDP_ARRAY, &val, name);
      int8_t *prop_data = IDP_array_bool_get(prop);
      for (i = 0; i < val.array.len; i++) {
        item = ob_seq_fast_items[i];
        const int value = PyC_Long_AsBool(item);
        if ((value == -1) && PyErr_Occurred()) {
          IDP_FreeProperty(prop);
          return nullptr;
        }
        prop_data[i] = (value != 0);
      }
      break;
    }
  }
  return prop;
}

static IDProperty *idp_from_PySequence(IDProperty *prop_exist,
                                       const char *name,
                                       PyObject *ob,
                                       const bool do_conversion,
                                       const bool can_create)
{
  Py_buffer buffer;
  bool use_buffer = false;
  int idp_buffer_type = -1;

  if (PyObject_CheckBuffer(ob)) {
    if (PyObject_GetBuffer(ob, &buffer, PyBUF_ND | PyBUF_FORMAT) == -1) {
      /* Request failed. A `PyExc_BufferError` will have been raised,
       * so clear it to silently fall back to accessing as a sequence. */
      PyErr_Clear();
    }
    else {
      idp_buffer_type = idp_array_type_from_formatstr_and_size(buffer.format, buffer.itemsize);
      if (idp_buffer_type != -1) {
        /* If creating a new IDProp is not allowed, and the existing one is not usable (same size
         * and type), then the 'buffer assignment' process cannot be used. */
        if (!can_create && (!prop_exist || (prop_exist->type != idp_buffer_type) ||
                            (prop_exist->len != buffer.len)))
        {
          PyBuffer_Release(&buffer);
        }
        else {
          use_buffer = true;
        }
      }
      else {
        PyBuffer_Release(&buffer);
      }
    }
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
