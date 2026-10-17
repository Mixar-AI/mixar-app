# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The restricted ``__import__`` installed in the agent sandbox's builtins."""

import builtins
import sys

from .sandbox_modules import is_denied_module, safe_module

# Packages a script may import beyond the pre-injected names. Addon modules
# (mixar.*) let pre-written tool scripts reach paint/addon internals; numpy
# lazily imports its own submodules (numpy.core._methods etc.);
# mathutils/bmesh/bpy_extras submodules (mathutils.bvhtree, bmesh.ops,
# bpy_extras.view3d_utils, ...) grant nothing beyond the already injected
# parents. NOT urllib.* -- only the RestrictedUrllib wrapper may reach the
# network.
_PASS_THROUGH_PACKAGES = ("mixar", "numpy", "mathutils", "bmesh", "bpy_extras")


def make_restricted_import(exec_namespace):
    """Build the ``__import__`` for one execution namespace.

    ``import bpy`` / ``import json`` resolve to the proxies already in the
    namespace; anything else is refused unless it lives in one of the
    pass-through packages, and never when it is a denied module
    (``sandbox_modules._DENIED_SUBMODULES``) or inside one.
    """
    allowed = set(exec_namespace.keys()) - {"__builtins__", "__name__", "open"}
    real_import = builtins.__import__

    def _import_lazy_submodules(package, fromlist):
        # `from bpy_extras import anim_utils` names a submodule the package
        # does not import itself. The real import system loads it from the
        # fromlist; the injected proxy cannot, so the name was missing until
        # something else had imported it. Load each such submodule the way
        # `import bpy_extras.anim_utils` already may (denied ones excepted);
        # the proxy then hands it out like any same-package attribute.
        real = sys.modules.get(package)
        for item in fromlist:
            if not isinstance(item, str) or item == "*" or hasattr(real, item):
                continue
            sub = f"{package}.{item}"
            if is_denied_module(sub):
                continue
            try:
                real_import(sub)
            except ImportError:
                pass  # not a submodule: the from-import reports the missing name

    def _restricted_import(name, *args, **kwargs):
        if name in allowed:
            fromlist = args[2] if len(args) > 2 else kwargs.get("fromlist")
            if fromlist and name in _PASS_THROUGH_PACKAGES:
                _import_lazy_submodules(name, fromlist)
            return exec_namespace[name]
        top_module = name.split(".")[0]
        if top_module in _PASS_THROUGH_PACKAGES:
            # Refuse BEFORE importing: `from numpy.ctypeslib import
            # load_library` returns the leaf module's proxy, and the proxy
            # only refuses denied CHILDREN, not the names on a denied leaf.
            if is_denied_module(name):
                raise ImportError(f"Module '{name}' is not available in the sandbox.")
            real = real_import(name, *args, **kwargs)
            # `import a.b` binds `a`, so handing back the real package
            # here would return the UNWRAPPED module and undo the
            # cross-package guard. Return the proxy we already built
            # where there is one, and wrap first-party packages so a
            # module that does `import os` cannot re-export it.
            #
            # ONLY for the no-fromlist form. With a fromlist,
            # `__import__` returns the LEAF module and the interpreter
            # then getattrs the names off it, so substituting the top
            # package here broke every `from numpy.linalg import norm`
            # / `from mathutils.geometry import ...` with "cannot
            # import name". The leaf's own proxy is equally guarded.
            fromlist = args[2] if len(args) > 2 else kwargs.get("fromlist")
            if not fromlist and top_module in exec_namespace:
                return exec_namespace[top_module]
            return safe_module(real)
        raise ImportError(
            f"Module '{name}' is not available. "
            f"Allowed modules: {', '.join(sorted(allowed))}"
        )

    return _restricted_import
