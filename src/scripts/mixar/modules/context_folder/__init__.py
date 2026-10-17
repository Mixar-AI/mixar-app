# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Context folders and files: what the user attaches to the agent chat.

The absolute path never leaves this machine. A chat turn carries a path-free
manifest (``core/manifest.py``); the agent then lists, reads, searches, views
and samples video frames of the files through the versioned
``context_folder.*`` RPCs (``core/rpc.py``, ``core/video.py``) and imports
models or images through a script (``core/importer.py``) — every call
addressed by an opaque folder id and a folder-relative path, and honoured only
for a folder the user attached to that chat session (``core/grants.py``).
Single files (videos, documents, anything that is not an image pill or an
imported model) attach as chips and reach the agent as ONE synthetic folder,
"Attached files" (``core/files.py``, ``core/file_set.py``).
"""
