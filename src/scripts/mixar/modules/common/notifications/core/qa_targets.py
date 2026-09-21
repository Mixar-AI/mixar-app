# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read-only semantic targets from the notification painter's actual bounds."""

import json

from .. import toast_renderer as renderer
from ..store import get_notification_store


def targets_json(region_ptr):
    rows = []
    items = {item.id: item for item in get_notification_store().get_visible()}

    def add(surface, text, value, rect):
        x, y, width, height = rect
        rows.append([surface, text, value, round(x), round(y),
                     round(x + width), round(y + height)])

    for card in renderer.toast_layouts_by_region.get(region_ptr, []):
        if card['id'] not in items:
            continue
        add('toast', card['title'], card['id'], card['rect'])
        for sample in card['samples']:
            add('toast_' + sample['kind'] + '_text', sample['text'], card['id'], sample['rect'])
    bounds = renderer.bounds_for_region(region_ptr) or {}
    for nid, *rect in bounds.get('close', []):
        if nid in items:
            add('toast_close', 'Dismiss notification', nid, rect)
    for nid, op, url, *rect in bounds.get('action', []):
        if nid in items:
            label = next((action.label for action in items[nid].actions
                          if (action.operator, action.url) == (op, url)), '')
            add('toast_action', label, nid, rect)
    for nid, url, *rect in bounds.get('url', []):
        if nid in items:
            add('toast_url', url, nid, rect)
    return json.dumps(rows)
