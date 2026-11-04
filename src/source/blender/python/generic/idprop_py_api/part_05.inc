/* SPDX-FileCopyrightText: 2023 Blender Authors
 * SPDX-License-Identifier: GPL-2.0-or-later */


static PySequenceMethods BPy_IDGroup_ViewKeys_as_sequence = {
    /*sq_length*/ reinterpret_cast<lenfunc>(BPy_Group_View_len),
    /*sq_concat*/ nullptr,
    /*sq_repeat*/ nullptr,
    /*sq_item*/ nullptr,
    /*was_sq_slice*/ nullptr,
    /*sq_ass_item*/ nullptr,
    /*was_sq_ass_slice*/ nullptr,
    /*sq_contains*/ reinterpret_cast<objobjproc>(BPy_Group_ViewKeys_Contains),
};

static PySequenceMethods BPy_IDGroup_ViewValues_as_sequence = {
    /*sq_length*/ reinterpret_cast<lenfunc>(BPy_Group_View_len),
    /*sq_concat*/ nullptr,
    /*sq_repeat*/ nullptr,
    /*sq_item*/ nullptr,
    /*was_sq_slice*/ nullptr,
    /*sq_ass_item*/ nullptr,
    /*was_sq_ass_slice*/ nullptr,
    /*sq_contains*/ reinterpret_cast<objobjproc>(BPy_Group_ViewValues_Contains),
};

static PySequenceMethods BPy_IDGroup_ViewItems_as_sequence = {
    /*sq_length*/ reinterpret_cast<lenfunc>(BPy_Group_View_len),
    /*sq_concat*/ nullptr,
    /*sq_repeat*/ nullptr,
    /*sq_item*/ nullptr,
    /*was_sq_slice*/ nullptr,
    /*sq_ass_item*/ nullptr,
    /*was_sq_ass_slice*/ nullptr,
    /*sq_contains*/ reinterpret_cast<objobjproc>(BPy_Group_ViewItems_Contains),
};

/* Methods. */

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_View_reversed_doc,
    "Return a reverse iterator over the ID Property keys values or items.");
static PyObject *BPy_IDGroup_View_reversed(BPy_IDGroup_View *self, PyObject * /*ignored*/)
{
  BPy_IDGroup_View *result = IDGroup_View_New_WithType(self->group, Py_TYPE(self));
  result->reversed = !self->reversed;
  return reinterpret_cast<PyObject *>(result);
}

static PyMethodDef BPy_IDGroup_View_methods[] = {
    {"__reversed__",
     (PyCFunction)(void (*)())BPy_IDGroup_View_reversed,
     METH_NOARGS,
     BPy_IDGroup_View_reversed_doc},
    {nullptr, nullptr},
};

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_ViewKeys_doc,
    "A view of :class:`IDPropertyGroup` keys "
    "(supports ``len()``, ``in``, iteration, and ``reversed()``).");
PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_ViewValues_doc,
    "A view of :class:`IDPropertyGroup` values "
    "(supports ``len()``, ``in``, iteration, and ``reversed()``).");
PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_ViewItems_doc,
    "A view of :class:`IDPropertyGroup` items as key/value pairs "
    "(supports ``len()``, ``in``, iteration, and ``reversed()``).");

PyTypeObject BPy_IDGroup_ViewKeys_Type = {PyVarObject_HEAD_INIT(nullptr, 0)};
PyTypeObject BPy_IDGroup_ViewValues_Type = {PyVarObject_HEAD_INIT(nullptr, 0)};
PyTypeObject BPy_IDGroup_ViewItems_Type = {PyVarObject_HEAD_INIT(nullptr, 0)};

/* ID Property Group View. */
static void IDGroup_View_init_type()
{
  PyTypeObject *k_ty = &BPy_IDGroup_ViewKeys_Type;
  PyTypeObject *v_ty = &BPy_IDGroup_ViewValues_Type;
  PyTypeObject *i_ty = &BPy_IDGroup_ViewItems_Type;

  /* Unique members. */
  k_ty->tp_name = "IDPropertyGroupViewKeys";
  v_ty->tp_name = "IDPropertyGroupViewValues";
  i_ty->tp_name = "IDPropertyGroupViewItems";

  k_ty->tp_doc = BPy_IDGroup_ViewKeys_doc;
  v_ty->tp_doc = BPy_IDGroup_ViewValues_doc;
  i_ty->tp_doc = BPy_IDGroup_ViewItems_doc;

  k_ty->tp_iter = reinterpret_cast<getiterfunc>(BPy_Group_ViewKeys_iter);
  v_ty->tp_iter = reinterpret_cast<getiterfunc>(BPy_Group_ViewValues_iter);
  i_ty->tp_iter = reinterpret_cast<getiterfunc>(BPy_Group_ViewItems_iter);

  k_ty->tp_as_sequence = &BPy_IDGroup_ViewKeys_as_sequence;
  v_ty->tp_as_sequence = &BPy_IDGroup_ViewValues_as_sequence;
  i_ty->tp_as_sequence = &BPy_IDGroup_ViewItems_as_sequence;

/* Shared members. */
#define SHARED_MEMBER_SET(member, value) \
  { \
    k_ty->member = v_ty->member = i_ty->member = value; \
  } \
  ((void)0)

  SHARED_MEMBER_SET(tp_basicsize, sizeof(BPy_IDGroup_View));
  SHARED_MEMBER_SET(tp_dealloc, (destructor)BPy_IDGroup_View_dealloc);
  SHARED_MEMBER_SET(tp_repr, (reprfunc)BPy_IDGroup_View_repr);
  SHARED_MEMBER_SET(tp_flags, Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC);
  SHARED_MEMBER_SET(tp_traverse, (traverseproc)BPy_IDGroup_View_traverse);
  SHARED_MEMBER_SET(tp_clear, (inquiry)BPy_IDGroup_View_clear);
  SHARED_MEMBER_SET(tp_is_gc, (inquiry)BPy_IDGroup_View_is_gc);
  SHARED_MEMBER_SET(tp_methods, BPy_IDGroup_View_methods);

#undef SHARED_MEMBER_SET
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name ID-Property Group Methods
 * \{ */

PyDoc_STRVAR(
    /* Wrap. */
    BPy_IDGroup_pop_doc,
    ".. method:: pop(key, default)\n"
    "\n"
    "   Remove an item from the group, returning a Python representation.\n"
    "\n"
    "   :raises KeyError: When the item doesn't exist and no *default* is given.\n"
    "\n"
    "   :param key: Name of item to remove.\n"
    "   :type key: str\n"
    "   :param default: Value to return when *key* isn't found "
    "(optional, a :exc:`KeyError` is raised when omitted and the key is not found).\n"
    "   :type default: Any\n"
    "   :return: A Python representation of the removed item, or *default*.\n"
    "   :rtype: Any\n");
static PyObject *BPy_IDGroup_pop(BPy_IDProperty *self, PyObject *args)
{
  IDProperty *idprop;
  PyObject *pyform;

  char *key;
  PyObject *def = nullptr;

  if (!PyArg_ParseTuple(args, "s|O:pop", &key, &def)) {
    return nullptr;
  }

  idprop = IDP_GetPropertyFromGroup(self->prop, key);
  if (idprop == nullptr) {
    if (def == nullptr) {
      PyErr_SetString(PyExc_KeyError, "item not in group");
      return nullptr;
    }
    return Py_NewRef(def);
  }

  pyform = BPy_IDGroup_MapDataToPy(idprop);
  if (pyform == nullptr) {
    /* Ok something bad happened with the #PyObject, so don't remove the prop from the group.
     * if `pyform` is nullptr, then it already should have raised an exception. */
    return nullptr;
  }

  IDP_FreeFromGroup(self->prop, idprop);
  return pyform;
}

/* utility function */
static void BPy_IDGroup_CorrectListLen(IDProperty *prop, PyObject *seq, int len, const char *func)
{
  int j;

  printf("%s: ID Property Error found and corrected!\n", func);

  /* fill rest of list with valid references to None */
  for (j = len; j < prop->len; j++) {
    PyList_SET_ITEM(seq, j, Py_NewRef(Py_None));
  }

  /* Set correct group length. */
  prop->len = len;
}

PyObject *BPy_Wrap_GetKeys(IDProperty *prop)
{
  PyObject *list = PyList_New(prop->len);
  IDProperty *loop;
  int i;

  for (i = 0, loop = static_cast<IDProperty *>(prop->data.group.first); loop && (i < prop->len);
       loop = loop->next, i++)
  {
    PyList_SET_ITEM(list, i, PyUnicode_FromString(loop->name));
  }

  /* if the id prop is corrupt, count the remaining */
  for (; loop; loop = loop->next, i++) {
    /* pass */
  }

  if (i != prop->len) { /* if the loop didn't finish, we know the length is wrong */
    BPy_IDGroup_CorrectListLen(prop, list, i, __func__);
    Py_DECREF(list); /* Free the list. */
    /* Call self again. */
    return BPy_Wrap_GetKeys(prop);
  }

  return list;
}

PyObject *BPy_Wrap_GetValues(ID *id, IDProperty *prop)
{
  PyObject *list = PyList_New(prop->len);
  IDProperty *loop;
  int i;

  for (i = 0, loop = static_cast<IDProperty *>(prop->data.group.first); loop;
       loop = loop->next, i++)
  {
    PyList_SET_ITEM(list, i, BPy_IDGroup_WrapData(id, loop, prop));
  }

  if (i != prop->len) {
    BPy_IDGroup_CorrectListLen(prop, list, i, __func__);
    Py_DECREF(list); /* Free the list. */
    /* Call self again. */
    return BPy_Wrap_GetValues(id, prop);
  }

  return list;
}

PyObject *BPy_Wrap_GetItems(ID *id, IDProperty *prop)
{
  PyObject *seq = PyList_New(prop->len);
  IDProperty *loop;
  int i;

  for (i = 0, loop = static_cast<IDProperty *>(prop->data.group.first); loop;
       loop = loop->next, i++)
  {
    PyObject *item = PyTuple_New(2);
    PyTuple_SET_ITEMS(
        item, PyUnicode_FromString(loop->name), BPy_IDGroup_WrapData(id, loop, prop));
    PyList_SET_ITEM(seq, i, item);
  }

  if (i != prop->len) {
    BPy_IDGroup_CorrectListLen(prop, seq, i, __func__);
    Py_DECREF(seq); /* Free the list. */
    /* Call self again. */
    return BPy_Wrap_GetItems(id, prop);
  }

  return seq;
}

PyObject *BPy_Wrap_GetKeys_View_WithID(ID *id, IDProperty *prop)
{
  PyObject *self = prop ? idprop_py_from_idp_group(id, prop, nullptr) : nullptr;
  PyObject *ret = BPy_IDGroup_ViewKeys_CreatePyObject(reinterpret_cast<BPy_IDProperty *>(self));
  Py_XDECREF(self); /* Owned by `ret`. */
  return ret;
}

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
    if (UNLIKELY(self->prop == other->prop)) {
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

  if (!PyArg_ParseTuple(args, "s|O:get", &key, &def)) {
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
