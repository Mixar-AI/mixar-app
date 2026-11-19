# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare can finish after Blender frees the requesting modal operator."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mixar.modules.asset_search.core import train_api as api


@pytest.mark.parametrize('outcome', ['success', 'rejected', 'exception'])
@pytest.mark.parametrize('stale', [False, True])
def test_prepare_result_delivery(monkeypatch, outcome, stale):
    class Owner:
        writes = 0

        def __setattr__(self, name, value):
            object.__setattr__(self, 'writes', self.writes + 1)
            if stale:
                raise ReferenceError('RNA owner has been removed')
            object.__setattr__(self, name, value)

    client = Mock()
    client.post.return_value = SimpleNamespace(
        success=outcome != 'rejected', message='Rejected', status_code=403,
        data={'data': {'action': 'skip', 'asset_count': 4}},
    )
    if outcome == 'exception':
        client.post.side_effect = RuntimeError('transport failure')
    logger = Mock()
    monkeypatch.setattr(api, 'train_client', lambda: client)
    monkeypatch.setattr(api, 'logger', logger)
    monkeypatch.setattr(api, 'rpt_', lambda text: text)
    owner = Owner()
    api.prepare_api([], owner)
    assert owner.writes == 1  # Never retry failure delivery through freed RNA.
    client.post.assert_called_once()
    if outcome != 'exception':
        logger.error.assert_not_called()
    if stale:
        logger.debug.assert_called_once()
    else:
        assert owner._bg_result['success'] == (outcome == 'success')
        if outcome == 'success':
            assert owner._bg_result['action'] == 'skip'
            assert owner._bg_result['asset_count'] == 4
        else:
            assert ('Rejected' if outcome == 'rejected' else 'transport failure') in owner._bg_result['message']


class _UploadOwner:
    """Stands in for the modal operator; ``freed`` mimics a removed StructRNA."""

    def __init__(self):
        object.__setattr__(self, 'freed', False)
        object.__setattr__(self, 'writes', [])

    def __setattr__(self, name, value):
        self.writes.append(name)
        if self.freed:
            raise ReferenceError('RNA owner has been removed')
        object.__setattr__(self, name, value)

    def __getattribute__(self, name):
        if name.startswith('_') and not name.startswith('__') and object.__getattribute__(self, 'freed'):
            raise ReferenceError('RNA owner has been removed')
        return object.__getattribute__(self, name)


@pytest.mark.parametrize('path', ['removal_only', 'one_batch'])
@pytest.mark.parametrize('owner_state', ['live', 'freed_before', 'freed_during_post'])
def test_post_batches_result_delivery(monkeypatch, tmp_path, path, owner_state):
    owner = _UploadOwner()
    if owner_state == 'freed_before':
        object.__setattr__(owner, 'freed', True)

    inner = {'removed': 2} if path == 'removal_only' else {'images_embedded': 3}

    def post(*args, **kwargs):
        if owner_state == 'freed_during_post':
            object.__setattr__(owner, 'freed', True)
        return SimpleNamespace(success=True, message='', status_code=200, data={'data': inner})

    client = Mock()
    client.post.side_effect = post
    logger = Mock()
    monkeypatch.setattr(api, 'train_client', lambda: client)
    monkeypatch.setattr(api, 'logger', logger)
    monkeypatch.setattr(api, 'rpt_', lambda text: text)

    if path == 'removal_only':
        batches = []
    else:
        image = tmp_path / 'chair.jpg'
        image.write_bytes(b'jpeg-bytes')
        batches = [{'metadata': [{'image_name': 'chair'}], 'files': [('chair.jpg', str(image))]}]

    api.post_batches(batches, 'full', ['old'], 'sum-1', owner)  # Must not raise.

    guard_logs = [c for c in logger.debug.call_args_list if 'owner was removed' in c.args[0]]
    assert len(guard_logs) == (0 if owner_state == 'live' else 1)
    logger.error.assert_not_called()
    if owner_state == 'freed_before':
        client.post.assert_not_called()
        assert owner.writes == ['_upload_total']
        return
    client.post.assert_called_once()
    if owner_state == 'freed_during_post':
        # Exactly one attempt at the post-response write; no failure report follows.
        assert owner.writes == ['_upload_total', '_upload_done', '_upload_embedded', '_upload_done']
        return

    assert owner._upload_total == 1
    assert owner._upload_done == 1
    if path == 'removal_only':
        assert client.post.call_args.kwargs['data'] == {
            'mode': 'incremental', 'removed_assets': '["old"]',
            'metadata': '[]', 'metadata_checksum': 'sum-1',
        }
        assert owner._upload_embedded == 0
        assert owner._bg_result == {'success': True, 'message': '2 removed', 'embedded': 0}
    else:
        assert client.post.call_args.kwargs['data'] == {
            'mode': 'full', 'removed_assets': '["old"]',
            'metadata': '[{"image_name": "chair"}]', 'metadata_checksum': 'sum-1',
        }
        assert client.post.call_args.kwargs['files'] == [
            ('images', ('chair.jpg', b'jpeg-bytes', 'image/jpeg')),
        ]
        assert owner._upload_embedded == 3
        assert owner._bg_result == {'success': True, 'message': '3 assets embedded', 'embedded': 3}
