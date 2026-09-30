# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Minimal gettext PO reader/writer.

No ``bpy`` import: the runtime loads the active catalog with it and the
``scripts/i18n`` tooling reads and rewrites every catalog with it. Only what
Mixar's catalogs use is supported — ``msgctxt``, ``msgid``, ``msgstr``,
comments and flags. Plural forms are read (``msgstr[0]`` wins) but never
written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "a": "\a", "b": "\b",
            "f": "\f", "v": "\v"}


@dataclass
class PoEntry:
    msgid: str
    msgstr: str = ""
    msgctxt: str | None = None
    flags: set[str] = field(default_factory=set)
    comments: list[str] = field(default_factory=list)      # "# " translator
    extracted: list[str] = field(default_factory=list)     # "#." extracted
    references: list[str] = field(default_factory=list)    # "#:" source refs
    obsolete: bool = False

    @property
    def key(self) -> tuple[str | None, str]:
        return (self.msgctxt, self.msgid)

    @property
    def is_header(self) -> bool:
        return self.msgid == "" and self.msgctxt is None

    @property
    def fuzzy(self) -> bool:
        return "fuzzy" in self.flags


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) < 2 or text[0] != '"' or text[-1] != '"':
        raise ValueError(f"expected a quoted PO string, got {text!r}")
    body = text[1:-1]
    if "\\" not in body:
        return body
    out = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == "\\" and i + 1 < n:
            nxt = body[i + 1]
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _quote(text: str) -> str:
    return '"' + (text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t")
                  .replace("\r", "\\r").replace("\n", "\\n")) + '"'


def parse_po(text: str) -> list[PoEntry]:
    """Parse PO source text into entries (header included, obsolete kept)."""
    entries: list[PoEntry] = []
    cur: PoEntry | None = None
    field_name: str | None = None
    parts: dict[str, list[str]] = {}

    def flush():
        nonlocal cur, parts, field_name
        if cur is not None and "msgid" in parts:
            cur.msgid = "".join(parts["msgid"])
            cur.msgctxt = "".join(parts["msgctxt"]) if "msgctxt" in parts else None
            if "msgstr" in parts:
                cur.msgstr = "".join(parts["msgstr"])
            elif "msgstr[0]" in parts:
                cur.msgstr = "".join(parts["msgstr[0]"])
            entries.append(cur)
        cur = None
        parts = {}
        field_name = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        obsolete = False
        if line.startswith("#~"):
            obsolete = True
            line = line[2:].strip()
            if not line:
                continue
        if line.startswith("#"):
            if cur is not None and "msgid" in parts:
                flush()
            if cur is None:
                cur = PoEntry(msgid="")
            if line.startswith("#,"):
                cur.flags.update(f.strip() for f in line[2:].split(",") if f.strip())
            elif line.startswith("#."):
                cur.extracted.append(line[2:].strip())
            elif line.startswith("#:"):
                cur.references.extend(line[2:].split())
            elif line.startswith("#|"):
                pass  # previous msgid, not kept
            else:
                cur.comments.append(line[1:].strip())
            continue
        if line.startswith('"'):
            if field_name is None:
                raise ValueError(f"continuation line without a field: {raw!r}")
            parts[field_name].append(_unquote(line))
            continue
        keyword, _, rest = line.partition(" ")
        if keyword in ("msgctxt", "msgid") and cur is not None and "msgid" in parts:
            flush()
        if cur is None:
            cur = PoEntry(msgid="")
        if obsolete:
            cur.obsolete = True
        field_name = keyword
        parts[field_name] = [_unquote(rest)]
    flush()
    return entries


def read_po(path: str | Path) -> list[PoEntry]:
    return parse_po(Path(path).read_text(encoding="utf-8"))


def load_messages(path: str | Path) -> dict[tuple[str | None, str], str]:
    """Usable translations of a catalog: ``{(msgctxt, msgid): msgstr}``.

    Skips the header, untranslated, fuzzy and obsolete entries. This is the
    runtime's hot path (one catalog at startup and per language switch), so it
    avoids building ``PoEntry`` objects.
    """
    out: dict[tuple[str | None, str], str] = {}
    ctxt: list[str] | None = None
    msgid: list[str] | None = None
    msgstr: list[str] | None = None
    target: list[str] | None = None
    skip = False

    def flush():
        nonlocal ctxt, msgid, msgstr, target, skip
        if msgid is not None and msgstr is not None and not skip:
            mid = "".join(msgid)
            mstr = "".join(msgstr)
            if mid and mstr:
                out[("".join(ctxt) if ctxt is not None else None, mid)] = mstr
        ctxt = msgid = msgstr = target = None
        skip = False

    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                flush()
                continue
            first = line[0]
            if first == '"':
                if target is not None:
                    target.append(_unquote(line))
                continue
            if first == "#":
                if msgstr is not None:
                    flush()
                if line.startswith("#~"):
                    skip = True
                elif line.startswith("#,") and "fuzzy" in line:
                    skip = True
                continue
            if line.startswith("msgctxt "):
                if msgstr is not None:
                    flush()
                ctxt = target = [_unquote(line[8:])]
            elif line.startswith("msgid "):
                if msgstr is not None:
                    flush()
                msgid = target = [_unquote(line[6:])]
            elif line.startswith("msgid_plural "):
                target = None
            elif line.startswith("msgstr "):
                msgstr = target = [_unquote(line[7:])]
            elif line.startswith("msgstr[0] "):
                msgstr = target = [_unquote(line[10:])]
            elif line.startswith("msgstr["):
                target = None
    flush()
    return out


def _write_field(lines: list[str], prefix: str, name: str, value: str) -> None:
    if "\n" in value[:-1]:
        lines.append(f'{prefix}{name} ""')
        chunks = value.split("\n")
        for i, chunk in enumerate(chunks):
            piece = chunk + ("\n" if i < len(chunks) - 1 else "")
            if piece:
                lines.append(prefix + _quote(piece))
    else:
        lines.append(f"{prefix}{name} {_quote(value)}")


def format_entry(entry: PoEntry) -> str:
    lines: list[str] = []
    prefix = "#~ " if entry.obsolete else ""
    lines.extend(f"# {c}".rstrip() for c in entry.comments)
    lines.extend(f"#. {c}" for c in entry.extracted)
    for ref in entry.references:
        lines.append(f"#: {ref}")
    if entry.flags:
        lines.append("#, " + ", ".join(sorted(entry.flags)))
    if entry.msgctxt is not None:
        _write_field(lines, prefix, "msgctxt", entry.msgctxt)
    _write_field(lines, prefix, "msgid", entry.msgid)
    _write_field(lines, prefix, "msgstr", entry.msgstr)
    return "\n".join(lines)


def format_po(entries: Iterable[PoEntry]) -> str:
    return "\n\n".join(format_entry(e) for e in entries) + "\n"


def write_po(path: str | Path, entries: Iterable[PoEntry]) -> None:
    Path(path).write_text(format_po(entries), encoding="utf-8", newline="\n")


def header_fields(entries: Iterable[PoEntry]) -> dict[str, str]:
    for entry in entries:
        if entry.is_header:
            out = {}
            for line in entry.msgstr.split("\n"):
                key, sep, value = line.partition(":")
                if sep:
                    out[key.strip()] = value.strip()
            return out
    return {}
