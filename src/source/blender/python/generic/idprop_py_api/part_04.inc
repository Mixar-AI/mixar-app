/* SPDX-FileCopyrightText: 2023 Blender Authors
 * SPDX-License-Identifier: GPL-2.0-or-later */
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
  if (group && UNLIKELY(group->prop == nullptr)) { return BPy_IDProperty_raise_removed(); } /* MIXAR-2031 */
  BLI_assert(group ? group->prop->type == IDP_GROUP : true);
  BPy_IDGroup_Iter *iter = PyObject_GC_New(BPy_IDGroup_Iter, type);
  iter->reversed = reversed;
  iter->group = group;
  if (group != nullptr) {
    Py_INCREF(group);
    BLI_assert(!PyObject_GC_IsTracked((PyObject *)iter));
    PyObject_GC_Track(iter);
    iter->cur = static_cast<IDProperty *>(
        (reversed ? group->prop->data.group.last() : group->prop->data.group.first()));
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
  if (self->group) { BPY_IDPROP_CHECK_INT(self->group->prop); } /* MIXAR-2031 */
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
  BPY_IDPROP_CHECK_OBJ(self->prop); /* MIXAR-2031 */
  IDProperty *idprop;
  PyObject *pyform;

  char *key;
  PyObject *def = nullptr;

  if (!PyArg_ParseTuple(args,
                        "s" /* `key` */
                        "|" /* Optional arguments. */
                        "O" /* `default` */
                        ":pop",
                        &key,
                        &def))
  {
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

  for (i = 0, loop = prop->data.group.first(); loop && (i < prop->len); loop = loop->next, i++) {
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

  for (i = 0, loop = prop->data.group.first(); loop; loop = loop->next, i++) {
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

  for (i = 0, loop = prop->data.group.first(); loop; loop = loop->next, i++) {
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
