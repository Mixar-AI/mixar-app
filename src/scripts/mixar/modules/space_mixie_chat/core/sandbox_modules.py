# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Restricted module wrappers for sandboxed script execution.

These classes provide restricted versions of standard library modules
that are injected into the script execution namespace. Each wrapper
only exposes a safe subset of the original module's API, with
dangerous operations either blocked or restricted to the temp directory.

Blocked capabilities:
- os / pathlib: NOT exposed at all -- the real modules grant os.system,
  os.environ, Path.write_text, etc. (a full sandbox escape). A script that
  imports them is rejected by the restricted __import__ in executor.py.
- tempfile: NamedTemporaryFile, mkdtemp, and all creation functions
- base64: only b64encode and b64decode are allowed
- string: everything except Formatter -- string.Formatter().get_field()
  resolves "0.__class__.__base__.__subclasses__" against the REAL getattr and
  hands back the object, walking straight past the dunder guard
- open(): write mode restricted to temp directory only
"""

import builtins
import types


# ---------------------------------------------------------------------------
# Cross-package module leaks
# ---------------------------------------------------------------------------
#
# Denying `import os` is not enough: an *allowed* module can bind another
# module as an ordinary attribute, and a plain attribute name never trips the
# AST dunder guard. These all reached the real `os` with no dunder access at
# all, and the last one reaches `builtins.exec`:
#
#     random._os.system(...)                      # _os IS the os module
#     fractions.sys.modules['os']
#     statistics.sys.modules['os']
#     datetime.sys.modules['os']
#     collections._sys.modules['os']
#     re.enum.sys.modules['os']
#     fractions.sys.modules['builtins'].exec(...)
#
# Rather than denylisting those names (the next stdlib release adds more), a
# module attribute is allowed only when it belongs to the SAME top-level
# package as the module the script was handed. So `collections.abc`,
# `numpy.linalg` and `mixar.modules.paint.*` keep working, while anything that
# crosses a package boundary -- `os`, `sys`, `ctypes`, `builtins`, `codecs` --
# is refused at the first hop.
#
# The wrapped module is held in a closure, not on the instance: the proxy has
# `__slots__ = ()` so there is no attribute to read it back out of, and the
# closure itself is only reachable through `__closure__`/`__globals__`, which
# the AST validator blocks.

# Harmless, purely informational module dunders. Everything else -- including
# __dict__, __loader__, __spec__, __builtins__ and the path-leaking __file__ --
# is refused by the proxy.
_MODULE_INFO_DUNDERS = frozenset({"__name__", "__doc__", "__version__", "__all__"})

# Same-package children that are NOT safe, because they exist to reach outside
# Python. The cross-package rule below cannot see these: `numpy.ctypeslib` is
# genuinely part of numpy, but `numpy.ctypeslib.load_library(...)` RETURNS a
# live `ctypes.CDLL` -- a plain function return, no module hop and no dunder,
# so neither the module guard nor the AST guard sees it. Verified: it loads
# libc and calls into it from inside the sandbox.
_DENIED_SUBMODULES = frozenset({
    "numpy.ctypeslib",   # -> ctypes.CDLL
    "numpy.f2py",        # compiles and loads native extensions
    "numpy.distutils",   # build machinery: compilers, subprocesses
    "numpy.testing",     # pytest bootstrapping
})

# Same-package ATTRIBUTES that are not safe for the same reason -- they run
# Python from disk. `bpy.utils` is the live case: it is the module every agent
# script already reaches through, and these turn it into an arbitrary-code
# loader without leaving the `bpy` package.
_DENIED_ATTRS = {
    "bpy.utils": frozenset({
        "execfile",
        "load_scripts",
        "load_scripts_extensions",
        "modules_from_path",
        "register_submodule_factory",
    }),
}

_SAFE_MODULE_CACHE: dict = {}


def safe_module(module, root: str = None):
    """Wrap ``module`` so it cannot hand out modules from other packages."""
    # A stand-in module (the test suite's mocked `bpy`/`mathutils`) may not
    # carry __name__. Fall back to an empty root, which allows no module
    # attribute at all -- the safe direction.
    name = getattr(module, "__name__", "") or ""
    if not isinstance(name, str):
        name = ""
    root = root or name.partition(".")[0]
    key = (id(module), root)
    cached = _SAFE_MODULE_CACHE.get(key)
    if cached is not None:
        return cached

    prefix = (root + ".") if root else "\0"

    class _SandboxedModule:
        __slots__ = ()

        def __getattr__(self, attr):
            # `__slots__ = ()` means there is no instance dict, so a dunder
            # falls through to here and would forward to the module's own --
            # `json.__dict__['codecs']` walks straight back out, and
            # `__file__` leaks a local filesystem path. The AST guard already
            # blocks the escape dunders in scripts; refuse them here too so
            # the proxy is safe on its own, keeping only the informational
            # ones scripts legitimately read.
            if (
                attr.startswith("__")
                and attr.endswith("__")
                and attr not in _MODULE_INFO_DUNDERS
            ):
                raise AttributeError(
                    f"{name}.{attr} is not available in the sandbox."
                )
            if attr in _DENIED_ATTRS.get(name, ()):
                raise AttributeError(
                    f"{name}.{attr} is not available in the sandbox: it runs "
                    f"Python from outside the script."
                )
            # Refuse by NAME, before the fetch. A denied child should never be
            # imported at all, and several of these are lazy attributes whose
            # import has side effects (numpy resolves numpy.ctypeslib through
            # a module-level __getattr__).
            if f"{name}.{attr}" in _DENIED_SUBMODULES:
                raise AttributeError(
                    f"{name}.{attr} is not available in the sandbox: it "
                    f"bridges out of Python."
                )
            value = getattr(module, attr)
            if isinstance(value, types.ModuleType):
                child = getattr(value, "__name__", "")
                if child in _DENIED_SUBMODULES:
                    # An alias under another attribute name.
                    raise AttributeError(
                        f"{name}.{attr} is not available in the sandbox: "
                        f"'{child}' bridges out of Python."
                    )
                if child == root or child.startswith(prefix):
                    return safe_module(value, root)
                raise AttributeError(
                    f"{name}.{attr} is not available in the sandbox: it is the "
                    f"'{child}' module, outside the '{root}' package."
                )
            return value

        def __dir__(self):
            return [
                a for a in dir(module)
                if not isinstance(getattr(module, a, None), types.ModuleType)
            ]

        def __repr__(self):
            return f"<sandboxed module {name!r}>"

    proxy = _SandboxedModule()
    _SAFE_MODULE_CACHE[key] = proxy
    return proxy


class RestrictedTempfile:
    """Restricted tempfile exposing only gettempdir()."""

    def __init__(self):
        import tempfile as _tf
        self._gettempdir = _tf.gettempdir

    def gettempdir(self) -> str:
        return self._gettempdir()

    def __getattr__(self, name):
        raise AttributeError(
            f"tempfile.{name} is not available in the sandbox. "
            f"Allowed: gettempdir"
        )


class RestrictedBase64:
    """Restricted base64 exposing only encode/decode."""

    def __init__(self):
        import base64 as _b64
        self.b64encode = _b64.b64encode
        self.b64decode = _b64.b64decode

    def __getattr__(self, name):
        raise AttributeError(
            f"base64.{name} is not available in the sandbox. "
            f"Allowed: b64encode, b64decode"
        )


class RestrictedString:
    """Restricted string module: constants + Template, but no Formatter.

    string.Formatter().get_field("0.__class__.__base__.__subclasses__", [x], {})
    performs the attribute walk in C with the real getattr and returns the
    OBJECT, not a rendered string -- a complete bypass of the sandbox's dunder
    guard. Nothing else in the module resolves attributes by name.
    """

    _ALLOWED = (
        "Template", "capwords", "ascii_letters", "ascii_lowercase",
        "ascii_uppercase", "digits", "hexdigits", "octdigits", "printable",
        "punctuation", "whitespace",
    )

    def __init__(self):
        import string as _string
        for _name in self._ALLOWED:
            setattr(self, _name, getattr(_string, _name))

    def __getattr__(self, name):
        raise AttributeError(
            f"string.{name} is not available in the sandbox. "
            f"Allowed: {', '.join(self._ALLOWED)}"
        )


def restricted_open(path, mode='r', *args, **kwargs):
    """Restricted open(): read-only by default, writes limited to temp directory."""
    import os.path as _osp
    import tempfile as _tf

    mode_str = str(mode)
    is_write = any(c in mode_str for c in ('w', 'a', 'x', '+'))

    if is_write:
        real = _osp.realpath(str(path))
        # realpath the prefix too: on macOS /var is a symlink to /private/var, so a
        # realpath'd target never starts with the un-normalized gettempdir() -> blocked.
        temp_prefix = _osp.realpath(_tf.gettempdir())
        if not real.startswith(temp_prefix):
            raise PermissionError(
                f"open() with write mode is restricted to temp directory. "
                f"Cannot write to: {path}"
            )

    return builtins.open(path, mode, *args, **kwargs)


def _close_quietly(resp):
    try:
        resp.close()
    except Exception:
        pass


class _UrlResponse:
    """read()-only wrapper over an HTTP response.

    The raw response is captured in closures — NO instance attribute references it (so
    ``response._resp`` etc. don't exist), and ``read`` is a plain function (no
    ``__self__``/``__func__``). Combined with the AST validator blocking
    ``__closure__``/``__self__``/``__func__``, a sandboxed script cannot reach the
    underlying response (its ``headers`` / ``status`` / ``fp`` / socket). Any attribute
    other than ``read`` falls through to ``__getattr__`` and is denied.
    """

    def __init__(self, resp):
        self.read = lambda *a, **k: resp.read(*a, **k)
        self.__close = lambda: _close_quietly(resp)  # name-mangled -> _UrlResponse__close

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.__close()
        return False

    def __getattr__(self, name):
        raise PermissionError("urllib response: only read() is available in the sandbox")


def _allowed_asset_hosts():
    """Hosts a sandboxed script may GET from (asset CDNs only). Env-overridable."""
    import os
    raw = os.environ.get("MIXAR_ASSET_HOSTS", "amazonaws.com,cloudflarestorage.com")
    return tuple(h.strip().lower() for h in raw.split(",") if h.strip())


class RestrictedUrllib:
    """Restricted urllib: ONLY `urlopen(url)` GET to allowlisted asset hosts.

    This is the only network egress available to sandboxed scripts (including the
    agent's execute_bpy_script escape hatch), so the host allowlist is the security
    boundary — keep it to asset CDNs (S3 / R2). Returns a read()-only response.
    """

    def __init__(self):
        import urllib.request as _req
        from urllib.parse import urlparse as _parse
        self._urlopen = _req.urlopen
        self._parse = _parse
        self._allowed = _allowed_asset_hosts()

    def _check_url(self, url):
        """Shared transport + host gate for urlopen and prefetch."""
        parsed = self._parse(str(url))
        # Restrict the TRANSPORT first: urllib's default opener includes FileHandler, so
        # a file:// URL whose hostname satisfies the allowlist (file://amazonaws.com/etc/
        # passwd) would otherwise read local files. Only http/https are network egress.
        if parsed.scheme not in ("http", "https"):
            raise PermissionError(
                f"urllib.urlopen: scheme '{parsed.scheme}' is not allowed (http/https only)"
            )
        host = (parsed.hostname or "").lower()
        if not any(host == h or host.endswith("." + h) for h in self._allowed):
            raise PermissionError(
                f"urllib.urlopen: host '{host}' is not allowed (asset hosts only: "
                f"{', '.join(self._allowed)})"
            )

    def urlopen(self, url, timeout=120):
        self._check_url(url)
        return _UrlResponse(self._urlopen(str(url), timeout=timeout))

    def prefetch(self, urls, timeout=120):
        """Concurrently GET a batch of allowlisted URLs into temp files.

        Returns {url: local_path or None}. Bulk companion to urlopen: agent
        scripts run on Blender's main thread, and downloading a texture/asset
        set one-by-one froze the app past the backend tool timeout (the
        terrain Patina apply pulls ~12 maps). The same scheme/host gate
        applies per URL; a disallowed or failed URL maps to None instead of
        raising, so one bad entry never voids the batch. Worker threads and
        the real open() live HERE, outside the sandbox namespace — the script
        only ever receives file paths in the temp directory.
        """
        import concurrent.futures as _futures
        import hashlib as _hashlib
        import tempfile as _tf

        out = {}
        allowed = []
        seen = set()
        for url in list(urls or [])[:32]:
            u = str(url)
            if u in seen:
                continue
            seen.add(u)
            try:
                self._check_url(u)
                allowed.append(u)
            except Exception:
                out[u] = None

        tmp = _tf.gettempdir().rstrip("/\\")

        def _fetch(u):
            try:
                data = self._urlopen(u, timeout=timeout).read()
                if not data:
                    return u, None
                name = "mixar_prefetch_" + _hashlib.sha1(u.encode()).hexdigest()[:16] + ".bin"
                path = tmp + "/" + name
                with open(path, "wb") as fh:
                    fh.write(data)
                return u, path
            except Exception:
                return u, None

        if allowed:
            workers = min(6, len(allowed))
            with _futures.ThreadPoolExecutor(max_workers=workers) as pool:
                for u, path in pool.map(_fetch, allowed):
                    out[u] = path
        return out

    def __getattr__(self, name):
        raise AttributeError(
            "urllib." + name + " is not available in the sandbox. "
            "Allowed: urlopen(url) GET and prefetch(urls) to asset hosts only"
        )


# Singleton instances (created once at module load)
RESTRICTED_TEMPFILE = RestrictedTempfile()
RESTRICTED_BASE64 = RestrictedBase64()
RESTRICTED_STRING = RestrictedString()
RESTRICTED_URLLIB = RestrictedUrllib()
