# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Help > Report a Bug: attach this machine's diagnostics to the web form.

Flow (``start_bug_report``, main thread):

1. Build the support bundle (``support_bundle.build_support_bundle``) into a
   temp zip. ``scene_table`` reads ``bpy``, so this stays on the main thread.
2. Signed in: stream it to ``POST /contact/bug-report/bundle`` on the API
   worker thread and receive a ``report_id``.
3. Open ``<frontend>/bug-report?source=desktop&report=<id>&app_version=..&os=..``
   in the browser. The page shows "Diagnostics attached" with a Remove
   control (which deletes the upload server-side) and sends ``report_id`` with
   the form; the backend attaches the zip to the team's email.

Every failure still opens the form, without ``report``: signed out, upload
refused or unreachable (older backend, offline), or the bundle could not be
built. A toast says diagnostics were not attached. The URL never carries the
user's name or email — the page reports to analytics.
"""

from __future__ import annotations

import os
import platform
import tempfile
from urllib.parse import urlencode

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

logger = get_logger(__name__)

BUG_REPORT_PATH = "/bug-report"
SOURCE_DESKTOP = "desktop"
_NOTICE_ID = "mixar_bug_report_diagnostics"


def os_label() -> str:
    """Short OS description for the report, e.g. ``macOS 26.5 arm64``."""
    machine = platform.machine() or ""
    system = platform.system()
    if system == "Darwin":
        version = platform.mac_ver()[0]
        label = f"macOS {version}" if version else "macOS"
    elif system == "Windows":
        label = f"Windows {platform.release()} ({platform.version()})"
    else:
        label = f"{system} {platform.release()}".strip()
    return f"{label} {machine}".strip()[:100]


def app_version() -> str:
    try:
        from mixar.modules.common.updates.core.update_checker import get_runtime_version
        return (get_runtime_version() or "")[:50]
    except Exception:  # noqa: BLE001
        return ""


def bug_report_url(frontend_url: str, *, report_id: str = "", version: str = "",
                   os_name: str = "", bundle_bytes: int = 0) -> str:
    """The website form URL. Only non-personal fields go in the query."""
    query = {"source": SOURCE_DESKTOP}
    if report_id:
        query["report"] = report_id
        if bundle_bytes > 0:
            query["bundle_kb"] = str(max(1, round(bundle_bytes / 1024)))
    if version:
        query["app_version"] = version
    if os_name:
        query["os"] = os_name
    return f"{frontend_url.rstrip('/')}{BUG_REPORT_PATH}?{urlencode(query)}"


def report_id_from(response) -> str:
    """``report_id`` from the upload response envelope, or ``""``."""
    body = getattr(response, "data", None)
    data = body.get("data", body) if isinstance(body, dict) else {}
    value = data.get("report_id") if isinstance(data, dict) else None
    return value if isinstance(value, str) else ""


def _open_url(url: str) -> None:
    try:
        import bpy
        bpy.ops.wm.url_open(url=url)
    except Exception:  # noqa: BLE001 - no window context: fall back to the OS
        import webbrowser
        webbrowser.open(url)


def _notify(title: str, body: str = "") -> None:
    try:
        from mixar.modules.common.notifications import get_notification_store
        get_notification_store().push(
            'warning', title, body, id=_NOTICE_ID, ttl_ms=6000)
    except Exception:  # noqa: BLE001 - a notice never blocks the report
        pass


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _open_form(report_id: str = "", bundle_bytes: int = 0) -> None:
    from mixar.config.config import get_frontend_url
    _open_url(bug_report_url(
        get_frontend_url(), report_id=report_id, version=app_version(),
        os_name=os_label(), bundle_bytes=bundle_bytes))


def _signed_in() -> bool:
    try:
        from mixar.modules.auth.core.auth import get_access_token
        return bool(get_access_token())
    except Exception:  # noqa: BLE001
        return False


def _on_upload_error(error: Exception) -> None:
    from mixar.modules.common.api import exceptions as api_errors
    transport = (api_errors.ConnectionError, api_errors.TimeoutError)
    if isinstance(error, api_errors.HTTPClientError) and not isinstance(error, transport):
        # The backend answered: signed out, too large, or an older backend
        # without the endpoint (404). The form still opens.
        logger.warning("bug report diagnostics upload refused: %s",
                       getattr(error, "status_code", "?"))
    else:
        from mixar.modules.common.network import classify_network_error, log_network_failure
        log_network_failure(logger, classify_network_error(error), "bug report diagnostics upload")
    _notify(n_("Diagnostics were not attached"),
            n_("The bug report form opened without them. You can still use "
               "Help > Save Support Bundle and email the file."))
    _open_form()


def start_bug_report() -> bool:
    """Build, upload and open the form. Returns True when an upload started."""
    if not _signed_in():
        _notify(n_("Sign in to attach diagnostics"),
                n_("The bug report form opened without the app's logs."))
        _open_form()
        return False

    from .support_bundle import build_support_bundle

    # Built to a temp file, then held in memory (the backend caps a bundle at
    # 15 MB) so no file handle outlives the call and the temp file is gone
    # before the upload starts.
    fd, path = tempfile.mkstemp(prefix="mixar-report-", suffix=".zip")
    os.close(fd)
    try:
        build_support_bundle(path)
        with open(path, "rb") as bundle:
            payload = bundle.read()
    except Exception as error:  # noqa: BLE001
        logger.error("bug report bundle failed: %s", error, exc_info=True)
        _notify(n_("Diagnostics were not attached"))
        _open_form()
        return False
    finally:
        _remove(path)

    def on_success(response):
        report_id = report_id_from(response)
        if not report_id:
            logger.warning("bug report diagnostics upload returned no report id")
            _notify(n_("Diagnostics were not attached"))
        _open_form(report_id, len(payload) if report_id else 0)

    try:
        from mixar.modules.common.api.services import get_contact_service
        get_contact_service().upload_bug_report_bundle_async(
            content_length=len(payload), body_factory=lambda: payload,
            on_success=on_success, on_error=_on_upload_error)
    except Exception as error:  # noqa: BLE001
        _on_upload_error(error)
        return False
    return True
