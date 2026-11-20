# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""User-facing words for the device check and the lobe refit (translated at display)."""

from __future__ import annotations

import json

from mixar.modules.common.i18n import iface_, n_

from .. import constants as C
from . import device_fit

REASONS = {
    device_fit.REASON_ACCEPTED: n_("it predicts unseen angles better than the file's lobes"),
    device_fit.REASON_MEAN: n_("it does not lower the mean error at unseen angles"),
    device_fit.REASON_MAX: n_("it does not lower the largest error at unseen angles"),
    device_fit.REASON_ALBEDO: n_("its lobes would reflect more light than they receive"),
}


def reason_text(code: str) -> str:
    return iface_(REASONS.get(code, code))


def device_check(mat) -> dict | None:
    """The material's stored device check, or None (no readings, or not a car paint)."""
    raw = mat.get(C.PROP_DEVICE_CHECK) if mat is not None else None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
