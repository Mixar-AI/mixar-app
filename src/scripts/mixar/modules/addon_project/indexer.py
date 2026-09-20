# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded source index and search for a linked add-on project."""

import ast
import hashlib
from pathlib import Path

from .constants import MAX_READ_BYTES, MAX_SEARCH_RESULTS
from .errors import AddonProjectError
from .paths import iter_project_files, resolve_project_path


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_source(path: Path, *, limit=MAX_READ_BYTES) -> tuple[str, str]:
    raw = path.read_bytes()
    if len(raw) > limit:
        raise AddonProjectError("file_too_large", "The requested file is too large to send to the agent")
    try:
        return raw.decode("utf-8"), sha256_bytes(raw)
    except UnicodeDecodeError:
        raise AddonProjectError("not_utf8", "Project source files must use UTF-8")


def _python_summary(text: str) -> dict:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {"syntax_error": f"line {exc.lineno}: {exc.msg}"}
    symbols = []
    imports = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append({"kind": node.__class__.__name__.replace("Def", "").lower(), "name": node.name, "line": node.lineno})
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level + (node.module or "")
            imports.append(prefix)
    return {"symbols": symbols[:100], "imports": imports[:100]}


def build_index(root: Path) -> tuple[list[dict], str]:
    files = []
    revision_hasher = hashlib.sha256()
    for relative, path in iter_project_files(root):
        raw = path.read_bytes()
        digest = sha256_bytes(raw)
        revision_hasher.update(relative.encode("utf-8"))
        revision_hasher.update(b"\0")
        revision_hasher.update(digest.encode("ascii"))
        record = {"path": relative, "sha256": digest, "size": len(raw)}
        if path.suffix.lower() == ".py" and len(raw) <= MAX_READ_BYTES:
            try:
                record.update(_python_summary(raw.decode("utf-8")))
            except UnicodeDecodeError:
                record["syntax_error"] = "not UTF-8"
        files.append(record)
    return files, revision_hasher.hexdigest()


def read_files(root: Path, requests: list) -> list[dict]:
    if not isinstance(requests, list) or not requests:
        raise AddonProjectError("invalid_request", "At least one file request is required")
    if len(requests) > 20:
        raise AddonProjectError("request_too_large", "At most 20 files can be read at once")
    results = []
    total = 0
    for request in requests:
        if isinstance(request, str):
            relative, start, end = request, None, None
        elif isinstance(request, dict):
            relative = request.get("path", "")
            start, end = request.get("start_line"), request.get("end_line")
        else:
            raise AddonProjectError("invalid_request", "Each file request must be a path or object")
        path = resolve_project_path(root, relative)
        if not path.is_file():
            raise AddonProjectError("file_not_found", f"Project file not found: {relative}")
        text, digest = read_source(path)
        lines = text.splitlines(keepends=True)
        if start is not None or end is not None:
            start = max(1, int(start or 1))
            end = min(len(lines), int(end or len(lines)))
            if end < start:
                raise AddonProjectError("invalid_range", f"Invalid line range for {relative}")
            text = "".join(lines[start - 1:end])
        total += len(text.encode("utf-8"))
        if total > MAX_READ_BYTES:
            raise AddonProjectError("request_too_large", "The combined file response is too large")
        results.append({"path": relative, "sha256": digest, "content": text, "start_line": start or 1})
    return results


def search_project(root: Path, query: str, *, path_glob=None, max_results=50) -> list[dict]:
    if not isinstance(query, str) or not query:
        raise AddonProjectError("invalid_query", "A non-empty search query is required")
    needle = query.casefold()
    max_results = min(max(1, int(max_results)), MAX_SEARCH_RESULTS)
    results = []
    for relative, path in iter_project_files(root):
        if path_glob and not Path(relative).match(path_glob):
            continue
        try:
            text, _ = read_source(path)
        except AddonProjectError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if needle in line.casefold():
                results.append({"path": relative, "line": line_number, "text": line[:500]})
                if len(results) >= max_results:
                    return results
    return results
