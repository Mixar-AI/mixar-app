# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The Character Parts node consumes one still carrying component masks."""


def require_character_image(contract):
    """Preserve the catalog socket identity, with a required single-image input."""
    image = next((socket for socket in contract['sockets']
                  if 'IMAGE' in socket.get('accepted_types', ())), None)
    if image is None:
        image = {'id': 'image', 'label': 'Image', 'group_id': 'image'}
    image.update(accepted_types=['IMAGE'], required=True, repeatable=False)
    contract['sockets'] = [image]
    contract['limits'] = {'IMAGE': 1}
