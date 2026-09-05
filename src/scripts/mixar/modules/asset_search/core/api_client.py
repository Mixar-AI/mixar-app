# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTP client for the credit-metered asset-search endpoints.

The shared client retries 5xx on POST, which is wrong for every endpoint in
this module: `/train`, `/train/prepare`, `/search` and `/search-batch` are
charged PER REQUEST and are not idempotent, so a retry re-does the work and
charges again. Worse, it hides the failure — urllib3 raises ResponseError once
retries are exhausted instead of returning the response, so the server's own
error never reaches the log.

That cost real time: a `/search` returning 500 for `column
asset_embeddings.provenance does not exist` surfaced to the user as
"Max retries exceeded … too many 500 error responses", four times per search at
10 credits each, with the actual reason nowhere in sight.

Without retries a transient 5xx just fails the call, the server's status and
detail are reported, and the user retries deliberately.
"""

from mixar.config.config import get_server_url
from mixar.modules.common.api.client import HTTPClient


def metered_client():
    """A client for asset-search calls that cost credits — no automatic retry."""
    return HTTPClient(base_url=get_server_url(), retry_count=0)
