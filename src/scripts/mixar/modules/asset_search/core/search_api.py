# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Background-thread search/status HTTP calls. No Blender data access."""
import json
from mixar.config.config import get_server_url
from mixar.modules.common.api.client import HTTPClient
from .api_client import metered_client
from ..constants import ASSET_SEARCH_ENDPOINT, ASSET_STATUS_ENDPOINT

def search_api(prompt, image_bytes, operator):
    """POST a search query to the backend proxy in a background thread."""
    try:
        # Credit-metered per call — never auto-retried (see core/api_client).
        client = metered_client()
        form_data = {"prompt": prompt or "", "top_k": 20}
        if getattr(operator, '_source_id', ''):
            form_data['source_id'] = operator._source_id
        if getattr(operator, '_library_names', None) is not None:
            form_data['libraries'] = json.dumps(operator._library_names)
        files = None
        if image_bytes:
            files = {"image": ("search_query.jpg", image_bytes, "image/jpeg")}

        resp = client.post(
            ASSET_SEARCH_ENDPOINT,
            data=form_data,
            files=files,
            timeout=30,
            raise_for_status=False,
        )

        if resp.status_code == 404:
            operator._result = {
                "success": False,
                "message": "No trained model found. Please train first.",
            }
            return

        if not resp.success:
            msg = resp.message or f"Server returned {resp.status_code}"
            operator._result = {"success": False, "message": msg}
            return

        data = resp.data or {}
        # Backend wraps: {status, message, data: {results: [...]}}
        inner = data.get("data", data)
        results = inner.get("results", [])
        if not results:
            operator._result = {
                "success": True,
                "message": "No matching assets found",
                "results": [],
            }
            return

        # Structured rows: the panel renders these with score bars and a
        # "locate in browser" action, not raw text.
        rows = []
        for r in results:
            meta = r.get("metadata", {}) or {}
            rows.append({
                "metadata": meta,
                "name": meta.get("name") or r.get("model_name", "?"),
                "score": float(r.get("similarity_score", 0) or 0),
                "library": meta.get("library", ""),
                "blend_file": meta.get("blend_file", ""),
                "type": meta.get("type", ""),
            })
        operator._result = {
            "success": True,
            "message": f"Found {len(rows)} matching asset(s)",
            "results": rows,
        }
    except Exception as exc:
        operator._result = {
            "success": False,
            "message": f"Search failed: {exc}",
        }


def status_api(metadata, operator):
    """POST metadata to the backend status proxy in a background thread."""
    try:
        client = HTTPClient(base_url=get_server_url())
        resp = client.post(
            ASSET_STATUS_ENDPOINT,
            data={"metadata": json.dumps(metadata), "source_id": getattr(operator, '_source_id', '')},
            timeout=30,
            raise_for_status=False,
        )

        if resp.status_code == 404:
            operator._result = {
                "success": True,
                "needs_retraining": True,
                "message": "No trained model found. Please train first.",
            }
            return

        if not resp.success:
            msg = resp.message or f"Server returned {resp.status_code}"
            operator._result = {"success": False, "message": msg}
            return

        data = resp.data or {}
        inner = data.get("data", data)
        operator._result = {
            "success": True,
            "needs_retraining": inner.get("needs_retraining", False),
            "message": inner.get("message", ""),
        }
    except Exception as exc:
        operator._result = {
            "success": False,
            "message": f"Status check failed: {exc}",
        }


