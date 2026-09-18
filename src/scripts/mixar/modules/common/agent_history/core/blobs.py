# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Protocol v2 image bytes: fetched over HTTP, verified, re-inserted before archiving.

Runs on the archive thread only. The record the server delivered keeps its
event_id (the hash of the original record WITH base64), so after the fetch the
record is rebuilt byte-for-byte and store.write_batch verifies it unchanged.
"""
import base64
import hashlib
import logging
import re

from ..constants import BLOB_FETCH_TIMEOUT, MAX_BLOB_BYTES

_HASH = re.compile(r'^[a-f0-9]{64}$')
ENDPOINT = 'api/v1/agent/history/blob'


class BlobUnavailable(Exception):
    """The bytes could not be fetched or verified; the record must not be acknowledged.

    ``index`` is the position of the failing record in the packet, so the
    caller can still archive and acknowledge everything before it.
    """

    def __init__(self, code, index=0):
        super().__init__(code)
        self.code = code
        self.index = index


def fetch_blob(session_id, seq, timeout=BLOB_FETCH_TIMEOUT):
    from mixar.modules.common.api.client import get_http_client
    from mixar.modules.common.api.exceptions import HTTPClientError
    from mixar.modules.common.network import classify_network_error, log_network_failure
    log = logging.getLogger(__name__)
    client = get_http_client()
    url = f"{getattr(client, '_base_url', '')}/{ENDPOINT}"
    try:
        response = client.get(ENDPOINT, params={'session_id': session_id, 'seq': seq}, timeout=timeout)
    except HTTPClientError as exc:
        if exc.__cause__ is not None:  # transport failure: route through the network contract
            log_network_failure(log, classify_network_error(exc, url=url), 'Agent history blob fetch')
        else:  # an HTTP status: keep the code in the log, never the payload
            log.warning('Agent history blob fetch refused: %s status=%s seq=%s',
                        type(exc).__name__, getattr(exc, 'status_code', None), seq)
        raise BlobUnavailable(type(exc).__name__) from exc
    raw = getattr(response, 'data', None)
    if not isinstance(raw, (bytes, bytearray)):
        raw = getattr(getattr(response, 'raw', None), 'content', None)
    if not isinstance(raw, (bytes, bytearray)):
        raise BlobUnavailable('archive_blob_body_missing')
    return bytes(raw)


def _descriptor(payload):
    ref = payload.get('blob')
    if not isinstance(ref, dict):
        raise BlobUnavailable('archive_blob_descriptor_invalid')
    seq, size, digest = ref.get('seq'), ref.get('bytes'), ref.get('sha256')
    if (not isinstance(seq, int) or isinstance(seq, bool) or seq < 1
            or not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_BLOB_BYTES
            or not isinstance(digest, str) or not _HASH.fullmatch(digest)):
        raise BlobUnavailable('archive_blob_descriptor_invalid')
    return seq, size, digest


def materialize(packet, fetch=None, should_stop=None):
    """Fill every referenced image in ``packet`` in place.

    Raises BlobUnavailable (with the failing record's index) on the first
    failure or when ``should_stop()`` turns true between records; records
    before it are complete and may still be archived.
    """
    fetch = fetch or fetch_blob  # resolved per call so QA fixtures can stub the transport
    session = packet.get('session_id')
    for index, event in enumerate(packet.get('records') or []):
        record = event.get('record') if isinstance(event, dict) else None
        payload = record.get('payload') if isinstance(record, dict) else None
        if not isinstance(payload, dict) or record.get('kind') != 'image' or 'blob' not in payload:
            continue
        if should_stop is not None and should_stop():
            raise BlobUnavailable('archive_sync_stopped', index)
        try:
            seq, size, digest = _descriptor(payload)
            raw = fetch(session, seq)
        except BlobUnavailable as exc:
            raise BlobUnavailable(exc.code, index) from exc
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise BlobUnavailable('archive_blob_hash_mismatch', index)
        rebuilt = {k: v for k, v in payload.items() if k != 'blob'}
        rebuilt['base64'] = base64.b64encode(raw).decode()
        event['record'] = {**record, 'payload': rebuilt}
    return packet
