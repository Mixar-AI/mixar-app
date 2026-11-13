# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Windows: the Running App's Own Signer

An install nobody asked for (on quit, at launch) must run only an MSI
signed by the publisher of the app that is running, which therefore must
be validly signed itself (#2079). :mod:`verify` compares publishers only
when it can read the running app's signature as ``Valid``; otherwise it
still says ``VERIFIED`` for any validly signed MSI, pinning just that
MSI's certificate. That is enough for Restart & Update (an unsigned dev
build keeps updating from a click), never for an install without one.

So this module reads the running executable's Authenticode signer once
per session, on a worker thread (:func:`read`: on the download thread,
and at launch on the launch install's own signature-check thread, before
it publishes its verdict), and the silent paths use only that cached
answer:

- :func:`silent_refusal` (from ``silent_install.silent_refusal``) refuses
  while this app's signature is not known to be ``Valid``;
- :func:`app_subject` is what the helper pins besides the thumbprint
  (``%SIGNERSUBJECT%``): the MSI it runs must carry this app's own signer
  subject, so a ``VERIFIED`` that skipped the publisher comparison cannot
  install another publisher's package silently.

Nothing here touches ``bpy`` or blocks the main thread.
"""

import threading

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

VALID = "Valid"

_lock = threading.Lock()
# signer: (status, subject, thumbprint) once read; None until then. A read
# the tool could not answer is not kept, so a later read tries again.
_cache = {"signer": None}


def read(running_binary) -> tuple:
    """Worker thread: the running app's ``(status, subject, thumbprint)``,
    ``()`` when it cannot be told. Read once per session, then cached."""
    with _lock:
        if _cache["signer"] is not None:
            return _cache["signer"]
    signer = ()
    if running_binary:
        try:
            from .verify import _authenticode

            signer = tuple(_authenticode(running_binary) or ())
        except Exception:  # noqa: BLE001 - unknown is not signed
            logger.debug("Could not read this app's signature", exc_info=True)
    with _lock:
        if signer and _cache["signer"] is None:
            _cache["signer"] = signer
        return _cache["signer"] or ()


def app_subject() -> str:
    """This app's signer subject when its signature is ``Valid``, else
    ``""`` (unsigned, invalid, unreadable or not read yet). Never blocks."""
    with _lock:
        signer = _cache["signer"] or ()
    if len(signer) >= 2 and signer[0] == VALID and signer[1]:
        return signer[1]
    return ""


def silent_refusal() -> str:
    """Why an install nobody asked for must not run on this Windows app."""
    if app_subject():
        return ""
    return "this app is not validly signed, so the update has no signer of its own to match"


def _reset_for_tests() -> None:
    with _lock:
        _cache.update(signer=None)
