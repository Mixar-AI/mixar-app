# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Atomic JSON file writes shared by client modules.

The payload goes to a temp file in the destination's own directory (so the
rename never crosses a volume), is flushed and fsynced, then ``os.replace``
swaps it in: readers see the old file or the new one, never a half-written
one. ``os.replace`` overwrites an existing file on Windows too (MoveFileEx
with REPLACE_EXISTING); a destination another process holds open there
raises ``PermissionError``, which reaches the caller. On any failure the
temp file is removed and the error re-raised.
"""

import json
import os
import tempfile
from pathlib import Path


def write_json_atomic(path: Path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
