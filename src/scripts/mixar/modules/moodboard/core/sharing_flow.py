# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Main-thread callbacks, account/file fences, and session-only Explore cache."""
import re
import uuid
from urllib.parse import urlparse

import bpy

from mixar.config.config import get_server_url
from mixar.modules.common.api.services.moodboard_service import get_moodboard_service
from mixar.modules.common.job_queue.core.error_helpers import classify_error, sanitize_message
from .canvas_context import redraw_moodboard_canvases

records = []
_generation = 0
_account = None
lifecycle = 0


def unwrap(response):
    envelope = response.data if isinstance(response.data, dict) else {}
    data = envelope.get('data', {})
    return data if isinstance(data, dict) else {}


def error_message(error, fallback):
    if getattr(error, 'status_code', 0) in (404, 409, 413, 422):
        return sanitize_message(getattr(error, 'message', ''), fallback)
    return classify_error(error) or fallback


def identity():
    wm = bpy.context.window_manager
    return (bool(wm.mixie_chat_is_logged_in), str(bpy.context.scene.mixie_chat_user_id))


def reset():
    global _generation, _account, lifecycle
    lifecycle += 1
    _generation += 1
    _account = identity()
    records.clear()
    wm = bpy.context.window_manager
    wm.moodboard_community_busy = False
    wm.moodboard_community_notice = ""
    wm.moodboard_community_link = ""
    from .sharing_previews import clear
    clear()


def sync_account():
    if _account != identity():
        reset()


def notice(message):
    bpy.context.window_manager.moodboard_community_notice = message
    redraw_moodboard_canvases()


def url(data):
    path = data.get("share_path", "")
    return get_server_url().rstrip('/') + path if path.startswith('/api/v1/moodboards/s/') else ""


def token_from_link(value):
    parsed = urlparse(value.strip())
    configured = urlparse(get_server_url())
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {'http', 'https'} or parsed.netloc != configured.netloc:
            raise ValueError("Use a moodboard link from this Mixar server")
        value = parsed.path.rstrip('/').rsplit('/', 1)[-1]
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', value):
        raise ValueError("Paste a complete Mixar moodboard sharing link")
    return value


def request(method, path, on_success, *, message, **kwargs):
    global _generation
    sync_account()
    wm = bpy.context.window_manager
    if wm.moodboard_community_busy:
        return False
    _generation += 1
    generation, account = _generation, identity()
    wm.moodboard_community_busy = True
    notice(message)

    def valid():
        return generation == _generation and account == identity()

    def success(response):
        if not valid():
            return
        wm.moodboard_community_busy = False
        try:
            on_success(unwrap(response))
        except Exception as exc:
            notice(error_message(exc, "Couldn't open this moodboard. Try refreshing"))
        redraw_moodboard_canvases()

    def failure(error):
        if not valid():
            return
        wm.moodboard_community_busy = False
        notice(error_message(error, "Couldn't load moodboards. Check your connection and retry"))

    try:
        getattr(get_moodboard_service(), method + '_async')(
            path, on_success=success, on_error=failure, timeout=90, **kwargs)
    except Exception as exc:
        failure(exc)
    return True


def load(mode=None, page=0):
    sync_account()
    wm = bpy.context.window_manager
    if wm.moodboard_community_busy:
        return
    mode = mode or wm.moodboard_community_mode
    if mode == 'mine' and not wm.mixie_chat_is_logged_in:
        notice("Sign in to see your boards")
        return
    wm.moodboard_community_mode, wm.moodboard_community_page = mode, page
    records.clear()

    def complete(data):
        records.extend(data.get('items', []))
        if mode == 'mine':
            by_id = {r['id']: r for r in records if 'id' in r}
            for scene in bpy.data.scenes:
                current = by_id.get(scene.moodboard_share_id)
                if current:
                    scene.moodboard_share_revision = current['revision']
        wm.moodboard_community_more = bool(data.get('has_more'))
        notice("" if records else "No boards yet. Publish a board or try another search")
        from .sharing_previews import load_covers
        load_covers(records)

    request('get', mode, complete, message="Loading moodboards…",
            params={'page': page, 'q': wm.moodboard_community_query})


def publish(scene):
    from .sharing_snapshot import capture
    if not scene.moodboard_share_title.strip():
        raise ValueError("Give your moodboard a title")
    payload = capture(scene)
    snapshot = payload['snapshot']
    if not any(snapshot.get(k) for k in ('media', 'nodes', 'textboxes', 'frames', 'annotations')):
        raise ValueError("Add something to your moodboard before sharing")
    payload.update(title=scene.moodboard_share_title, description=scene.moodboard_share_description,
                   visibility=scene.moodboard_share_visibility,
                   expected_revision=scene.moodboard_share_revision)
    if not scene.moodboard_share_id:
        scene.moodboard_share_id = str(uuid.uuid4())
    board_id = scene.moodboard_share_id

    def complete(data):
        try:
            if scene.moodboard_share_id != board_id:
                return
            scene.moodboard_share_revision = data['revision']
        except ReferenceError:
            return
        bpy.context.window_manager.moodboard_community_link = url(data)
        notice("Private snapshot saved" if data['visibility'] == 'private' else "Board shared. Copy the link below")

    request('put', board_id, complete, message="Uploading moodboard…", json=payload)


def open_copy(path):
    source = bpy.context.scene

    def complete(data):
        from .sharing_snapshot import restore
        from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import (
            inherit_account, inherit_settings, switch_scene_tab, renumber_tabs,
        )
        scene = restore(data)
        inherit_account(source, scene)
        inherit_settings(source, scene)
        switch_scene_tab(scene, was=source)
        renumber_tabs()
        notice("Opened your own copy. The original board is unchanged")
        # Frame in whichever canvas host the user opened Explore from.
        epoch = lifecycle
        def frame():
            if epoch != lifecycle:
                return None
            wm = bpy.context.window_manager
            for window in wm.windows:
                if window.scene != scene:
                    continue
                for area in window.screen.areas:
                    want = 'WINDOW' if area.type == 'MIXIE' else None
                    if (area.type == 'VIEW_3D' and window.workspace.name == 'Zen Mode'
                            and wm.mixar_moodboard_drawer_amount >= .98):
                        want = 'TOOL_PROPS'
                    region = next((r for r in area.regions if r.type == want and r.width > 1), None)
                    if region:
                        with bpy.context.temp_override(window=window, area=area, region=region):
                            if bpy.ops.mixie.moodboard_frame.poll():
                                bpy.ops.mixie.moodboard_frame('EXEC_DEFAULT', selected_only=False)
            points = [(p.x, p.y) for a in scene.mixie_moodboard_annotations for p in a.points]
            if points:
                xs, ys = zip(*points)
                bpy.ops.mixie.moodboard_ensure_visible(
                    x=min(xs), y=min(ys), width=max(1, max(xs)-min(xs)),
                    height=max(1, max(ys)-min(ys)), margin=50)
            return None
        bpy.app.timers.register(frame, first_interval=.2)

    request('get', path, complete, message="Opening a copy…")


def open_share(scene):
    sync_account()
    wm = bpy.context.window_manager
    wm.moodboard_community_link = ''
    notice('')
    if not scene.moodboard_share_revision or not wm.mixie_chat_is_logged_in:
        return
    def complete(data):
        try:
            scene.moodboard_share_revision = data['revision']
        except ReferenceError:
            return
        wm.moodboard_community_link = url(data)
        notice('')
    request('get', scene.moodboard_share_id, complete, message='Loading saved snapshot…')


def change_visibility(record, visibility):
    def complete(data):
        record.update(data)
        bpy.context.window_manager.moodboard_community_link = url(data)
        for scene in bpy.data.scenes:
            if scene.moodboard_share_id == record['id']:
                scene.moodboard_share_revision = data['revision']
                scene.moodboard_share_visibility = data['visibility']
        notice("Now private. Previous links have been revoked" if visibility == 'private' else "Visibility updated; copy the new link")
    request('patch', record['id'] + '/visibility', complete, message="Updating visibility…",
            json={'visibility': visibility, 'expected_revision': record['revision']})


def delete(record):
    def complete(_data):
        if record in records:
            records.remove(record)
        for scene in bpy.data.scenes:
            if scene.moodboard_share_id == record['id']:
                scene.moodboard_share_id, scene.moodboard_share_revision = '', 0
        notice("Cloud board deleted. Your local board is still here")
    request('delete', record['id'], complete, message="Deleting cloud board…")
