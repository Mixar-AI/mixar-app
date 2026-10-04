# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Private durable at-most-once admission. No arguments or pixels are stored."""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time

from ..constants import UIError


class Receipts:
    def __init__(self, path):
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink() or path.parent.is_symlink():
            raise UIError("receipt_unavailable", "UI receipt storage must not be a symlink")
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        self.db = sqlite3.connect(path, timeout=2, check_same_thread=False)
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('secret', ?)", (secrets.token_hex(32),))
            self.secret = self.db.execute("SELECT value FROM meta WHERE key='secret'").fetchone()[0].encode()
            self.db.execute("CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, digest TEXT, status TEXT, created REAL)")
            # Any prior accepted action belongs to a lost process; never redispatch it.
            self.db.execute("UPDATE calls SET status='outcome_unknown' WHERE status IN ('accepted', 'running')")
            self.db.commit()
        except BaseException:
            # A failed constructor is never assigned to service._receipts.
            # Close here so its partially started transaction cannot retain a
            # write lock and make all subsequent startup attempts fail too.
            self.db.close()
            raise

    def digest(self, principal, name, args):
        raw = json.dumps([principal, name, args], sort_keys=True, allow_nan=False).encode()
        return hmac.new(self.secret, raw, hashlib.sha256).hexdigest()

    def prior(self, call_id, digest):
        with self.lock:
            row = self.db.execute("SELECT digest,status FROM calls WHERE id=?", (call_id,)).fetchone()
            if not row:
                return None
            if not hmac.compare_digest(row[0], digest):
                raise UIError("call_conflict", "Call UUID already belongs to a different UI action")
            return {"call_id": call_id, "status": row[1], "replayed": True}

    def claim(self, call_id, digest):
        with self.lock, self.db:
            if self.db.execute("SELECT count(*) FROM calls").fetchone()[0] >= 100000:
                raise UIError("receipt_capacity", "UI receipt storage is full; no action executed")
            try:
                self.db.execute("INSERT INTO calls VALUES (?,?,'accepted',?)", (call_id, digest, time.time()))
            except sqlite3.IntegrityError:
                raise UIError("call_conflict", "UI action already accepted; inspect its receipt") from None

    def finish(self, call_id, status):
        with self.lock, self.db:
            self.db.execute("UPDATE calls SET status=? WHERE id=?", (status, call_id))

    def status(self, call_id):
        with self.lock:
            row = self.db.execute("SELECT status FROM calls WHERE id=?", (call_id,)).fetchone()
            return {"call_id": call_id, "status": row[0] if row else "unavailable"}

    def close(self):
        with self.lock:
            self.db.close()
