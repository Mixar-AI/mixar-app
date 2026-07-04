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
- os: environ, exec*, popen, chmod, chown, and all other unsafe functions
- tempfile: NamedTemporaryFile, mkdtemp, and all creation functions
- base64: only b64encode and b64decode are allowed
- open(): write mode restricted to temp directory only
"""

import builtins


class _RestrictedOsPath:
    """Restricted os.path exposing only safe path inspection functions."""

    def __init__(self):
        import os.path as _osp
        self.join = _osp.join
        self.exists = _osp.exists
        self.basename = _osp.basename
        self.dirname = _osp.dirname
        self.splitext = _osp.splitext
        self.isfile = _osp.isfile
        self.isdir = _osp.isdir

    def __getattr__(self, name):
        raise AttributeError(
            f"os.path.{name} is not available in the sandbox. "
            f"Allowed: join, exists, basename, dirname, splitext, isfile, isdir"
        )


class RestrictedOs:
    """Restricted os module: only safe path ops and temp-file removal."""

    def __init__(self):
        import os as _os
        import os.path as _osp
        import tempfile as _tf
        self.path = _RestrictedOsPath()
        self._real_remove = _os.remove
        # realpath so the prefix matches realpath'd targets (on macOS /var is a symlink
        # to /private/var, so an un-normalized prefix never matches and every temp op fails)
        self._temp_prefix = _osp.realpath(_tf.gettempdir())

    def remove(self, path: str) -> None:
        """Only allow removing files inside the system temp directory."""
        import os.path as _osp
        real = _osp.realpath(str(path))
        if not real.startswith(self._temp_prefix):
            raise PermissionError(
                f"os.remove() is restricted to temp directory. "
                f"Cannot remove: {path}"
            )
        self._real_remove(real)

    def __getattr__(self, name):
        raise AttributeError(
            f"os.{name} is not available in the sandbox. "
            f"Allowed: os.path.*, os.remove (temp dir only)"
        )


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

    def urlopen(self, url, timeout=120):
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
        return _UrlResponse(self._urlopen(str(url), timeout=timeout))

    def __getattr__(self, name):
        raise AttributeError(
            "urllib." + name + " is not available in the sandbox. "
            "Allowed: urlopen(url) GET to asset hosts only"
        )


# Singleton instances (created once at module load)
RESTRICTED_OS = RestrictedOs()
RESTRICTED_TEMPFILE = RestrictedTempfile()
RESTRICTED_BASE64 = RestrictedBase64()
RESTRICTED_URLLIB = RestrictedUrllib()
