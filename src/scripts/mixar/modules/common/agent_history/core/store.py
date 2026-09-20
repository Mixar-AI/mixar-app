# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Durable session JSONL + content-addressed blobs, with a rebuildable manifest.

One OS lock serializes writers across processes. Blobs are fsynced before the
journal; the manifest/cursor is fsynced last. No acknowledgement on write failure.
All public IDs are validated; user filesystem paths never appear in responses.
"""
from __future__ import annotations
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid

from ..constants import MAX_BLOB_BYTES, MAX_READ_CHARS, MAX_READ_RECORDS, MAX_RECORD_BYTES, SEGMENT_BYTES

_LOCK = threading.RLock()
_ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
_HASH = re.compile(r'^[a-f0-9]{64}$')


def valid_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError('invalid_archive_id')
    return value


def root():
    return Path.home() / '.mixar' / 'agent_history'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _fsync_dir(path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with open(temporary, 'xb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def _locked(session):
    directory = root() / valid_id(session)
    with _LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / '.lock', 'a+b') as handle:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                if not handle.read(1):
                    handle.write(b'0'); handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield directory
            finally:
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _manifest(directory, owner):
    path = directory / 'manifest.json'
    if path.exists():
        value = json.loads(path.read_text())
        if value.get('owner_id') != owner or value.get('version') != 1:
            raise ValueError('archive_owner_or_version_mismatch')
        return value
    if any((directory / 'events').glob('*.jsonl')):
        raise ValueError('archive_manifest_missing')
    return {'version': 1, 'session_id': directory.name, 'owner_id': owner,
            'scene_history_id': None, 'cursors': {}, 'gaps': [], 'segment': 1}


def _tail(directory, manifest):
    """Repair only an incomplete final line. Complete corrupt records fail closed."""
    folder = directory / 'events'
    folder.mkdir(exist_ok=True)
    segments = sorted(folder.glob('*.jsonl'))
    path = segments[-1] if segments else folder / '000001.jsonl'
    if path.exists():
        with open(path, 'r+b') as handle:
            raw = handle.read()
            end = raw.rfind(b'\n') + 1
            if end < len(raw):
                handle.truncate(end); handle.flush(); os.fsync(handle.fileno())
            for line in raw[:end].splitlines():
                event = json.loads(line)
                epoch = event['epoch']
                manifest['cursors'][epoch] = max(manifest['cursors'].get(epoch, 0), event['seq'])
    manifest['segment'] = int(path.stem)
    return path


def _blob(directory, raw):
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError('archive_blob_too_large')
    digest = hashlib.sha256(raw).hexdigest()
    path = directory / 'blobs' / digest
    if not path.exists():
        _atomic(path, raw)
    elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('archive_blob_corrupt')
    return digest


def _verify_replay(directory, epoch, seq, event_id):
    for segment in sorted((directory / 'events').glob('*.jsonl'), reverse=True):
        for line in reversed(segment.read_bytes().splitlines()):
            row = json.loads(line)
            if row['epoch'] == epoch and row['seq'] == seq:
                if row['event_id'] != event_id:
                    raise ValueError('archive_replay_conflict')
                return
    raise ValueError('archive_cursor_without_record')


def write_batch(owner, packet, scene_history_id=None):
    session = valid_id(packet['session_id'])
    epoch = packet.get('epoch')
    if epoch and (not isinstance(epoch, str) or not re.fullmatch(r'[a-f0-9]{32}', epoch)):
        raise ValueError('invalid_archive_epoch')
    if packet.get('records') and not epoch:
        raise ValueError('missing_archive_epoch')
    with _locked(session) as directory:
        manifest = _manifest(directory, valid_id(owner))
        if scene_history_id:
            scene_id = valid_id(scene_history_id)
            if manifest['scene_history_id'] not in (None, scene_id):
                # A scene copy may keep the session ID. Preserve original binding.
                raise ValueError('archive_scene_mismatch')
            manifest['scene_history_id'] = scene_id
        # Persist ownership before the first journal write, including crashes.
        if not (directory / 'manifest.json').exists():
            _atomic(directory / 'manifest.json', canonical(manifest))
            _fsync_dir(directory.parent)
        path = _tail(directory, manifest)
        if packet.get('status') in ('gap', 'unavailable'):
            gap = {'epoch': epoch, 'reason': str(packet.get('reason') or 'unavailable')[:80]}
            if gap not in manifest['gaps']:
                manifest['gaps'].append(gap)
        if epoch and manifest['cursors'] and epoch not in manifest['cursors']:
            gap = {'epoch': epoch, 'reason': 'delivery_epoch_changed'}
            if gap not in manifest['gaps']:
                manifest['gaps'].append(gap)
        for event in packet.get('records', []):
            seq = event['seq']
            if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
                raise ValueError('invalid_archive_sequence')
            cursor = manifest['cursors'].get(epoch, 0)
            raw = canonical(event['record'])
            if len(raw) > MAX_RECORD_BYTES or hashlib.sha256(raw).hexdigest() != event['event_id']:
                raise ValueError('archive_record_hash_mismatch')
            if seq <= cursor:
                _verify_replay(directory, epoch, seq, event['event_id'])
                continue  # replay after durable write, before acknowledgement
            if seq != cursor + 1:
                gap = {'epoch': epoch, 'reason': 'archive_sequence_gap', 'expected': cursor + 1, 'received': seq}
                if gap not in manifest['gaps']:
                    manifest['gaps'].append(gap)
                _atomic(directory / 'manifest.json', canonical(manifest))
                raise ValueError('archive_sequence_gap')
            record = event['record']
            if record.get('version') != 1:
                raise ValueError('unsupported_archive_version')
            # Run/task IDs are metadata, never path components.
            if any(not isinstance(record.get(k), str) or len(record[k]) > 256 for k in ('run_id', 'task_id')):
                raise ValueError('invalid_archive_identity')
            payload = record.get('payload', {})
            if record['kind'] == 'image':
                image = base64.b64decode(payload['base64'], validate=True)
                if len(image) > MAX_BLOB_BYTES or hashlib.sha256(image).hexdigest()[:16] != payload['id']:
                    raise ValueError('archive_image_hash_mismatch')
                image_blob = _blob(directory, image)
                # Keep only a descriptor in the record blob; bytes are separate.
                record = {**record, 'payload': {k: v for k, v in payload.items() if k != 'base64'}}
                record['payload']['blob'] = image_blob
            body = _blob(directory, canonical(record))
            row = {'epoch': epoch, 'seq': seq, 'event_id': event['event_id'],
                   'run_id': record['run_id'], 'task_id': record['task_id'],
                   'kind': record['kind'], 'message_id': payload.get('id'), 'body': body}
            if path.exists() and path.stat().st_size >= SEGMENT_BYTES:
                manifest['segment'] += 1
                path = directory / 'events' / ('%06d.jsonl' % manifest['segment'])
            with open(path, 'ab') as handle:
                handle.write(canonical(row) + b'\n'); handle.flush(); os.fsync(handle.fileno())
            _fsync_dir(path.parent)
            manifest['cursors'][epoch] = seq
        _atomic(directory / 'manifest.json', canonical(manifest))
        return {'session_id': session, 'epoch': epoch,
                'seq': manifest['cursors'].get(epoch, 0)} if epoch else None


def read(owner, session, message_id=None, task_id=None, image_id=None, limit=10):
    """Bounded read-only retrieval. No supplied paths and no script execution."""
    directory = root() / valid_id(session)
    if not directory.is_dir():
        return {'status': 'unavailable'}
    limit = max(1, min(int(limit), MAX_READ_RECORDS))
    with _locked(session):
        manifest = _manifest(directory, valid_id(owner))
        rows, used = [], 0
        for segment in sorted((directory / 'events').glob('*.jsonl'), reverse=True):
            for line in reversed(segment.read_bytes().splitlines()):
                event = json.loads(line)
                if task_id and event['task_id'] != task_id:
                    continue
                if message_id and event.get('message_id') != message_id:
                    continue
                if image_id and (event['kind'] != 'image' or event.get('message_id') != image_id):
                    continue
                digest = event['body']
                if not _HASH.fullmatch(digest):
                    raise ValueError('archive_blob_id_invalid')
                raw = (directory / 'blobs' / digest).read_bytes()
                if hashlib.sha256(raw).hexdigest() != digest:
                    raise ValueError('archive_blob_corrupt')
                record = json.loads(raw)
                if image_id:
                    blob = record['payload']['blob']
                    if not _HASH.fullmatch(blob):
                        raise ValueError('archive_blob_id_invalid')
                    image = (directory / 'blobs' / blob).read_bytes()
                    if hashlib.sha256(image).hexdigest() != blob:
                        raise ValueError('archive_blob_corrupt')
                    return {'status': 'available', 'image': {**record['payload'],
                            'base64': base64.b64encode(image).decode()}}
                text = raw.decode()
                remaining = MAX_READ_CHARS - used
                if remaining <= 0:
                    return {'status': 'available', 'records': rows, 'gaps': manifest['gaps']}
                rows.append({'event_id': event['event_id'], 'text': text[:remaining],
                             'truncated': len(text) > remaining})
                used += min(len(text), remaining)
                if len(rows) >= limit or message_id:
                    return {'status': 'available', 'records': rows, 'gaps': manifest['gaps']}
        return {'status': 'available' if rows else 'unavailable', 'records': rows,
                'gaps': manifest['gaps']}


def known_sessions(owner):
    """Local opaque IDs for reconnect discovery; never expose another owner's IDs."""
    result = []
    for path in root().glob('*/manifest.json'):
        try:
            manifest = json.loads(path.read_text())
            if manifest.get('owner_id') == owner:
                result.append(valid_id(path.parent.name))
        except (ValueError, OSError):
            continue
    return result
