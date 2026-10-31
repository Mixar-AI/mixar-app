# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The release pipeline's crash-symbol archiver (scripts/ci/upload_crash_symbols.py).

The debug ids it files symbols under must be byte-for-byte the ids the crash
log prints (src/source/creator/mixar_crash_info.cc): lower-case hex without
separators of the Mach-O LC_UUID, the GNU build-id, or the PDB GUID + age.
"""

import importlib.util
import json
import struct
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("upload_crash_symbols", ROOT / "scripts/ci/upload_crash_symbols.py")
ucs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ucs)

UUID_BYTES = bytes(range(16))


def _macho(cputype=0x0100000C, uuid_bytes=UUID_BYTES) -> bytes:
    segment = struct.pack("<II16s", 0x19, 72, b"__TEXT") + b"\0" * 48  # LC_SEGMENT_64 (padded)
    uuid_cmd = struct.pack("<II", 0x1B, 24) + uuid_bytes
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, cputype, 0, 2, 2, len(segment) + len(uuid_cmd), 0, 0)
    return header + segment + uuid_cmd


def _elf_with_build_id(build_id: bytes) -> bytes:
    note = struct.pack("<III", 4, len(build_id), 3) + b"GNU\0" + build_id
    shoff = 64 + len(note)
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    header[0x28:0x30] = struct.pack("<Q", shoff)
    header[0x3A:0x3E] = struct.pack("<HH", 64, 2)
    null_section = b"\0" * 64
    note_section = bytearray(64)
    note_section[4:8] = struct.pack("<I", 7)  # SHT_NOTE
    note_section[0x18:0x28] = struct.pack("<QQ", 64, len(note))
    return bytes(header) + note + null_section + bytes(note_section)


def _pe_with_codeview(guid: uuid.UUID, age: int, pdb_path: bytes) -> bytes:
    data = bytearray(0x400)
    data[:2] = b"MZ"
    data[0x3C:0x40] = struct.pack("<I", 0x80)
    data[0x80:0x84] = b"PE\0\0"
    coff = 0x84
    data[coff + 2:coff + 4] = struct.pack("<H", 1)          # one section
    data[coff + 16:coff + 18] = struct.pack("<H", 240)      # PE32+ optional header size
    optional = coff + 20
    data[optional:optional + 2] = struct.pack("<H", 0x20B)
    directories = optional + 112
    data[directories + 48:directories + 56] = struct.pack("<II", 0x1000, 28)  # debug directory
    section = optional + 240
    data[section + 8:section + 24] = struct.pack("<IIII", 0x200, 0x1000, 0x200, 0x200)
    debug = 0x200
    codeview = debug + 28
    data[debug + 12:debug + 28] = struct.pack("<IIII", 2, 24 + len(pdb_path) + 1, 0x1000 + 28, codeview)
    data[codeview:codeview + 4] = b"RSDS"
    data[codeview + 4:codeview + 20] = guid.bytes_le
    data[codeview + 20:codeview + 24] = struct.pack("<I", age)
    data[codeview + 24:codeview + 24 + len(pdb_path)] = pdb_path
    return bytes(data)


def test_macho_uuid_is_plain_lower_hex():
    assert ucs.macho_uuids(_macho()) == [("arm64", UUID_BYTES.hex())]


def test_fat_macho_lists_every_slice():
    arm, intel = _macho(), _macho(cputype=0x01000007, uuid_bytes=bytes(range(16, 32)))
    header = struct.pack(">II", 0xCAFEBABE, 2)
    first = 8 + 2 * 20
    header += struct.pack(">iiIII", 0x0100000C, 0, first, len(arm), 0)
    header += struct.pack(">iiIII", 0x01000007, 0, first + len(arm), len(intel), 0)
    assert ucs.macho_uuids(header + arm + intel) == [
        ("arm64", UUID_BYTES.hex()), ("x86_64", bytes(range(16, 32)).hex()),
    ]


def test_elf_build_id():
    build_id = bytes.fromhex("0123456789abcdef0123456789abcdef01234567")
    assert ucs.elf_build_id(_elf_with_build_id(build_id)) == build_id.hex()
    assert ucs.elf_build_id(b"not an elf") is None


def test_pe_codeview_id_matches_the_symbol_server_key():
    guid = uuid.UUID("3f2504e0-4f89-11d3-9a0c-0305e82c3301")
    data = _pe_with_codeview(guid, 3, rb"C:\mixar-texture-painting\build\Prod\bin\Release\mixar.pdb")
    debug_id, pdb_name = ucs.pe_codeview(data)
    # GUID fields in GUID-string order, then the age: what mixar_crash_info.cc prints.
    assert debug_id == "3f2504e04f8911d39a0c0305e82c33013"
    assert pdb_name == "mixar.pdb"


def test_windows_prepare_files_exe_and_pdb_under_the_id(tmp_path):
    guid = uuid.UUID("3f2504e0-4f89-11d3-9a0c-0305e82c3301")
    exe = tmp_path / "Mixar.exe"
    exe.write_bytes(_pe_with_codeview(guid, 1, b"D:\\b\\mixar.pdb"))
    pdb = tmp_path / "mixar.pdb"
    pdb.write_bytes(b"pdb")
    manifests = ucs.prepare("windows", str(exe), str(tmp_path / "out"), pdb=str(pdb), version="4.3.7", git_sha="abc")
    folder = tmp_path / "out" / "by-id" / manifests[0]["id"]
    assert sorted(p.name for p in folder.iterdir()) == ["Mixar.exe", "manifest.json", "mixar.pdb"]
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["object"] == "Mixar.exe" and manifest["version"] == "4.3.7"


def test_upload_dry_run_prints_both_copies(tmp_path, capsys):
    manifests = [{"id": "ab", "arch": "arm64"}]
    ucs.upload(str(tmp_path), "s3://bucket/crash-symbols/", manifests, version="4.3.7", platform="darwin", dry_run=True)
    out = capsys.readouterr().out
    assert "s3://bucket/crash-symbols/by-id" in out and "s3://bucket/crash-symbols/versions" in out
    assert (tmp_path / "versions" / "4.3.7" / "darwin-arm64.json").exists()
