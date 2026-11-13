# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Minimal PDFs written as raw bytes, so no binary fixture is committed.

Shared by ``test_context_folder_pdf.py`` and the in-app QA checks
(``tests/qa/context_folder_files_checks.py`` loads this file by path). Pages
are 612 x 792 pt (US Letter) unless ``rotate`` turns one by 90 degrees. The
cross-reference table is exact, so PDFium never has to repair the file.
``user_password`` writes a real Standard Security Handler (RC4 40-bit, R2)
document: it opens with that password and refuses to open without it.
"""

import hashlib

# The padding string of PDF 1.7 section 7.6.3.3 (algorithm 2).
_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")
_FILE_ID = hashlib.md5(b"mixar-pdf-fixture").digest()
# A 2x2 RGB image: blue, green / red, yellow.
_PIXELS = bytes([0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 0])

# Content streams for one page each.
RED_RECT = b"1 0 0 rg 100 100 300 200 re f"  # filled red rectangle, x 100-400, y 100-300 (pt)
IMAGE_ONLY = b"q 400 0 0 400 100 200 cm /Im1 Do Q"  # the 2x2 image scaled to 400 pt


def text_page(*lines: str) -> bytes:
    """Helvetica 24 pt lines from the top of the page (ASCII, no parentheses)."""
    ops = ["BT", "/F1 24 Tf", "72 700 Td", "28 TL"]
    ops += [f"({line}) Tj T*" for line in lines]
    return "\n".join(ops + ["ET"]).encode("latin-1")


def _rc4(key: bytes, data: bytes) -> bytes:
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) % 256
        state[i], state[j] = state[j], state[i]
    out, i, j = bytearray(), 0, 0
    for byte in data:
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        out.append(byte ^ state[(state[i] + state[j]) % 256])
    return bytes(out)


def _security(user_password: str):
    """``(encrypt dictionary, file key)`` for revision 2 (algorithms 2, 3, 4)."""
    padded_user = (user_password.encode("latin-1") + _PAD)[:32]
    owner = _rc4(hashlib.md5((b"owner" + _PAD)[:32]).digest()[:5], padded_user)
    permissions = -4
    digest = hashlib.md5(padded_user + owner + (permissions & 0xFFFFFFFF).to_bytes(4, "little") + _FILE_ID)
    key = digest.digest()[:5]
    user = _rc4(key, _PAD)
    entry = f"<< /Filter /Standard /V 1 /R 2 /O <{owner.hex()}> /U <{user.hex()}> /P {permissions} >>"
    return entry.encode("latin-1"), key


def build_pdf(pages, *, rotate=None, user_password=None) -> bytes:
    """A PDF with one page per content stream in ``pages``."""
    objects = {1: b"<< /Type /Catalog /Pages 2 0 R >>"}
    kids = " ".join(f"{3 + 2 * index} 0 R" for index in range(len(pages)))
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("latin-1")
    font_id = 3 + 2 * len(pages)
    image_id = font_id + 1
    for index, content in enumerate(pages):
        turn = (rotate or {}).get(index + 1)
        rotation = f" /Rotate {turn}" if turn else ""
        objects[3 + 2 * index] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]{rotation} "
            f"/Resources << /Font << /F1 {font_id} 0 R >> /XObject << /Im1 {image_id} 0 R >> >> "
            f"/Contents {4 + 2 * index} 0 R >>").encode("latin-1")
        objects[4 + 2 * index] = (b"", content)
    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects[image_id] = (b"/Type /XObject /Subtype /Image /Width 2 /Height 2 "
                         b"/ColorSpace /DeviceRGB /BitsPerComponent 8", _PIXELS)
    encrypt_id, key = None, None
    if user_password is not None:
        encrypt_id = image_id + 1
        objects[encrypt_id], key = _security(user_password)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        body = objects[number]
        out += f"{number} 0 obj\n".encode("latin-1")
        if isinstance(body, tuple):  # (extra dictionary entries, stream data)
            extra, data = body
            if key is not None:  # algorithm 1: per-object RC4 key
                data = _rc4(hashlib.md5(key + number.to_bytes(3, "little") + b"\0\0").digest()[:10], data)
            out += b"<< " + extra + f" /Length {len(data)} >>\nstream\n".encode("latin-1")
            out += data + b"\nendstream"
        else:
            out += body
        out += b"\nendobj\n"
    xref = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode("latin-1")
    out += b"".join(f"{offsets[number]:010d} 00000 n \n".encode("latin-1") for number in range(1, size))
    encrypt = f" /Encrypt {encrypt_id} 0 R" if encrypt_id else ""
    out += (f"trailer\n<< /Size {size} /Root 1 0 R /ID [<{_FILE_ID.hex()}> <{_FILE_ID.hex()}>]{encrypt} >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode("latin-1")
    return bytes(out)


def mixed_pdf() -> bytes:
    """Page 1 text, page 2 a red rectangle only (turned 90 degrees), page 3 an image only."""
    return build_pdf([text_page("Hello PDF world", "Shield is round"), RED_RECT, IMAGE_ONLY],
                     rotate={2: 90})
