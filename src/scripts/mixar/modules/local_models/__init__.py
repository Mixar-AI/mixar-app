# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local model support: managed llama.cpp runtime + curated GGUF models.

Stage 1 (this package's ``core/``) is the bpy-free runtime layer: pinned
runtime/model catalogs, verified resumable downloads, safe archive
extraction, a llama-server process supervisor, the backend ``llm.request``
relay, and detection of user-run local servers. UI, operators and
bootstrap wiring arrive in Stage 2. See README.md and ARCHITECTURE.md.
"""
