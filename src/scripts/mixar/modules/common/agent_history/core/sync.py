# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Background archive transport. Never perform filesystem I/O on the WS/UI thread."""
import errno
import logging
import threading
import time

from ..constants import POLL_SECONDS, REQUEST_TIMEOUT
from . import store


class ArchiveSync:
    def __init__(self, client):
        self.client = client
        self.stop_event = threading.Event()
        self.owner = None
        self.scene_ids = {}
        self.last_error = None
        self.thread = None
        self.discovery_offset = 0

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name='MixarAgentArchive')
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _notice(self, code):
        if code == self.last_error:
            return
        self.last_error = code
        logging.getLogger(__name__).warning('Agent archive: %s', code)
        bodies = {
            'archive_sync_timeout': 'History sync timed out. Retrying automatically.',
            'archive_sync_unavailable': 'History sync is unavailable. Retrying when the connection is ready.',
            'archive_sync_rejected': 'The server rejected the history sync request. Update the app and backend, then reconnect.',
            'archive_owner_changed': 'History sync stopped because the signed-in account changed. Reconnect to resume.',
            'archive_gap': 'Some history is no longer available from the server. The missing range is marked in the archive.',
            'archive_blocked': 'The server history buffer is full. Saved records are being acknowledged so sync can continue.',
            'archive_disk_full': 'History could not be saved because the disk is full. Free disk space; saving will retry automatically.',
            'archive_permission_denied': 'History could not be saved because folder access was denied. Check the app’s filesystem permissions.',
            'archive_write_failed': 'History could not be saved locally. Existing records are preserved; saving will retry automatically.',
            'archive_validation_failed': 'History failed an archive integrity or identity check. Existing records are preserved; the failed batch was not acknowledged.',
        }
        from mixar.modules.common.notifications import get_notification_store
        get_notification_store().push('warning', 'Agent history needs attention',
            body=bodies.get(code, bodies['archive_write_failed']))

    def _capture_scene_ids(self):
        from mixar.modules.space_mixie_chat.core.main_thread_executor import run_on_main_thread
        ready = threading.Event()
        ok = [False]
        def collect():
            try:
                import bpy
                from mixar.modules.operation_history.core.scene_key import get_scene_history_id
                mapping = {}
                for scene in bpy.data.scenes:
                    session = getattr(scene, 'mixie_session_id', '')
                    # Private worker scenes use agentlane:<token>, not chat IDs.
                    # They are archived under their parent conversation already.
                    try:
                        store.valid_id(session)
                    except ValueError:
                        continue
                    mapping[session] = get_scene_history_id(scene)
                self.scene_ids = mapping
                ok[0] = True
            finally:
                ready.set()  # run_on_main_thread swallows exceptions; never leave the waiter hanging.
        run_on_main_thread(collect)
        # A callback dropped before registration (shutdown, timer failure) is
        # indistinguishable from a slow main thread; the poll loop simply retries.
        deadline = time.monotonic() + REQUEST_TIMEOUT
        while not ready.is_set():
            if self.stop_event.is_set() or time.monotonic() >= deadline:
                return False
            ready.wait(min(0.25, max(0.0, deadline - time.monotonic())))
        return ok[0]

    def _run(self):
        acknowledgements = []
        while not self.stop_event.is_set() and self.client.is_connected:
            if not self._capture_scene_ids():
                self.stop_event.wait(POLL_SECONDS)
                continue
            ready = threading.Event()
            reply = []
            def received(value):
                reply.append(value); ready.set()
            known = sorted(set(self.scene_ids) | set(store.known_sessions(self.owner) if self.owner else []))
            start = self.discovery_offset % max(1, len(known))
            known = known[start:] + known[:start]
            self.discovery_offset += 32
            try:
                request_id = self.client.send_request('agent.history_sync',
                    {'acknowledgements': acknowledgements, 'session_ids': known[:32]},
                    received, timeout=REQUEST_TIMEOUT)
            except Exception:
                self._notice('archive_sync_unavailable')
                self.stop_event.wait(POLL_SECONDS)
                continue
            # No disk write is acknowledged until a subsequent successful pull.
            if not ready.wait(REQUEST_TIMEOUT):
                with self.client._pending_lock:
                    self.client._pending_callbacks.pop(request_id, None)
                    self.client._pending_deadlines.pop(request_id, None)
                self._notice('archive_sync_timeout')
            elif reply and isinstance(reply[0], dict) and reply[0].get('code') == -32601:
                return  # Older backend; leave existing client features available.
            elif reply and isinstance(reply[0], dict) and reply[0].get('code') == -32602:
                self._notice('archive_sync_rejected')
            elif not reply or not isinstance(reply[0], dict) or reply[0].get('version') != 1:
                self._notice('archive_sync_unavailable')
            else:
                if self.stop_event.is_set():
                    return
                result = reply[0]
                owner = result.get('owner_id')
                if self.owner and self.owner != owner:
                    self._notice('archive_owner_changed'); return
                self.owner = owner
                acknowledgements = []
                healthy = True
                for packet in result.get('sessions', []):
                    try:
                        ack = store.write_batch(owner, packet, self.scene_ids.get(packet['session_id']))
                        if ack:
                            acknowledgements.append(ack)
                        if packet.get('status') != 'available':
                            healthy = False
                            self._notice('archive_blocked' if packet.get('status') == 'blocked' else 'archive_gap')
                    except OSError as exc:
                        healthy = False
                        code = ('archive_disk_full' if exc.errno in (errno.ENOSPC, errno.EDQUOT) else
                                'archive_permission_denied' if exc.errno in (errno.EACCES, errno.EPERM) else
                                'archive_write_failed')
                        self._notice(code)
                    except ValueError:
                        healthy = False
                        self._notice('archive_validation_failed')
                    except Exception:
                        # No path, payload or exception text in logs or RPC replies.
                        healthy = False
                        self._notice('archive_write_failed')
                if healthy:
                    self.last_error = None
            self.stop_event.wait(POLL_SECONDS)

    def read(self, params, request_id):
        def work():
            try:
                if not self.owner or params.get('owner_id') != self.owner:
                    result = {'status': 'unavailable'}
                else:
                    result = store.read(self.owner, params['session_id'],
                        message_id=params.get('message_id'), task_id=params.get('task_id'),
                        image_id=params.get('image_id'), limit=params.get('limit', 10))
            except Exception:
                result = {'status': 'unavailable'}
            if request_id and self.client.is_connected:
                self.client.queue_response(request_id, result)
        threading.Thread(target=work, daemon=True, name='MixarArchiveRead').start()
