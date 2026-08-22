# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Optimistic, staged, journaled add-on source transactions."""

import difflib
import os
import stat
import tempfile
import time
import uuid
from pathlib import Path

from .checks import run_static_checks
from .constants import MAX_DIFF_CHARS, MAX_PATCH_BYTES, MAX_PATCH_FILES
from .errors import AddonProjectError
from .indexer import build_index, read_source, sha256_bytes
from .paths import normalize_relative_path, resolve_project_path
from .storage import read_json, write_json_atomic


class TransactionStore:
    def __init__(self, storage_dir: Path):
        self.root = Path(storage_dir) / "transactions"

    def _project_dir(self, project_id: str) -> Path:
        return self.root / project_id

    def _proposal_path(self, project_id: str, proposal_id: str) -> Path:
        return self._project_dir(project_id) / "proposals" / f"{proposal_id}.json"

    def _history_path(self, project_id: str, transaction_id: str) -> Path:
        return self._project_dir(project_id) / "history" / f"{transaction_id}.json"

    def stage(self, project_id: str, root: Path, params: dict) -> dict:
        changes = params.get("changes")
        if not isinstance(changes, list) or not changes:
            raise AddonProjectError("invalid_patch", "A non-empty changes list is required")
        if len(changes) > MAX_PATCH_FILES:
            raise AddonProjectError("patch_too_large", f"At most {MAX_PATCH_FILES} files may change at once")
        _, current_revision = build_index(root)
        expected_revision = params.get("expected_revision")
        if expected_revision != current_revision:
            raise AddonProjectError("revision_conflict", "The project changed; inspect the latest revision before staging")

        normalized = []
        previews = []
        total_bytes = 0
        seen = set()
        for change in changes:
            if not isinstance(change, dict):
                raise AddonProjectError("invalid_patch", "Each change must be an object")
            relative = normalize_relative_path(change.get("path", ""))
            if relative in seen:
                raise AddonProjectError("invalid_patch", f"Duplicate change path: {relative}")
            seen.add(relative)
            path = resolve_project_path(root, relative)
            operation = change.get("operation", "write")
            if operation not in ("write", "delete"):
                raise AddonProjectError("invalid_patch", f"Unsupported operation for {relative}")
            old_text = ""
            old_hash = None
            if path.exists():
                if not path.is_file():
                    raise AddonProjectError("invalid_path", f"Not a file: {relative}")
                old_text, old_hash = read_source(path, limit=1_000_000)
            expected_hash = change.get("expected_sha256")
            if expected_hash != old_hash:
                raise AddonProjectError("file_conflict", f"File changed since inspection: {relative}")
            if operation == "delete":
                if old_hash is None:
                    raise AddonProjectError("file_not_found", f"Cannot delete missing file: {relative}")
                new_text = None
            else:
                new_text = change.get("content")
                if not isinstance(new_text, str):
                    raise AddonProjectError("invalid_patch", f"Write content must be text: {relative}")
                encoded = new_text.encode("utf-8")
                total_bytes += len(encoded)
                if total_bytes > MAX_PATCH_BYTES:
                    raise AddonProjectError("patch_too_large", "Combined patch content is too large")
                if path.suffix.lower() in (".py", ".pyi"):
                    try:
                        compile(new_text, relative, "exec")
                    except SyntaxError as exc:
                        raise AddonProjectError("syntax_error", f"{relative}:{exc.lineno}: {exc.msg}")
            diff = "".join(difflib.unified_diff(
                old_text.splitlines(keepends=True),
                (new_text or "").splitlines(keepends=True),
                fromfile=f"a/{relative}", tofile=f"b/{relative}", n=3,
            ))[:MAX_DIFF_CHARS]
            previews.append({
                "path": relative,
                "operation": operation,
                "diff": diff,
                "old_sha256": old_hash,
                "new_sha256": sha256_bytes(new_text.encode("utf-8")) if new_text is not None else None,
            })
            normalized.append({
                "path": relative,
                "operation": operation,
                "expected_sha256": old_hash,
                "content": new_text,
            })
        proposal_id = str(uuid.uuid4())
        write_json_atomic(self._proposal_path(project_id, proposal_id), {
            "proposal_id": proposal_id,
            "project_id": project_id,
            "base_revision": current_revision,
            "created_at": time.time(),
            "changes": normalized,
        })
        return {"success": True, "proposal_id": proposal_id, "base_revision": current_revision, "changes": previews}

    def proposal_changes(self, project_id: str, proposal_id: str) -> list:
        """Normalized changes of a staged proposal ([] when unavailable)."""
        proposal = read_json(self._proposal_path(project_id, proposal_id), None)
        if isinstance(proposal, dict) and proposal.get("project_id") == project_id:
            changes = proposal.get("changes")
            if isinstance(changes, list):
                return changes
        return []

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def commit(self, project_id: str, root: Path, proposal_id: str) -> dict:
        proposal = read_json(self._proposal_path(project_id, proposal_id), None)
        if not isinstance(proposal, dict) or proposal.get("project_id") != project_id:
            raise AddonProjectError("proposal_not_found", "The staged proposal is unavailable")
        _, current_revision = build_index(root)
        if current_revision != proposal.get("base_revision"):
            raise AddonProjectError("revision_conflict", "The project changed after staging; no files were written")
        backups = []
        written = []
        for change in proposal["changes"]:
            path = resolve_project_path(root, change["path"])
            old_text, old_hash = (
                read_source(path, limit=1_000_000)
                if path.exists() else (None, None)
            )
            if old_hash != change.get("expected_sha256"):
                raise AddonProjectError(
                    "file_conflict",
                    f"File changed after staging: {change['path']}",
                )
            backups.append({
                "path": change["path"],
                "content": old_text,
                "before_sha256": old_hash,
                "expected_after_sha256": (
                    sha256_bytes(change["content"].encode("utf-8"))
                    if change["content"] is not None else None
                ),
            })

        transaction_id = str(uuid.uuid4())
        history_path = self._history_path(project_id, transaction_id)
        journal = {
            "transaction_id": transaction_id,
            "project_id": project_id,
            "proposal_id": proposal_id,
            "base_revision": proposal["base_revision"],
            "revision": None,
            "created_at": time.time(),
            "status": "pending",
            "files": backups,
        }
        # The recovery journal must be durable before the first project file
        # changes. If Blender exits mid-commit, the next project operation can
        # conservatively restore every file to its pre-commit content.
        write_json_atomic(history_path, journal)
        try:
            for change, backup in zip(proposal["changes"], backups):
                path = resolve_project_path(root, change["path"])
                current_hash = (
                    read_source(path, limit=1_000_000)[1]
                    if path.exists() else None
                )
                if current_hash != backup["before_sha256"]:
                    raise AddonProjectError("file_conflict", f"File changed after staging: {change['path']}")
                if change["operation"] == "delete":
                    path.unlink()
                else:
                    self._atomic_write(path, change["content"])
                written.append(backup)
            checks = run_static_checks(root)
            if not checks["success"]:
                raise AddonProjectError("checks_failed", checks["summary"])
            _, revision = build_index(root)
            journal["revision"] = revision
            journal["status"] = "committed"
            write_json_atomic(history_path, journal)
        except Exception:
            for backup in reversed(written):
                path = resolve_project_path(root, backup["path"])
                if backup["content"] is None:
                    if path.exists():
                        path.unlink()
                else:
                    self._atomic_write(path, backup["content"])
            try:
                history_path.unlink()
            except OSError:
                pass
            raise
        try:
            self._proposal_path(project_id, proposal_id).unlink()
        except OSError:
            pass
        return {"success": True, "transaction_id": transaction_id, "revision": revision, "checks": checks}

    def history(self, project_id: str, limit=20) -> list[dict]:
        history_dir = self._project_dir(project_id) / "history"
        records = []
        for path in history_dir.glob("*.json") if history_dir.exists() else ():
            record = read_json(path, None)
            if isinstance(record, dict) and record.get("status", "committed") == "committed":
                records.append({
                    "transaction_id": record.get("transaction_id"),
                    "revision": record.get("revision"),
                    "created_at": record.get("created_at"),
                    "files": [item.get("path") for item in record.get("files", [])],
                })
        records.sort(key=lambda item: item.get("created_at") or 0, reverse=True)
        return records[:min(max(1, int(limit)), 100)]

    def rollback(self, project_id: str, root: Path, transaction_id: str, expected_revision: str) -> dict:
        history_path = self._history_path(project_id, transaction_id)
        record = read_json(history_path, None)
        if (
            not isinstance(record, dict)
            or record.get("project_id") != project_id
            or record.get("status", "committed") != "committed"
        ):
            raise AddonProjectError("transaction_not_found", "The transaction is unavailable")
        _, current_revision = build_index(root)
        if current_revision != expected_revision or current_revision != record.get("revision"):
            raise AddonProjectError("revision_conflict", "Rollback refused because the project changed")
        for file_record in record.get("files", []):
            path = resolve_project_path(root, file_record["path"])
            current_hash = read_source(path, limit=1_000_000)[1] if path.exists() else None
            if current_hash != file_record.get("expected_after_sha256"):
                raise AddonProjectError("file_conflict", f"Rollback refused for changed file: {file_record['path']}")

        # Persist the recovery direction before touching the first source file.
        # A crash can leave a mix of before/after hashes; recover_pending then
        # completes the approved rollback without overwriting later user edits.
        record["status"] = "rollback_pending"
        record["rollback_started_at"] = time.time()
        write_json_atomic(history_path, record)
        self._restore_before(root, record.get("files", []))
        _, revision = build_index(root)
        checks = run_static_checks(root)
        record["status"] = "rolled_back"
        record["rolled_back_at"] = time.time()
        record["rolled_back_revision"] = revision
        write_json_atomic(history_path, record)
        return {
            "success": True,
            "rolled_back": transaction_id,
            "revision": revision,
            "checks": checks,
        }

    def _restore_before(self, root: Path, files: list[dict]) -> None:
        for file_record in reversed(files):
            path = resolve_project_path(root, file_record["path"])
            if file_record.get("content") is None:
                if path.exists():
                    path.unlink()
            else:
                self._atomic_write(path, file_record["content"])

    @staticmethod
    def _validate_recovery_hashes(root: Path, files: list[dict]) -> None:
        for file_record in files:
            path = resolve_project_path(root, file_record["path"])
            current_hash = (
                read_source(path, limit=1_000_000)[1]
                if path.exists() else None
            )
            allowed = {
                file_record.get("before_sha256"),
                file_record.get("expected_after_sha256"),
            }
            if current_hash not in allowed:
                raise AddonProjectError(
                    "recovery_conflict",
                    f"Interrupted transaction recovery refused for changed file: {file_record['path']}",
                )

    def recover_pending(self, project_id: str, root: Path) -> None:
        """Restore a commit interrupted after its write-ahead journal landed."""
        history_dir = self._project_dir(project_id) / "history"
        for journal_path in sorted(history_dir.glob("*.json")) if history_dir.exists() else ():
            record = read_json(journal_path, None)
            if not isinstance(record, dict) or record.get("status") not in {
                "pending", "rollback_pending",
            }:
                continue
            files = record.get("files") or []
            self._validate_recovery_hashes(root, files)
            self._restore_before(root, files)
            if record.get("status") == "pending":
                journal_path.unlink()
                continue
            _, revision = build_index(root)
            record["status"] = "rolled_back"
            record["rolled_back_at"] = time.time()
            record["rolled_back_revision"] = revision
            write_json_atomic(journal_path, record)
