/* SPDX-FileCopyrightText: 2023 Blender Authors
 * SPDX-License-Identifier: GPL-2.0-or-later */


/** \} */

/* -------------------------------------------------------------------- */
/** \name ID-Property from Python (Internal Conversions)
 * \{ */

/**
 * The `idp_from_Py*` functions expect that the input type has been checked before
 * and return nullptr if the IDProperty can't be created.
 *
 * \param prop_exist: If not null, attempt to assign given `ob` value to this property first, and
 * only create a new one if not possible.
 * If no assignment (or conversion and assignment) is possible, the current
 * value remains unchanged.
 *
 * \param do_conversion: If `true`, allow some 'reasonable' conversion of input value to match the
 * `prop_exist` property type. E.g. can convert an `int` to a `float`, but not
 * the other way around.
 *
 * \param can_create: Whether creating a new IDProperty is allowed.
 *
 * \return `prop_exist` if given and it could be assigned given `ob` value, a new IDProperty
 *         otherwise.
 */

static IDProperty *idp_from_PyFloat(IDProperty *prop_exist,
                                    const char *name,
                                    PyObject *ob,
                                    const bool do_conversion,
                                    const bool can_create)
{
  IDProperty *prop = nullptr;
  const double value = PyFloat_AsDouble(ob);
  if (prop_exist) {
    if (prop_exist->type == IDP_DOUBLE) {
      IDP_double_set(prop_exist, value);
      prop = prop_exist;
    }
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
