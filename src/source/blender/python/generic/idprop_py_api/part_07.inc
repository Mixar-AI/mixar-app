/* SPDX-FileCopyrightText: 2023 Blender Authors
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \} */

/* -------------------------------------------------------------------- */
/** \name Public Module 'idprop'
 * \{ */

static PyMethodDef IDProp_methods[] = {
    {nullptr, nullptr, 0, nullptr},
};

PyDoc_STRVAR(
    /* Wrap. */
    IDProp_module_doc,
    "This module provides access to ID property types, used for\n"
    "custom properties on data-blocks, accessed via ``[\"key\"]`` syntax.\n"
    "\n"
    "- See :ref:`info_quickstart-custom_properties` for example usage.\n"
    "- See :ref:`bpy_types-custom_properties` for types that support custom properties.\n");
static PyModuleDef IDProp_module_def = {
    /*m_base*/ PyModuleDef_HEAD_INIT,
    /*m_name*/ "idprop",
    /*m_doc*/ IDProp_module_doc,
    /*m_size*/ 0,
    /*m_methods*/ IDProp_methods,
    /*m_slots*/ nullptr,
    /*m_traverse*/ nullptr,
    /*m_clear*/ nullptr,
    /*m_free*/ nullptr,
};

PyObject *BPyInit_idprop()
{
  PyObject *mod;
  PyObject *submodule;
  PyObject *sys_modules = PyImport_GetModuleDict();

  mod = PyModule_Create(&IDProp_module_def);

  /* idprop.types */
  PyModule_AddObject(mod, "types", (submodule = BPyInit_idprop_types()));
  PyC_Module_AddToSysModules(sys_modules, submodule);

  return mod;
}

/** \} */

}  // namespace blender
