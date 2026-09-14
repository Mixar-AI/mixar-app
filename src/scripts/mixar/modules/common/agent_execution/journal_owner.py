# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""OS-held writer lifetime locks for the shared operation journal.

Each journal connection has a unique owner; OS locks survive neither close
nor process death. Recovery never infers death from another connection
opening the database, elapsed time, or a potentially reused process id.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path


def _lock(file) -> None:
    file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


class JournalOwner:
    def __init__(self, journal_path: str):
        self.directory = Path(journal_path + ".owners")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.id = uuid.uuid4().hex
        self.path = self.directory / self.id
        self._file = self.path.open("x+b")
        try:
            # Windows byte-range locks need a byte to lock.
            self._file.write(b"\0")
            self._file.flush()
            _lock(self._file)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        # Closing the descriptor releases the OS lock on both platforms.
        self._file.close()
        _unlink(self.path)

    def abandoned(self, owner_id: str) -> bool:
        """True only when the recorded owner's lifetime lock is gone.

        Unrecognized owners and access errors remain RUNNING for explicit
        reconciliation. They are not evidence that a publisher has died.
        """
        if not isinstance(owner_id, str) or len(owner_id) != 32:
            return False
        if any(c not in "0123456789abcdef" for c in owner_id):
            return False
        path = self.directory / owner_id
        try:
            with path.open("r+b") as file:
                _lock(file)
        except FileNotFoundError:
            return True
        except OSError:
            return False
        # Owner ids are never reused; an unlocked file cannot become live again.
        _unlink(path)
        return True
