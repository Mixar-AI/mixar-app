#!/bin/bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Shared body of the upstream/-submodule re-pin hooks.
#
# `git checkout` moves HEAD but not submodule working trees, and neither does
# `git merge` / `git pull`. Different branches here pin different Blender
# releases (5.0 vs 5.2), so a stale upstream/ silently overlays Mixar's sources
# onto the wrong Blender and `make build` fails in confusing ways (a 5.0
# upstream under a 5.2 branch dies at `find_package(fmt)`; a stale build cache
# dies with "At least Python 3.13 is required ... found Python 3.11").
#
# lib/* inside upstream is additionally configured `update = none` in
# upstream/.gitmodules, so plain `git submodule update --recursive` never
# touches it either - it needs its own explicit checkout.
#
# Usage: sync_upstream_pin <hook-name> <prev-head> <new-head>
#   <prev-head> may be empty; it is only used for the BLENDER_VERSION warning.

sync_upstream_pin() {
    local hook="$1"
    local prev_head="${2:-}"
    local new_head="${3:-HEAD}"

    # Nothing to do on a fresh clone before `make init` has run.
    git submodule status -- upstream 2>/dev/null | grep -q '^-' && return 0

    local expected_upstream actual_upstream
    expected_upstream="$(git rev-parse "HEAD:upstream" 2>/dev/null || true)"
    [[ -n "$expected_upstream" ]] || return 0
    actual_upstream="$(git -C upstream rev-parse HEAD 2>/dev/null || true)"

    if [[ "$actual_upstream" != "$expected_upstream" ]]; then
        echo "$hook: re-pinning upstream/ to ${expected_upstream:0:12}"
        git -C upstream checkout -f --detach "$expected_upstream"
    fi

    # Only re-pin lib/* submodules that are already initialized on this machine
    # (each platform only checks out its own lib/<platform>).
    local line lib_path expected_lib actual_lib
    while read -r line; do
        [[ "$line" == -* ]] && continue
        lib_path="$(awk '{print $2}' <<< "$line")"
        expected_lib="$(git -C upstream rev-parse "HEAD:$lib_path" 2>/dev/null || true)"
        [[ -n "$expected_lib" ]] || continue
        actual_lib="$(git -C "upstream/$lib_path" rev-parse HEAD 2>/dev/null || true)"
        if [[ "$actual_lib" != "$expected_lib" ]]; then
            echo "$hook: re-pinning upstream/$lib_path to ${expected_lib:0:12}"
            git -C "upstream/$lib_path" checkout -f "$expected_lib"
        fi
    done < <(git -C upstream submodule status -- lib 2>/dev/null)

    # build/ and source/ (the overlaid CMake tree) are shared across branches
    # and cannot be reused across a Blender major-version change - warn instead
    # of letting the next `make build` fail confusingly mid-configure/compile.
    [[ -n "$prev_head" ]] || return 0
    local prev_version new_version
    prev_version="$(git show "$prev_head:scripts/unix/settings.sh" 2>/dev/null | grep -m1 'BLENDER_VERSION' || true)"
    new_version="$(git show "$new_head:scripts/unix/settings.sh" 2>/dev/null | grep -m1 'BLENDER_VERSION' || true)"
    if [[ -n "$prev_version" && -n "$new_version" && "$prev_version" != "$new_version" ]]; then
        echo "$hook: BLENDER_VERSION pin changed."
        echo "$hook: run 'make clean_build' before 'make build' - build/ and source/ are shared across branches and can't mix Blender versions."
    fi
}
