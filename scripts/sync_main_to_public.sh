#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

#
# sync_main_to_public.sh — advance the public repo's main branch to the
# already-mirrored content of the released branch, instead of mirroring
# private main commit-by-commit.
#
# Why main can't use sync_commit_mirror.sh
# ----------------------------------------
# Private main only ever receives develop→main release PRs, landed as merge
# commits. sync_commit_mirror.sh walks --first-parent, so ONE first-parent
# commit on main is AN ENTIRE RELEASE — dozens of PRs squashed into a single
# public snapshot commit titled "Merge pull request #1065 from
# Mixar-AI/develop". Public main was ten such commits, all by the same merger.
# No amount of message rewriting fixes that: the granularity simply isn't
# there.
#
# What this does instead
# ----------------------
# The released content is develop, and develop is ALREADY mirrored commit by
# commit. So: find the public mirror of the merged-in branch tip, and join it
# onto public main.
#
#   * public main missing            → create it at the mirrored commit.
#   * public main already an ancestor → fast-forward (no new commit).
#   * otherwise                       → a real merge commit with two parents
#     (current public main, mirrored release commit) whose TREE is the
#     mirrored release tree. Non-destructive: nothing on public main is
#     rewritten or force-pushed, and from this point on `git log main` shows
#     every granular develop commit.
#
# The merge commit carries the "Private-SHA: <private main sha>" trailer, so
# sync_tag_to_public.sh keeps resolving release tags.
#
# Usage:
#   sync_main_to_public.sh [--branch main] [--dry-run]
#
# Env:
#   PUBLIC_REPO_PATH   path to the public repo clone (default: ../mixar-app)

set -euo pipefail

BRANCH="main"
DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --branch)   BRANCH="${2:?--branch requires a name}"; shift 2 ;;
        --branch=*) BRANCH="${1#--branch=}"; shift ;;
        --dry-run)  DRY_RUN=true; shift ;;
        -h|--help)
            sed -n '2,/^set -euo pipefail$/p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "ERROR: unknown arg: $1" >&2; exit 1 ;;
    esac
done

PRIVATE_ROOT="$(git rev-parse --show-toplevel)"
PUBLIC_ROOT="${PUBLIC_REPO_PATH:-${PRIVATE_ROOT}/../mixar-app}"
SANITIZED_BRANCH="${BRANCH//\//-}"
STATE_REF="refs/sync-state/${SANITIZED_BRANCH}"
MAX_WALK=300

echo "─── sync_main_to_public ───"
echo "  branch:   $BRANCH"
echo "  private:  $PRIVATE_ROOT"
echo "  public:   $PUBLIC_ROOT"
echo "  dry-run:  $DRY_RUN"
echo ""

# ----------------------------------------------------------------------------
# Pre-flight
# ----------------------------------------------------------------------------
if [[ ! -d "$PUBLIC_ROOT/.git" ]]; then
    echo "ERROR: public repo not a git repository: $PUBLIC_ROOT" >&2
    exit 1
fi

if ! PRIVATE_TIP=$(cd "$PRIVATE_ROOT" && git rev-parse --verify "refs/heads/${BRANCH}" 2>/dev/null); then
    echo "ERROR: private repo has no '${BRANCH}' branch." >&2
    exit 1
fi
echo "  private $BRANCH → $PRIVATE_TIP"

# ----------------------------------------------------------------------------
# Locate the public mirror of the released content.
#
# Prefer the merge's SECOND parent (the branch that was released — develop or
# release/vX). That is exactly the content main now holds, and its commits are
# the ones already mirrored granularly. Fall back to main's full ancestry so a
# non-merge tip (e.g. a hotfix committed straight onto main) still resolves.
# ----------------------------------------------------------------------------
find_public_mirror() {
    local start="$1" candidate mirror
    while IFS= read -r candidate; do
        [[ -z "$candidate" ]] && continue
        mirror=$(cd "$PUBLIC_ROOT" && \
            git log --all --format=%H --grep="^Private-SHA: ${candidate}\$" -1 2>/dev/null || true)
        if [[ -n "$mirror" ]]; then
            echo "${candidate} ${mirror}"
            return 0
        fi
    done < <(cd "$PRIVATE_ROOT" && git rev-list -n "$MAX_WALK" "$start")
    return 1
}

RESULT=""
if MERGED_TIP=$(cd "$PRIVATE_ROOT" && git rev-parse -q --verify "${PRIVATE_TIP}^2" 2>/dev/null); then
    echo "  released branch tip (second parent) → $MERGED_TIP"
    RESULT=$(find_public_mirror "$MERGED_TIP" || true)
fi
if [[ -z "$RESULT" ]]; then
    echo "  falling back to full ${BRANCH} ancestry..."
    RESULT=$(find_public_mirror "$PRIVATE_TIP" || true)
fi

if [[ -z "$RESULT" ]]; then
    echo "ERROR: no ancestor of '$BRANCH' has a public mirror." >&2
    echo "" >&2
    echo "The released branch has not been mirrored yet. Sync it first:" >&2
    echo "  ./scripts/sync_commit_mirror.sh --branch develop" >&2
    exit 1
fi

ANCHOR_PRIVATE="${RESULT%% *}"
PUBLIC_SRC="${RESULT##* }"
echo "  public source = $PUBLIC_SRC (mirror of private $ANCHOR_PRIVATE)"

# ----------------------------------------------------------------------------
# Join it onto public main.
# ----------------------------------------------------------------------------
advance_state() {
    $DRY_RUN && return 0
    (cd "$PRIVATE_ROOT" && git update-ref "$STATE_REF" "$PRIVATE_TIP")
}

# `git branch -f` refuses to move a branch that is the public clone's checked-out
# HEAD — and main IS the default branch of a fresh mixar-app clone. Detach first.
# The workflow already detaches; this makes a local run work too.
if ! $DRY_RUN && [[ "$(cd "$PUBLIC_ROOT" && git symbolic-ref -q --short HEAD || true)" == "$BRANCH" ]]; then
    echo "  public HEAD is on '$BRANCH' — detaching so the branch can be moved"
    (cd "$PUBLIC_ROOT" && git checkout -q --detach)
fi

if ! PUBLIC_TIP=$(cd "$PUBLIC_ROOT" && git rev-parse --verify "refs/heads/${BRANCH}" 2>/dev/null); then
    echo "  public '$BRANCH' does not exist — creating it at $PUBLIC_SRC"
    $DRY_RUN || (cd "$PUBLIC_ROOT" && git branch -f "$BRANCH" "$PUBLIC_SRC")
    advance_state
    echo "Done (branch created)."
    exit 0
fi

if [[ "$PUBLIC_TIP" == "$PUBLIC_SRC" ]]; then
    echo "  public '$BRANCH' already at $PUBLIC_SRC — nothing to do."
    advance_state
    exit 0
fi

if (cd "$PUBLIC_ROOT" && git merge-base --is-ancestor "$PUBLIC_TIP" "$PUBLIC_SRC"); then
    echo "  fast-forwarding public '$BRANCH' $PUBLIC_TIP → $PUBLIC_SRC"
    $DRY_RUN || (cd "$PUBLIC_ROOT" && git branch -f "$BRANCH" "$PUBLIC_SRC")
    advance_state
    echo "Done (fast-forward)."
    exit 0
fi

# Divergent: build a merge commit that takes the released tree wholesale.
# `git commit-tree` is used rather than `git merge` because we never want a
# content merge here — public main's tree must equal the mirrored release
# tree exactly, byte for byte.
SUBJECT=$(cd "$PRIVATE_ROOT" && git log -1 --format='%s' "$PRIVATE_TIP")
MERGER_NAME=$(cd "$PRIVATE_ROOT" && git log -1 --format='%cn' "$PRIVATE_TIP")
MERGER_EMAIL=$(cd "$PRIVATE_ROOT" && git log -1 --format='%ce' "$PRIVATE_TIP")
MERGE_DATE=$(cd "$PRIVATE_ROOT" && git log -1 --format='%cI' "$PRIVATE_TIP")
TREE=$(cd "$PUBLIC_ROOT" && git rev-parse "${PUBLIC_SRC}^{tree}")

MSG=$(printf '%s\n\nRelease merge: public %s now carries the full granular\nhistory of the released branch (mirrored at %s).\n\nPrivate-SHA: %s\n' \
    "$SUBJECT" "$BRANCH" "${PUBLIC_SRC:0:12}" "$PRIVATE_TIP")

if $DRY_RUN; then
    echo ""
    echo "Dry-run: would create a merge commit on public '$BRANCH'"
    echo "  parents: $PUBLIC_TIP (current $BRANCH), $PUBLIC_SRC (release)"
    echo "  tree:    $TREE"
    echo "  message:"
    printf '%s\n' "$MSG" | sed 's/^/    /'
    exit 0
fi

NEW_COMMIT=$(cd "$PUBLIC_ROOT" && \
    GIT_AUTHOR_NAME="$MERGER_NAME" \
    GIT_AUTHOR_EMAIL="$MERGER_EMAIL" \
    GIT_AUTHOR_DATE="$MERGE_DATE" \
    GIT_COMMITTER_NAME="$MERGER_NAME" \
    GIT_COMMITTER_EMAIL="$MERGER_EMAIL" \
    GIT_COMMITTER_DATE="$MERGE_DATE" \
    git commit-tree "$TREE" -p "$PUBLIC_TIP" -p "$PUBLIC_SRC" -m "$MSG")

(cd "$PUBLIC_ROOT" && git branch -f "$BRANCH" "$NEW_COMMIT")
advance_state

echo "  created merge commit $NEW_COMMIT on public '$BRANCH'"
echo ""
echo "Next steps:"
echo "  Public:  cd $PUBLIC_ROOT && git push origin $BRANCH"
echo "  Private: git push origin $STATE_REF"
