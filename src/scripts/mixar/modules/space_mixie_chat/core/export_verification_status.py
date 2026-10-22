# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Separate file creation from delivery verification without breaking success."""


def verification_status(verification):
    if not verification or not verification.get('checked'):
        return 'unverified'
    return 'verified' if verification.get('passed') else 'verification_failed'


def verification_warning(verification):
    status = verification_status(verification)
    if status == 'verified':
        return ''
    # Agent protocol text, not a local UI string. Never claim an unchecked
    # output passed, or hide a mismatch behind the file-written success flag.
    return ('The file was written, but verification found issues. Review verification.issues before using it.'
            if status == 'verification_failed' else
            'The file was written, but could not be fully verified. Review verification.issues before using it.')


def gltf_mesh_instances(doc):
    """Count reachable mesh nodes, not shared mesh definitions or orphan nodes."""
    nodes, meshes = doc.get('nodes') or [], doc.get('meshes') or []
    scenes = doc.get('scenes') or []
    if scenes:
        roots = scenes[doc.get('scene', 0)].get('nodes') or []
    else:
        children = {c for n in nodes for c in n.get('children', [])}
        roots = [i for i in range(len(nodes)) if i not in children]
    pending, seen, count = list(roots), set(), 0
    while pending:
        index = pending.pop()
        if index in seen or not 0 <= index < len(nodes):
            continue
        seen.add(index)
        node = nodes[index]
        mesh = node.get('mesh')
        if isinstance(mesh, int) and 0 <= mesh < len(meshes):
            count += 1
        pending.extend(node.get('children') or [])
    return count
