# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""JWT expiry is a connection scheduling hint; the server authenticates tokens."""
import base64
import json
import math
import time

# Cover the bounded connection/startup work before server reauthentication.
EXPIRY_MARGIN_S = 30


def remaining(token):
    try:
        payload = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        expiry = claims.get('exp')
        if type(expiry) not in (int, float) or not math.isfinite(expiry):
            return None
        return expiry - time.time()
    except (ValueError, TypeError, IndexError, AttributeError, OverflowError):
        return None
