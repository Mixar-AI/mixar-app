# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One semantic search of the user's indexed asset library.

Shared by the File Browser search panel (``mixie.search_assets``) and the
island Library tab's search row (``agent_bubble/core/library_search.py``).
Blocking network I/O: call it from a worker thread only, never touching
``bpy`` there.
"""

from mixar.modules.asset_search.constants import ASSET_KIND_MATERIAL, ASSET_SEARCH_ENDPOINT
from mixar.modules.asset_search.core.api_client import metered_client
from mixar.modules.common.i18n import n_, rpt_

MAX_TOP_K = 20


def _row(result):
    meta = result.get("metadata", {}) or {}
    kind = str(meta.get("kind") or "").upper()
    if not kind and result.get("asset_type") == "material":
        kind = ASSET_KIND_MATERIAL
    return {
        "name": meta.get("name") or result.get("model_name", "?"),
        "score": float(result.get("similarity_score", 0) or 0),
        "library": meta.get("library", ""),
        "blend_file": meta.get("blend_file", ""),
        "type": meta.get("type", ""),
        "kind": kind,
    }


def search(prompt, image_bytes=None, image_filename="search_query.jpg",
           top_k=3, asset_type=None):
    """Search by text and/or image; returns ``{success, message, results}``.

    ``asset_type`` is the backend filter: ``"material"``, ``"model"``,
    ``"all"``, or None for the server default (models only). Each result row
    is ``{name, score, library, blend_file, type, kind}``, best first.
    Messages are translatable templates the caller shows as-is.
    """
    try:
        # Credit-metered per call — never auto-retried (see core/api_client).
        client = metered_client()
        form_data = {"prompt": prompt or "", "top_k": str(max(1, min(MAX_TOP_K, int(top_k))))}
        if asset_type:
            form_data["asset_type"] = asset_type
        files = None
        if image_bytes:
            files = {"image": (image_filename or "search_query.jpg", image_bytes, "image/jpeg")}

        resp = client.post(
            ASSET_SEARCH_ENDPOINT,
            data=form_data,
            files=files,
            timeout=30,
            raise_for_status=False,
        )
        if resp.status_code in (400, 404) and "train" in (resp.message or "").lower():
            return {"success": False, "results": [],
                    "message": n_("Nothing is indexed yet. Train your libraries first.")}
        if resp.status_code == 404:
            return {"success": False, "results": [],
                    "message": n_("No trained model found. Please train first.")}
        if not resp.success:
            msg = resp.message or rpt_("Server returned {status}").format(status=resp.status_code)
            return {"success": False, "results": [], "message": msg}

        data = resp.data or {}
        # Backend wraps: {status, message, data: {results: [...]}}
        inner = data.get("data", data)
        rows = [_row(r) for r in inner.get("results", []) or []]
        if not rows:
            return {"success": True, "results": [], "message": n_("No matching assets found")}
        return {
            "success": True,
            "results": rows,
            "message": rpt_("Found {count} matching asset(s)").format(count=len(rows)),
        }
    except Exception as exc:  # noqa: BLE001 — surfaced to the UI, never raised
        return {"success": False, "results": [],
                "message": rpt_("Search failed: {error}").format(error=exc)}

