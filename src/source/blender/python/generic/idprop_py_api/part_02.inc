/* SPDX-FileCopyrightText: 2023 Blender Authors
 * SPDX-License-Identifier: GPL-2.0-or-later */
    else if (do_conversion) {
      switch (prop_exist->type) {
        case IDP_FLOAT:
          IDP_float_set(prop_exist, float(value));
          prop = prop_exist;
          break;
        case IDP_STRING:
        case IDP_INT:
        case IDP_ARRAY:
        case IDP_GROUP:
        case IDP_ID:
        case IDP_DOUBLE:
        case IDP_IDPARRAY:
        case IDP_BOOLEAN:
          break;
      }
    }
  }
  if (!prop && can_create) {
    prop = bke::idprop::create(name, value).release();
  }
  return prop;
}

static IDProperty *idp_from_PyBool(IDProperty *prop_exist,
                                   const char *name,
                                   PyObject *ob,
                                   const bool do_conversion,
                                   const bool can_create)
{
  IDProperty *prop = nullptr;
  const bool value = PyC_Long_AsBool(ob);
  if (prop_exist) {
    if (prop_exist->type == IDP_BOOLEAN) {
      IDP_bool_set(prop_exist, value);
      prop = prop_exist;
    }
    else if (do_conversion) {
      switch (prop_exist->type) {
        case IDP_INT:
          IDP_int_set(prop_exist, int(value));
          prop = prop_exist;
          break;
        case IDP_STRING:
        case IDP_FLOAT:
        case IDP_ARRAY:
        case IDP_GROUP:
        case IDP_ID:
        case IDP_DOUBLE:
        case IDP_IDPARRAY:
        case IDP_BOOLEAN:
          break;
      }
    }
  }
  if (!prop && can_create) {
    prop = bke::idprop::create_bool(name, value).release();
  }
  return prop;
}

static IDProperty *idp_from_PyLong(IDProperty *prop_exist,
                                   const char *name,
                                   PyObject *ob,
                                   const bool do_conversion,
                                   const bool can_create)
{
  IDProperty *prop = nullptr;
  if (prop_exist) {
    if (prop_exist->type == IDP_INT) {
      const int value = PyC_Long_AsI32(ob);
      if (value == -1 && PyErr_Occurred()) {
        return prop;
      }
      IDP_int_set(prop_exist, value);
      prop = prop_exist;
    }
    else if (do_conversion) {
      const int64_t value = PyC_Long_AsI64(ob);
      if (value == -1 && PyErr_Occurred()) {
        return prop;
      }
      switch (prop_exist->type) {
        case IDP_FLOAT:
          IDP_float_set(prop_exist, float(value));
          prop = prop_exist;
          break;
        case IDP_DOUBLE:
          IDP_double_set(prop_exist, double(value));
          prop = prop_exist;
          break;
        case IDP_STRING:
        case IDP_INT:
        case IDP_ARRAY:
        case IDP_GROUP:
        case IDP_ID:
        case IDP_IDPARRAY:
        case IDP_BOOLEAN:
          break;
      }
    }
  }
  if (!prop && can_create) {
    const int value = PyC_Long_AsI32(ob);
    if (value == -1 && PyErr_Occurred()) {
      return prop;
    }
    prop = bke::idprop::create(name, value).release();
  }
  return prop;
}

static IDProperty *idp_from_PyUnicode(IDProperty *prop_exist,
                                      const char *name,
                                      PyObject *ob,
                                      const bool /*do_conversion*/,
                                      const bool can_create)
{
  IDProperty *prop = nullptr;
  Py_ssize_t value_len = 0;
  const char *value = nullptr;

#ifdef USE_STRING_COERCE
  PyObject *value_coerce = nullptr;
  value = PyC_UnicodeAsBytesAndSize(ob, &value_len, &value_coerce);
#else
  value = PyUnicode_AsUTF8AndSize(ob, &value_len);
#endif

  if (prop_exist) {
    if (prop_exist->type == IDP_STRING && prop_exist->subtype == IDP_STRING_SUB_UTF8) {
      IDP_AssignStringMaxSize(prop_exist, value, int(value_len) + 1);
      prop = prop_exist;
    }
    /* No conversion. */
  }

  if (!prop && can_create) {
    IDPropertyTemplate val = {0};
    val.string.str = value;
    val.string.len = int(value_len) + 1;
    val.string.subtype = IDP_STRING_SUB_UTF8;
    prop = IDP_New(IDP_STRING, &val, name);
  }

#ifdef USE_STRING_COERCE
  Py_XDECREF(value_coerce);
#endif

  return prop;
}

static IDProperty *idp_from_PyBytes(IDProperty *prop_exist,
                                    const char *name,
                                    PyObject *ob,
                                    const bool /*do_conversion*/,
                                    const bool can_create)
{
  IDProperty *prop = nullptr;
  Py_ssize_t value_len = PyBytes_GET_SIZE(ob);
  const char *value = PyBytes_AS_STRING(ob);

  if (prop_exist) {
    if (prop_exist->type == IDP_STRING && prop_exist->subtype == IDP_STRING_SUB_BYTE) {
      /* Binary properties have an exact byte length, not a NUL terminator.
       * AssignStringMaxSize truncates embedded zero bytes on reassignment. */
      IDP_ResizeArray(prop_exist, int(value_len));
      if (value_len != 0) {
        memcpy(prop_exist->data.pointer, value, size_t(value_len));
      }
      prop = prop_exist;
    }
    /* No conversion. */
  }

  if (!prop && can_create) {
    IDPropertyTemplate val = {0};
    val.string.str = value;
    val.string.len = int(value_len);
    val.string.subtype = IDP_STRING_SUB_BYTE;
    prop = IDP_New(IDP_STRING, &val, name);
  }

  return prop;
}

static int idp_array_type_from_formatstr_and_size(const char *typestr, Py_ssize_t itemsize)
{
  const char format = PyC_StructFmt_type_from_str(typestr);

  if (PyC_StructFmt_type_is_float_any(format)) {
    if (itemsize == 4) {
      return IDP_FLOAT;
    }
    if (itemsize == 8) {
      return IDP_DOUBLE;
    }
  }
  if (PyC_StructFmt_type_is_int_any(format)) {
    if (itemsize == 4) {
      return IDP_INT;
    }
    /* TODO: Support Booleans? */
  }

  return -1;
}

static const char *idp_format_from_array_type(int type)
{
  if (type == IDP_INT) {
    return "i";
  }
  if (type == IDP_FLOAT) {
    return "f";
  }
  if (type == IDP_DOUBLE) {
    return "d";
  }
  if (type == IDP_BOOLEAN) {
    return "b";
  }
  return nullptr;
}

static IDProperty *idp_from_PySequence_Buffer(IDProperty *prop_exist,
                                              const char *name,
                                              const Py_buffer &buffer,
                                              const int idp_type,
                                              const bool /*do_conversion*/,
                                              const bool can_create)
{
  BLI_assert(idp_type != -1);
  IDProperty *prop = nullptr;

  if (prop_exist) {
    if (prop_exist->type == IDP_ARRAY && prop_exist->subtype == idp_type) {
      BLI_assert(buffer.len == prop_exist->len);
      memcpy(IDP_array_voidp_get(prop_exist), buffer.buf, buffer.len);
      prop = prop_exist;
    }
    /* No conversion. */
  }
  if (!prop && can_create) {
    IDPropertyTemplate val = {0};
    val.array.type = idp_type;
    val.array.len = buffer.len / buffer.itemsize;
    prop = IDP_New(IDP_ARRAY, &val, name);
    memcpy(IDP_array_voidp_get(prop), buffer.buf, buffer.len);
  }
  return prop;
}

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
