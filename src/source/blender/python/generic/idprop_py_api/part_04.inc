/* SPDX-FileCopyrightText: 2023 Blender Authors
 * SPDX-License-Identifier: GPL-2.0-or-later */


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
        if (UNLIKELY(wrap == nullptr)) {
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

      for (loop = static_cast<IDProperty *>(prop->data.group.first); loop; loop = loop->next) {
        PyObject *wrap = BPy_IDGroup_MapDataToPy(loop);

        /* BPy_IDGroup_MapDataToPy sets the error */
        if (UNLIKELY(wrap == nullptr)) {
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
    IDProperty *cur = self->cur;
    self->cur = self->reversed ? self->cur->prev : self->cur->next;
    PyObject *ret = PyTuple_New(2);
    PyTuple_SET_ITEMS(ret,
                      PyUnicode_FromString(cur->name),
                      BPy_IDGroup_WrapData(self->group->owner_id, cur, self->group->prop));
    return ret;
  }
  PyErr_SetNone(PyExc_StopIteration);
  return nullptr;
}

PyDoc_STRVAR(BPy_IDGroup_IterKeys_doc, "Iterator over :class:`IDPropertyGroup` keys.");
PyDoc_STRVAR(BPy_IDGroup_IterValues_doc, "Iterator over :class:`IDPropertyGroup` values.");
PyDoc_STRVAR(BPy_IDGroup_IterItems_doc,
             "Iterator over :class:`IDPropertyGroup` items (key/value pairs).");

PyTypeObject BPy_IDGroup_IterKeys_Type = {PyVarObject_HEAD_INIT(nullptr, 0)};
PyTypeObject BPy_IDGroup_IterValues_Type = {PyVarObject_HEAD_INIT(nullptr, 0)};
PyTypeObject BPy_IDGroup_IterItems_Type = {PyVarObject_HEAD_INIT(nullptr, 0)};

/* ID Property Group Iterator. */
static void IDGroup_Iter_init_type()
{
#define SHARED_MEMBER_SET(member, value) \
  { \
    k_ty->member = v_ty->member = i_ty->member = value; \
  } \
  ((void)0)

  PyTypeObject *k_ty = &BPy_IDGroup_IterKeys_Type;
  PyTypeObject *v_ty = &BPy_IDGroup_IterValues_Type;
  PyTypeObject *i_ty = &BPy_IDGroup_IterItems_Type;

  /* Unique members. */
  k_ty->tp_name = "IDPropertyGroupIterKeys";
  v_ty->tp_name = "IDPropertyGroupIterValues";
  i_ty->tp_name = "IDPropertyGroupIterItems";

  k_ty->tp_doc = BPy_IDGroup_IterKeys_doc;
  v_ty->tp_doc = BPy_IDGroup_IterValues_doc;
  i_ty->tp_doc = BPy_IDGroup_IterItems_doc;

  k_ty->tp_iternext = reinterpret_cast<iternextfunc>(BPy_Group_IterKeys_next);
  v_ty->tp_iternext = reinterpret_cast<iternextfunc>(BPy_Group_IterValues_next);
  i_ty->tp_iternext = reinterpret_cast<iternextfunc>(BPy_Group_IterItems_next);

  /* Shared members. */
  SHARED_MEMBER_SET(tp_basicsize, sizeof(BPy_IDGroup_Iter));
  SHARED_MEMBER_SET(tp_dealloc, (destructor)BPy_IDGroup_Iter_dealloc);
  SHARED_MEMBER_SET(tp_repr, (reprfunc)BPy_IDGroup_Iter_repr);
  SHARED_MEMBER_SET(tp_flags, Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC);
  SHARED_MEMBER_SET(tp_traverse, (traverseproc)BPy_IDGroup_Iter_traverse);
  SHARED_MEMBER_SET(tp_clear, (inquiry)BPy_IDGroup_Iter_clear);
  SHARED_MEMBER_SET(tp_is_gc, (inquiry)BPy_IDGroup_Iter_is_gc);
  SHARED_MEMBER_SET(tp_iter, PyObject_SelfIter);

#undef SHARED_MEMBER_SET
}

static PyObject *IDGroup_Iter_New_WithType(BPy_IDProperty *group,
                                           const bool reversed,
                                           PyTypeObject *type)
{
  BLI_assert(group ? group->prop->type == IDP_GROUP : true);
  BPy_IDGroup_Iter *iter = PyObject_GC_New(BPy_IDGroup_Iter, type);
  iter->reversed = reversed;
  iter->group = group;
  if (group != nullptr) {
    Py_INCREF(group);
    BLI_assert(!PyObject_GC_IsTracked((PyObject *)iter));
    PyObject_GC_Track(iter);
    iter->cur = static_cast<IDProperty *>(
        (reversed ? group->prop->data.group.last : group->prop->data.group.first));
    iter->len_init = group->prop->len;
  }
  else {
    iter->cur = nullptr;
    iter->len_init = 0;
  }
  return reinterpret_cast<PyObject *>(iter);
}

static PyObject *BPy_IDGroup_IterKeys_CreatePyObject(BPy_IDProperty *group, const bool reversed)
{
  return IDGroup_Iter_New_WithType(group, reversed, &BPy_IDGroup_IterKeys_Type);
}

static PyObject *BPy_IDGroup_IterValues_CreatePyObject(BPy_IDProperty *group, const bool reversed)
{
  return IDGroup_Iter_New_WithType(group, reversed, &BPy_IDGroup_IterValues_Type);
}

static PyObject *BPy_IDGroup_IterItems_CreatePyObject(BPy_IDProperty *group, const bool reversed)
{
  return IDGroup_Iter_New_WithType(group, reversed, &BPy_IDGroup_IterItems_Type);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name ID-Property Group View Types (Keys/Values/Items)
 *
 * This view types is a thin wrapper on keys/values/items, this matches Python's `dict_view` type.
 * This is returned by `property.keys()` and is separate from the iterator that loops over keys.
 *
 * There are some less common features this type could support (matching Python's `dict_view`)
 *
 * TODO:
 * - Efficient contains checks for values and items which currently convert to a list first.
 * - Missing `dict_views.isdisjoint`.
 * - Missing `tp_as_number` (`nb_subtract`, `nb_and`, `nb_xor`, `nb_or`).
 * \{ */

static PyObject *BPy_IDGroup_View_repr(BPy_IDGroup_View *self)
{
  if (self->group == nullptr) {
    return PyUnicode_FromFormat("<%s>", Py_TYPE(self)->tp_name);
  }
  return PyUnicode_FromFormat("<%s \"%s\">", Py_TYPE(self)->tp_name, self->group->prop->name);
}

static void BPy_IDGroup_View_dealloc(BPy_IDGroup_View *self)
{
  if (self->group != nullptr) {
    PyObject_GC_UnTrack(self);
  }
  Py_CLEAR(self->group);
  PyObject_GC_Del(self);
}

static int BPy_IDGroup_View_traverse(BPy_IDGroup_View *self, visitproc visit, void *arg)
{
  Py_VISIT(self->group);
  return 0;
}

static int BPy_IDGroup_View_clear(BPy_IDGroup_View *self)
{
  Py_CLEAR(self->group);
  return 0;
}

static int BPy_IDGroup_View_is_gc(BPy_IDGroup_View *self)
{
  return (self->group != nullptr);
}

/* View Specific API's (Key/Value/Items). */

static PyObject *BPy_Group_ViewKeys_iter(BPy_IDGroup_View *self)
{
  return BPy_IDGroup_IterKeys_CreatePyObject(self->group, self->reversed);
}

static PyObject *BPy_Group_ViewValues_iter(BPy_IDGroup_View *self)
{
  return BPy_IDGroup_IterValues_CreatePyObject(self->group, self->reversed);
}

static PyObject *BPy_Group_ViewItems_iter(BPy_IDGroup_View *self)
{
  return BPy_IDGroup_IterItems_CreatePyObject(self->group, self->reversed);
}

static Py_ssize_t BPy_Group_View_len(BPy_IDGroup_View *self)
{
  if (self->group == nullptr) {
    return 0;
  }
  return self->group->prop->len;
}

static int BPy_Group_ViewKeys_Contains(BPy_IDGroup_View *self, PyObject *value)
{
  if (self->group == nullptr) {
    return 0;
  }
  return BPy_IDGroup_Contains(self->group, value);
}

static int BPy_Group_ViewValues_Contains(BPy_IDGroup_View *self, PyObject *value)
{
  if (self->group == nullptr) {
    return 0;
  }
  /* TODO: implement this without first converting to a list. */
  PyObject *list = PySequence_List(reinterpret_cast<PyObject *>(self));
  const int result = PySequence_Contains(list, value);
  Py_DECREF(list);
  return result;
}

static int BPy_Group_ViewItems_Contains(BPy_IDGroup_View *self, PyObject *value)
{
  if (self->group == nullptr) {
    return 0;
  }
  /* TODO: implement this without first converting to a list. */
  PyObject *list = PySequence_List(reinterpret_cast<PyObject *>(self));
  const int result = PySequence_Contains(list, value);
  Py_DECREF(list);
  return result;
}
