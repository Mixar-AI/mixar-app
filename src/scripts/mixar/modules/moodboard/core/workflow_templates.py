# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Workflow templates: one Add-menu entry that builds a framed graph of drafts.

A workflow is listed in ``NODE_TEMPLATES`` like any node template, so every
entry point (canvas strip, + menu, Shift+A, pie, native drag) offers it without
knowing it is special. Only availability and creation branch on it.

A ``hidden`` workflow stays registered and buildable but is never available, so
no entry point lists it and creation refuses it. Boards that already hold the
graph it built are untouched: that graph is ordinary frames and cards.

Pure data plus two predicates: safe to call from a menu draw.
"""

WORKFLOW_TEMPLATES = {
    'CHARACTER_SHEET_3D': {
        # Every member must be offered as a node template on its own…
        'members': ('IMAGE_GEN', 'MODEL_3D'),
        # …while an optional member only adds a card when it is available.
        'optional': ('AUTO_RIG',),
        # Withdrawn from every Add surface. Set False to offer it again; the
        # catalog gate in ``workflow_available`` still applies.
        'hidden': True,
        'description': (
            "Build an editable workflow from a character sheet: clean body and part "
            "references, 3D, rig and assembly. Nothing is generated until you press Generate."
        ),
    },
}


def is_workflow(template_id) -> bool:
    return template_id in WORKFLOW_TEMPLATES


def workflow_available(template_id, member_available) -> bool:
    """Visible only when the build can actually wire (never a certain rollback).

    A ``hidden`` workflow is never visible, whatever the catalog offers.

    ``member_available`` is ``node_templates.template_available``; it is passed
    in rather than imported because that module imports this one.
    """
    workflow = WORKFLOW_TEMPLATES.get(template_id)
    if workflow is None or workflow.get('hidden'):
        return False
    if not all(member_available(member) for member in workflow['members']):
        return False
    from .character_sheet_catalog import preflight

    return preflight() is not None
