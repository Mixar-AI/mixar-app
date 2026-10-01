# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Context folders: local folders the user attaches to the agent chat.

The folder's absolute path never leaves this machine. A chat turn carries a
path-free manifest (``core/manifest.py``); the agent then lists, reads,
searches and views the files through the versioned ``context_folder.*``
RPCs (``core/rpc.py``) and imports models or images through a script
(``core/importer.py``) — every call addressed by an opaque folder id and a
folder-relative path, and honoured only for a folder the user attached to
that chat session (``core/grants.py``).
"""
