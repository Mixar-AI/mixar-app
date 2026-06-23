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
        import tempfile as _tf
        self.path = _RestrictedOsPath()
        self._real_remove = _os.remove
        self._temp_prefix = _tf.gettempdir()

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
        temp_prefix = _tf.gettempdir()
        if not real.startswith(temp_prefix):
            raise PermissionError(
                f"open() with write mode is restricted to temp directory. "
                f"Cannot write to: {path}"
            )

    return builtins.open(path, mode, *args, **kwargs)


# Singleton instances (created once at module load)
RESTRICTED_OS = RestrictedOs()
RESTRICTED_TEMPFILE = RestrictedTempfile()
RESTRICTED_BASE64 = RestrictedBase64()
