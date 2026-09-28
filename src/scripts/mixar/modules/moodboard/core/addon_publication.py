# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit publication of one local Mixar add-on; never installs shared code."""
import uuid

import bpy

from mixar.modules.addon_project.service import get_addon_project_service
from mixar.modules.addon_project.storage import read_json, write_json_atomic
from mixar.modules.addon_project.core.publication_package import package
from . import sharing_flow as flow

choices = []
preview = {}
project_id = ''
prepared_account = None
preparing = False
saved_publication = {}


def _registry():
    return get_addon_project_service().storage_dir / 'publications.json'


def _key(module):
    return ':'.join((flow.identity()[1], project_id, module))


def stored(module):
    return read_json(_registry(), {}).get(_key(module), {})


def remember(module, value):
    data = read_json(_registry(), {})
    data[_key(module)] = value
    write_json_atomic(_registry(), data)
    saved_publication.clear()
    saved_publication.update(value)


def prepare(scene):
    global project_id, prepared_account, preparing
    service = get_addon_project_service()
    project_id = scene.mixie_addon_project_id
    if not project_id and service.get_workspace_root():
        linked = service.link_workspace_root()
        project_id = linked['project_id']
        scene.mixie_addon_project_id = project_id
        scene.mixie_addon_project_name = linked['name']
    choices.clear()
    preview.clear()
    prepared_account = flow.identity()
    if not project_id:
        return
    description = service.describe(project_id)
    names = [a['name'] for a in description.get('addons', [])]
    if not names and description.get('entrypoint'):
        names = [description['entrypoint']]
    choices.extend((name, name.replace('_', ' ').title(), 'Publish only this add-on') for name in names)
    if choices:
        wm = bpy.context.window_manager
        preparing = True
        try:
            wm.community_addon_module = description['entrypoint'] if description['entrypoint'] in names else names[0]
        finally:
            preparing = False
        select()


def select():
    preview.clear()
    wm = bpy.context.window_manager
    module = wm.community_addon_module
    if not module or not project_id:
        return
    try:
        service = get_addon_project_service()
        with service._lock:
            root, manifest = service._resolve(project_id)
            result = package(root, module, workspace=bool(manifest.get('workspace')))
        # Keep metadata only between actions; capture current source on publish.
        preview.update({k: v for k, v in result.items() if k != 'archive'})
        info, saved = result['info'], stored(module)
        saved_publication.clear()
        saved_publication.update(saved)
        wm.community_addon_title = saved.get('title') or str(info.get('name') or module.replace('_', ' ').title())
        wm.community_addon_description = saved.get('description') or str(info.get('description') or '')
        version = info.get('version', (1, 0, 0))
        wm.community_addon_version = saved.get('details', {}).get('version') or '.'.join(map(str, version))
        wm.community_addon_license = saved.get('details', {}).get('license', 'GPL-3.0-or-later')
        wm.community_addon_category = saved.get('details', {}).get('category', 'Other')
        wm.community_addon_visibility = saved.get('visibility', 'private')
        wm.moodboard_community_link = flow.url(saved)
        flow.notice('')
        if saved.get('id'):
            def complete(data):
                remember(module, data)
                if wm.community_addon_module == module:
                    wm.community_addon_visibility = data['visibility']
                    wm.moodboard_community_link = flow.url(data)
                    flow.notice('')
            flow.request('get', saved['id'], complete, message='Checking published version…')
    except Exception as exc:
        flow.notice(getattr(exc, 'message', str(exc)))


def publish():
    wm = bpy.context.window_manager
    if prepared_account != flow.identity():
        raise ValueError('Your account changed. Reopen Publish Add-on')
    module = wm.community_addon_module
    if module not in {c[0] for c in choices}:
        raise ValueError('Choose an add-on created in Mixar')
    if not wm.community_addon_title.strip() or not wm.community_addon_description.strip():
        raise ValueError('Add a title and a description of what your add-on does')
    service = get_addon_project_service()
    with service._lock:
        root, manifest = service._resolve(project_id)
        content = package(root, module, workspace=bool(manifest.get('workspace')))
    saved = stored(module)
    payload = {k: getattr(wm, 'community_addon_' + k) for k in
               ('title', 'description', 'visibility', 'version', 'license', 'category')}
    payload.update(module=module, archive=content['archive'], expected_revision=saved.get('revision', 0))
    ident = saved.get('id') or str(uuid.uuid4())
    def complete(data):
        remember(module, data)
        wm.moodboard_community_link = flow.url(data)
        flow.notice('Private add-on saved' if data['visibility'] == 'private' else 'Add-on published. Your source package is ready to share')
    flow.request('put', 'addons/' + ident, complete, message='Publishing add-on…', json=payload)
