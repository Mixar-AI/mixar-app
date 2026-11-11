# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""An upload may outlive the Blender operator receiving its progress."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mixar.modules.asset_search.core import train_stream as ts


class Owner:
    def __init__(self, fail_at=None):
        object.__setattr__(self, 'writes', 0)
        object.__setattr__(self, 'fail_at', fail_at)
        object.__setattr__(self, '_metadata_checksum', 'checksum')

    def __setattr__(self, name, value):
        object.__setattr__(self, 'writes', self.writes + 1)
        if self.fail_at is not None and self.writes >= self.fail_at:
            raise ReferenceError('RNA owner has been removed')
        object.__setattr__(self, name, value)


@pytest.fixture
def client(monkeypatch):
    client = Mock()
    client.post.return_value = SimpleNamespace(
        success=True, data={'images_embedded': 2}, message='', status_code=200)
    monkeypatch.setattr(ts, 'train_client', lambda: client)
    monkeypatch.setattr(ts, '_read_batch_files', lambda files: [])
    monkeypatch.setattr(ts, 'logger', Mock())
    return client


def batches(count=1):
    stream = ts.BatchStream()
    for _ in range(count):
        stream.push({'metadata': [], 'files': []})
    stream.close()
    return stream


@pytest.mark.parametrize('fail_at', [1, 2, 3, 4, 5])
def test_stale_owner_at_initialization_progress_or_completion(client, fail_at):
    owner = Owner(fail_at)
    stream = batches()
    ts.post_stream(stream, 'incremental', [], owner)
    assert stream.aborted
    assert owner.writes == fail_at  # No second report through freed RNA.
    ts.logger.error.assert_not_called()


def test_stale_owner_stops_queued_batches(client):
    stream = batches(2)
    ts.post_stream(stream, 'incremental', [], Owner(3))
    assert stream.aborted
    assert client.post.call_count == 1
    assert stream.pop() is None


@pytest.mark.parametrize('failure', ['rejected', 'exception'])
def test_stale_owner_during_failure_reporting(client, failure):
    if failure == 'rejected':
        client.post.return_value.success = False
    else:
        client.post.side_effect = RuntimeError('transport failure')
    owner = Owner(3)
    stream = batches()
    ts.post_stream(stream, 'incremental', [], owner)
    assert stream.aborted
    assert owner.writes == 3


def test_stale_checksum_read(client):
    class RemovedOwner(Owner):
        @property
        def _metadata_checksum(self):
            raise ReferenceError('RNA owner has been removed')

        def __init__(self):
            object.__setattr__(self, 'writes', 0)
            object.__setattr__(self, 'fail_at', None)

    stream = batches(0)
    ts.post_stream(stream, 'incremental', ['removed'], RemovedOwner())
    assert stream.aborted
    client.post.assert_not_called()
    ts.logger.error.assert_not_called()


def test_live_owner_completes_and_preserves_protocol(client):
    owner = Owner()
    stream = batches(2)
    ts.post_stream(stream, 'full', ['removed'], owner)
    assert not stream.aborted
    assert owner._upload_done == 2
    assert owner._upload_embedded == 4
    assert owner._bg_result['success'] is True
    calls = client.post.call_args_list
    assert calls[0].kwargs['data']['mode'] == 'full'
    assert calls[1].kwargs['data']['mode'] == 'incremental'
    assert calls[1].kwargs['data']['removed_assets'] == '[]'


def test_live_owner_still_receives_transport_failure(client):
    client.post.side_effect = RuntimeError('transport failure')
    owner = Owner()
    stream = batches()
    ts.post_stream(stream, 'incremental', [], owner)
    assert stream.aborted
    assert owner._bg_result['success'] is False
    assert 'transport failure' in owner._bg_result['message']
