# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Wire and storage constants for Add-on Project Mode."""

PROTOCOL_VERSION = 1
CAPABILITY = "addon_project_v1"
MANIFEST_VERSION = 1
MANIFEST_DIR = ".mixar"
MANIFEST_FILE = "addon-project.json"

RPC_DESCRIBE = "addon_project.describe"
RPC_SEARCH = "addon_project.search"
RPC_READ = "addon_project.read"
RPC_STAGE_PATCH = "addon_project.stage_patch"
RPC_COMMIT_PATCH = "addon_project.commit_patch"
RPC_RUN_CHECKS = "addon_project.run_checks"
RPC_ROLLBACK = "addon_project.rollback"
RPC_HISTORY = "addon_project.history"

RPC_METHODS = frozenset({
    RPC_DESCRIBE,
    RPC_SEARCH,
    RPC_READ,
    RPC_STAGE_PATCH,
    RPC_COMMIT_PATCH,
    RPC_RUN_CHECKS,
    RPC_ROLLBACK,
    RPC_HISTORY,
})

EDITABLE_SUFFIXES = frozenset({
    ".py", ".pyi", ".toml", ".json", ".md", ".txt", ".yaml", ".yml",
})
IGNORED_PARTS = frozenset({
    ".git", ".hg", ".svn", ".mixar", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".venv", "venv", "dist", "build",
})
MAX_FILE_BYTES = 1_000_000
MAX_READ_BYTES = 250_000
MAX_SEARCH_RESULTS = 200
MAX_PROJECT_FILES = 500
MAX_PATCH_FILES = 50
MAX_PATCH_BYTES = 2_000_000
MAX_DIFF_CHARS = 40_000
