# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""safe_extract: traversal rejection + layout normalization."""

import io
import os
import tarfile
import zipfile

import pytest

from mixar.modules.local_models.core.archive import ArchiveError, safe_extract


def make_tar(path, members):
    """members: [(name, data|None for dir, mode)] or TarInfo tuples with
    ('sym', name, linkname)."""
    with tarfile.open(path, "w:gz") as tar:
        for member in members:
            if member[0] == "sym":
                _, name, linkname = member
                info = tarfile.TarInfo(name)
                info.type = tarfile.SYMTYPE
                info.linkname = linkname
                tar.addfile(info)
                continue
            name, data, mode = member
            info = tarfile.TarInfo(name)
            info.mode = mode
            if data is None:
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))


def make_zip(path, members):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members:
            archive.writestr(name, data)


def test_nested_tar_layout_is_flattened(tmp_path):
    archive = str(tmp_path / "llama.tar.gz")
    make_tar(archive, [
        ("llama-b10485", None, 0o755),
        ("llama-b10485/llama-server", b"#!server", 0o755),
        ("llama-b10485/libggml.0.dylib", b"lib", 0o644),
        ("sym", "llama-b10485/libggml.dylib", "libggml.0.dylib"),
        ("llama-b10485/LICENSE", b"GPL", 0o644),
    ])
    dest = str(tmp_path / "out")
    safe_extract(archive, dest)
    assert sorted(os.listdir(dest)) == [
        "LICENSE", "libggml.0.dylib", "libggml.dylib", "llama-server",
    ]
    server = os.path.join(dest, "llama-server")
    assert os.path.isfile(server)
    if os.name == "posix":
        assert os.stat(server).st_mode & 0o111 == 0o111
        assert os.path.islink(os.path.join(dest, "libggml.dylib"))


def test_flat_zip_layout_stays_flat(tmp_path):
    archive = str(tmp_path / "llama.zip")
    make_zip(archive, [
        ("llama-server.exe", b"exe"),
        ("ggml.dll", b"dll"),
        ("llama-server-impl.dll", b"impl"),
    ])
    dest = str(tmp_path / "out")
    safe_extract(archive, dest)
    assert sorted(os.listdir(dest)) == [
        "ggml.dll", "llama-server-impl.dll", "llama-server.exe",
    ]


def test_traversal_member_rejected_tar(tmp_path):
    archive = str(tmp_path / "evil.tar.gz")
    make_tar(archive, [("../evil.txt", b"x", 0o644)])
    with pytest.raises(ArchiveError):
        safe_extract(archive, str(tmp_path / "out"))
    assert not (tmp_path / "evil.txt").exists()


def test_absolute_member_rejected_tar(tmp_path):
    archive = str(tmp_path / "evil.tar.gz")
    make_tar(archive, [("/abs/evil.txt", b"x", 0o644)])
    with pytest.raises(ArchiveError):
        safe_extract(archive, str(tmp_path / "out"))


def test_traversal_member_rejected_zip(tmp_path):
    archive = str(tmp_path / "evil.zip")
    make_zip(archive, [("../../evil.txt", b"x")])
    with pytest.raises(ArchiveError):
        safe_extract(archive, str(tmp_path / "out"))


def test_drive_letter_member_rejected_zip(tmp_path):
    archive = str(tmp_path / "evil.zip")
    make_zip(archive, [("C:/evil.txt", b"x")])
    with pytest.raises(ArchiveError):
        safe_extract(archive, str(tmp_path / "out"))


def test_symlink_escaping_dest_rejected(tmp_path):
    archive = str(tmp_path / "evil.tar.gz")
    make_tar(archive, [
        ("llama-b10485/ok", b"x", 0o644),
        ("sym", "llama-b10485/escape", "../../../etc/passwd"),
    ])
    with pytest.raises(ArchiveError):
        safe_extract(archive, str(tmp_path / "out"))


def test_absolute_symlink_rejected(tmp_path):
    archive = str(tmp_path / "evil.tar.gz")
    make_tar(archive, [
        ("llama-b10485/ok", b"x", 0o644),
        ("sym", "llama-b10485/escape", "/etc/passwd"),
    ])
    with pytest.raises(ArchiveError):
        safe_extract(archive, str(tmp_path / "out"))


def test_unsupported_extension_rejected(tmp_path):
    weird = tmp_path / "thing.rar"
    weird.write_bytes(b"not an archive")
    with pytest.raises(ArchiveError):
        safe_extract(str(weird), str(tmp_path / "out"))


def test_corrupt_tar_raises_archive_error(tmp_path):
    corrupt = tmp_path / "broken.tar.gz"
    corrupt.write_bytes(b"definitely not gzip")
    with pytest.raises(ArchiveError):
        safe_extract(str(corrupt), str(tmp_path / "out"))
