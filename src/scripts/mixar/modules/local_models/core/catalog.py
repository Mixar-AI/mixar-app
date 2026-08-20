# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure logic over the pinned model catalog: fit ladder + recommendation.

Fit rule (LM Studio-style "likely too large" guardrail):

- ``fits``    — total file bytes * 1.15 + 2 GiB <= total RAM (weights plus
                context/overhead headroom comfortably fit);
- ``tight``   — the files alone fit in RAM but headroom does not (warn);
- ``too_big`` — the files alone exceed RAM;
- ``unknown`` — RAM could not be probed (0): show no fit warnings.

Everything here is deterministic over ``constants.MODEL_CATALOG`` and the
injected RAM/downloaded state, so the ladder is fully unit-testable. The
zero-argument defaults pull live state from platform_info and manifest.
"""

from typing import Dict, Iterable, List, Optional

from ..constants import DEFAULT_MODEL_ID, MODEL_CATALOG, MODEL_DOWNLOAD_URL_TEMPLATE

_FIT_OVERHEAD_FACTOR = 1.15
_FIT_HEADROOM_BYTES = 2 * 1024 ** 3  # 2 GiB


def get_model(model_id: str) -> Optional[dict]:
    """The catalog entry for *model_id*, or None."""
    for entry in MODEL_CATALOG:
        if entry["id"] == model_id:
            return entry
    return None


def required_files(model_id: str) -> List[dict]:
    """The files a model needs: [{name, url, size, sha256}, ...]."""
    entry = get_model(model_id)
    if entry is None:
        return []
    files = [entry["file"]]
    if entry.get("mmproj"):
        files.append(entry["mmproj"])
    return [
        {
            "name": spec["name"],
            "url": MODEL_DOWNLOAD_URL_TEMPLATE.format(
                repo=entry["repo"], file=spec["name"]
            ),
            "size": spec["size"],
            "sha256": spec["sha256"],
        }
        for spec in files
    ]


def total_bytes(model_id: str) -> int:
    return sum(spec["size"] for spec in required_files(model_id))


def fit_state(model_id: str, total_ram_bytes: int) -> str:
    """"fits" | "tight" | "too_big" | "unknown" for *model_id* on this RAM."""
    if not total_ram_bytes:
        return "unknown"
    required = total_bytes(model_id)
    if required * _FIT_OVERHEAD_FACTOR + _FIT_HEADROOM_BYTES <= total_ram_bytes:
        return "fits"
    if required <= total_ram_bytes:
        return "tight"
    return "too_big"


def _live_ram() -> int:
    from . import platform_info

    return platform_info.total_ram_bytes()


def _live_downloaded_ids() -> tuple:
    from . import manifest

    return manifest.ready_model_ids()


def list_models(*, total_ram_bytes: Optional[int] = None,
                downloaded_ids: Optional[Iterable[str]] = None) -> List[Dict]:
    """Catalog entries with computed per-entry state for the UI.

    Each returned dict is the catalog entry plus ``downloaded`` (bool),
    ``fit`` (see :func:`fit_state`), ``total_bytes`` and ``recommended``
    (exactly one True entry). Pass *total_ram_bytes* / *downloaded_ids*
    explicitly in tests; defaults probe the machine and the manifest.
    """
    ram = _live_ram() if total_ram_bytes is None else total_ram_bytes
    downloaded = set(
        _live_downloaded_ids() if downloaded_ids is None else downloaded_ids
    )
    recommended_id = recommend_default(total_ram_bytes=ram)
    result = []
    for entry in MODEL_CATALOG:
        model_id = entry["id"]
        item = dict(entry)
        item["downloaded"] = model_id in downloaded
        item["fit"] = fit_state(model_id, ram)
        item["total_bytes"] = total_bytes(model_id)
        item["recommended"] = model_id == recommended_id
        result.append(item)
    return result


def recommend_default(*, total_ram_bytes: Optional[int] = None) -> str:
    """The largest model that comfortably fits, else the catalog default."""
    ram = _live_ram() if total_ram_bytes is None else total_ram_bytes
    fitting = [
        entry["id"] for entry in MODEL_CATALOG
        if fit_state(entry["id"], ram) == "fits"
    ]
    if fitting:
        return max(fitting, key=total_bytes)
    return DEFAULT_MODEL_ID
