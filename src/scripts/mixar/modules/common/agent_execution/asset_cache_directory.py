# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Private storage for downloaded agent assets; no bpy.

Only a background downloader creates the directory. Python 3.13+ also applies
a user/admin-only ACL for mkdtemp's 0700 directory on Windows. We never adopt
an existing directory, including the old shared ``mixar_agent_assets`` cache.
Completed files remain after exit: saved projects may reference these paths.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import tempfile
import uuid

_DIR_FD = os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY")


def _identity(info):
    return info.st_dev, info.st_ino


def _redirected(info):
    return (stat.S_ISLNK(info.st_mode) or
            bool(getattr(info, "st_file_attributes", 0) &
                 getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _private(info):
    # Windows security comes from creating our own directory with a private
    # ACL, not from st_mode (which does not describe Windows ACL permissions).
    return (os.name == "nt" or
            (info.st_uid == os.geteuid() and not info.st_mode & 0o077))


class CacheDirectory:
    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="mixar_agent_assets-"))
        self.identity = _identity(self.path.lstat())
        self.verify()

    def verify(self):
        info = self.path.lstat()
        if (_redirected(info) or not stat.S_ISDIR(info.st_mode) or
                _identity(info) != self.identity or not _private(info)):
            raise OSError("Asset cache directory is unsafe or was replaced")

    @contextmanager
    def open(self):
        self.verify()
        fd = None
        try:
            if _DIR_FD:
                fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY |
                             getattr(os, "O_NOFOLLOW", 0))
                if _identity(os.fstat(fd)) != self.identity:
                    raise OSError("Asset cache directory was replaced")
            self.verify()
            yield _DirectoryAccess(self, fd)
        finally:
            if fd is not None:
                os.close(fd)


class _DirectoryAccess:
    def __init__(self, directory, fd):
        self.directory, self.fd = directory, fd

    def _target(self, name):
        return name if self.fd is not None else self.directory.path / name

    def _stat(self, name):
        return os.stat(self._target(name), dir_fd=self.fd, follow_symlinks=False)

    def hit(self, name):
        """Bounded metadata checks only: never read an asset or wait for it."""
        fd = None
        try:
            info = self._stat(name)
            if (_redirected(info) or not stat.S_ISREG(info.st_mode) or
                    info.st_size <= 0 or info.st_nlink != 1 or not _private(info)):
                return None
            # O_NONBLOCK also prevents a raced-in FIFO from blocking the UI.
            # Windows rejects reparse points above and verifies identity below;
            # its private ACL excludes another user's directory mutations.
            fd = os.open(self._target(name), os.O_RDONLY |
                         getattr(os, "O_NOFOLLOW", 0) |
                         getattr(os, "O_NONBLOCK", 0) |
                         getattr(os, "O_BINARY", 0), dir_fd=self.fd)
            opened = os.fstat(fd)
            if (_identity(opened) != _identity(info) or
                    not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or
                    opened.st_size <= 0 or not _private(opened) or
                    _identity(self._stat(name)) != _identity(opened)):
                return None
            self.directory.verify()
            return str(self.directory.path / name)
        except OSError:
            return None
        finally:
            if fd is not None:
                os.close(fd)

    def partial(self):
        self.directory.verify()
        for _ in range(8):
            name = uuid.uuid4().hex + ".part"
            try:
                fd = os.open(self._target(name), os.O_WRONLY | os.O_CREAT |
                             os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) |
                             getattr(os, "O_BINARY", 0), 0o600, dir_fd=self.fd)
                return name, fd
            except FileExistsError:
                continue
        raise OSError("Could not create an asset cache temporary file")

    def publish(self, partial, name):
        self.directory.verify()
        os.replace(self._target(partial), self._target(name),
                   src_dir_fd=self.fd, dst_dir_fd=self.fd)

    def discard(self, name):
        if self.fd is None:
            self.directory.verify()
        try:
            os.unlink(self._target(name), dir_fd=self.fd)
        except FileNotFoundError:
            pass
