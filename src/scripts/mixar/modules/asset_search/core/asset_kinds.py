# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Asset kinds the embedding index knows, and their identity keys.

Objects and collections are the original "legacy" kinds: their identity is
``name|library|blend_file`` and they carry no ``kind`` on the wire, so a
library indexed before materials existed keeps the exact checksum the backend
stored for it. Materials add ``kind: "MATERIAL"`` and a fourth key segment.
"""

from mixar.modules.asset_search.constants import (
    ASSET_KIND_MATERIAL,
    INDEXED_ASSET_KINDS,
)


def wire_kind(kind):
    """``kind`` as sent to the backend: "MATERIAL", or "" for legacy kinds."""
    return ASSET_KIND_MATERIAL if str(kind or "").upper() == ASSET_KIND_MATERIAL else ""


def identity_key(name, library, blend_file, kind=""):
    """Render-filter / diff key, matching the backend's identity tuple."""
    key = f"{name}|{library}|{blend_file}"
    wk = wire_kind(kind)
    return f"{key}|{wk}" if wk else key


def identity_entry(name, library, blend_file, kind=""):
    """Minimal identity dict for status/prepare metadata."""
    entry = {"name": name, "library": library, "blend_file": blend_file}
    wk = wire_kind(kind)
    if wk:
        entry["kind"] = wk
    return entry


def kinds_form_value():
    """JSON for the ``kinds`` form field of /train and /train/prepare."""
    import json

    return json.dumps(list(INDEXED_ASSET_KINDS))
