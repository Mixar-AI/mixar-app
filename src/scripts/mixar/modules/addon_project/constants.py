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
# run_checks accepts an OPTIONAL client-defined "entrypoint" param (validated
# single-segment module name that must resolve inside the project); it falls
# back to the manifest entrypoint when omitted. Lets the agent target one
# add-on when the linked project is a whole workspace root of several.
RPC_RUN_CHECKS = "addon_project.run_checks"
RPC_ROLLBACK = "addon_project.rollback"
RPC_HISTORY = "addon_project.history"
# set_enabled params (client-defined contract): "enabled" bool (required);
# "uninstall" bool (only meaningful with enabled=False: disable AND remove
# this project's install symlink — project files are never touched; a real
# dir/file or foreign symlink at the target fails closed untouched);
# optional "entrypoint" validated like run_checks' (single top-level module
# resolving inside the project; falls back to the manifest entrypoint).
RPC_SET_ENABLED = "addon_project.set_enabled"

RPC_METHODS = frozenset({
    RPC_DESCRIBE,
    RPC_SEARCH,
    RPC_READ,
    RPC_STAGE_PATCH,
    RPC_COMMIT_PATCH,
    RPC_RUN_CHECKS,
    RPC_ROLLBACK,
    RPC_HISTORY,
    RPC_SET_ENABLED,
})

# One source of truth for the workspace layout convention: describe ships it
# proactively (the "layout" field) and the workspace_root_layout stage error
# repeats it, so the agent learns the rule BEFORE its first commit.
WORKSPACE_LAYOUT_RULE = (
    "Create each add-on as its own top-level package: "
    "<addon_name>/__init__.py (snake_case). Never create files at the "
    "project root."
)

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
# Bounds the WHOLE linked tree. Since the workspace root became the single
# linked project (every add-on inside it indexes together), 500 was too tight
# for a multi-add-on workspace; iter_project_files still fails closed with a
# clear "project_too_large" AddonProjectError at the cap, and describe payload
# size grows with this, so keep it workspace-scale rather than unbounded.
MAX_PROJECT_FILES = 2000
MAX_PATCH_FILES = 50
MAX_PATCH_BYTES = 2_000_000
MAX_DIFF_CHARS = 40_000
