#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

#
# sync_main_to_public.sh — advance the public repo's main branch to the
# public version of private main, reusing the already-mirrored granular
# history of the released branch instead of mirroring main commit-by-commit.
#
# Why main can't use sync_commit_mirror.sh
# ----------------------------------------
# Private main only ever receives PRs landed as merge commits (develop →
# main releases, and the odd bugfix/* straight to main). sync_commit_mirror.sh
# walks --first-parent, so ONE first-parent commit on main is AN ENTIRE
# RELEASE — dozens of PRs squashed into one public snapshot commit.
#
# What this does instead
# ----------------------
# The released branch (the merge's second parent, usually develop) is already
# mirrored commit by commit. Find the public mirror of its tip and join it
# onto public main. Public main must end up holding EXACTLY the public version
# of private main (sync_public_lib.sh: spl_exact_diff), so:
#
#   * public main already holds it      → nothing to do (safe to re-run).
#   * released tip's mirror is exact:
#       - public main missing           → create it there.
#       - public main is an ancestor    → fast-forward.
#       - public main already contains it but its content drifted
#                                       → one commit on public main
#         restoring the mirror's tree.
#       - otherwise                     → a merge commit (public main,
#         mirror) whose tree is the mirror's tree.
#   * no exact mirror (the released branch is never mirrored, e.g. a
#     bugfix/* PR straight to main, or its mirror lags) → a merge commit
#     whose tree is private main mirrored directly, through the same
#     .publicignore copy and leak tripwires as sync_commit_mirror.sh.
#
# Nothing on public main is ever rewritten or force-pushed. Every commit this
# creates carries "Private-SHA: <private main sha>", and its message passes
# the same leak tripwire as every mirrored commit.
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

# shellcheck source=scripts/sync_public_lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sync_public_lib.sh"

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

PUBLIC_TIP=$(cd "$PUBLIC_ROOT" && git rev-parse -q --verify "refs/heads/${BRANCH}" 2>/dev/null || true)
echo "  public  $BRANCH → ${PUBLIC_TIP:-<missing>}"

advance_state() {
    $DRY_RUN && return 0
    (cd "$PRIVATE_ROOT" && git update-ref "$STATE_REF" "$PRIVATE_TIP")
}

# ----------------------------------------------------------------------------
# Re-run guard: public main already holds exactly this release. Covers a
# re-run after a failed state-ref push, which used to stack a duplicate merge.
# ----------------------------------------------------------------------------
if [[ -n "$PUBLIC_TIP" ]] \
    && [[ -n "$(cd "$PUBLIC_ROOT" && git log -1 --format=%H --grep="^Private-SHA: ${PRIVATE_TIP}\$" "$PUBLIC_TIP")" ]] \
    && spl_is_exact "$PRIVATE_TIP" "$PUBLIC_TIP"; then
    echo "  public '$BRANCH' already holds private $PRIVATE_TIP — nothing to do."
    advance_state
    exit 0
fi

# ----------------------------------------------------------------------------
# Locate the released branch's public mirror and prove it is exact.
# ----------------------------------------------------------------------------
RELEASED_TIP=$(spl_released_tip "$PRIVATE_TIP")
echo "  released tip → $RELEASED_TIP"

PUBLIC_SRC=""
if ANCHOR=$(spl_find_anchor "$RELEASED_TIP"); then
    ANCHOR_PRIVATE="${ANCHOR%% *}"
    ANCHOR_PUBLIC="${ANCHOR##* }"
    for c in $(spl_mirrors_of "$ANCHOR_PRIVATE"); do
        echo "  nearest mirror: public $c (private $ANCHOR_PRIVATE)"
        DIFF=$(spl_exact_diff "$PRIVATE_TIP" "$c") || exit 1
        if [[ -z "$DIFF" ]]; then
            PUBLIC_SRC="$c"
            echo "  ✓ it holds exactly private $BRANCH's public content"
            break
        fi
        echo "  ✗ it differs from private $BRANCH's public content:"
        printf '%s\n' "$DIFF" | sed -n '1,20p' | sed 's/^/      /'
    done
else
    ANCHOR_PUBLIC=""
    echo "  no mirrored commit on the released branch"
fi

# ----------------------------------------------------------------------------
# Join an exact mirror onto public main.
# ----------------------------------------------------------------------------
SUBJECT=$(cd "$PRIVATE_ROOT" && git log -1 --format='%s' "$PRIVATE_TIP")
MERGER_NAME=$(cd "$PRIVATE_ROOT" && git log -1 --format='%cn' "$PRIVATE_TIP")
MERGER_EMAIL=$(cd "$PRIVATE_ROOT" && git log -1 --format='%ce' "$PRIVATE_TIP")
MERGE_DATE=$(cd "$PRIVATE_ROOT" && git log -1 --format='%cI' "$PRIVATE_TIP")

# commit_on_public <tree> <message> <parent>... → new public commit sha
commit_on_public() {
    local tree="$1" msg="$2" args=() p
    shift 2
    for p in "$@"; do args+=(-p "$p"); done
    (cd "$PUBLIC_ROOT" && \
        GIT_AUTHOR_NAME="$MERGER_NAME" GIT_AUTHOR_EMAIL="$MERGER_EMAIL" \
        GIT_AUTHOR_DATE="$MERGE_DATE" GIT_COMMITTER_NAME="$MERGER_NAME" \
        GIT_COMMITTER_EMAIL="$MERGER_EMAIL" GIT_COMMITTER_DATE="$MERGE_DATE" \
        git commit-tree "$tree" "${args[@]}" -m "$msg")
}

# tripwire_or_exit <message> — the final public message, before committing.
tripwire_or_exit() {
    if ! spl_tripwire_message "$1" "public $BRANCH commit"; then
        echo "Aborting: rewrite private $BRANCH's merge message (PR title) before retrying." >&2
        exit 2
    fi
}

move_public_branch() {
    if $DRY_RUN; then
        echo "  [dry-run] would move public '$BRANCH' → $1"
        return 0
    fi
    # `git branch -f` refuses to move the checked-out branch; detach first.
    if [[ "$(cd "$PUBLIC_ROOT" && git symbolic-ref -q --short HEAD || true)" == "$BRANCH" ]]; then
        (cd "$PUBLIC_ROOT" && git checkout -q --detach)
    fi
    (cd "$PUBLIC_ROOT" && git branch -f "$BRANCH" "$1")
}

if [[ -n "$PUBLIC_SRC" ]]; then
    if [[ -z "$PUBLIC_TIP" ]]; then
        echo "  public '$BRANCH' does not exist — creating it at $PUBLIC_SRC"
        move_public_branch "$PUBLIC_SRC"
    elif (cd "$PUBLIC_ROOT" && git merge-base --is-ancestor "$PUBLIC_SRC" "$PUBLIC_TIP") \
        && [[ "$(spl_tree "$PUBLIC_ROOT" "$PUBLIC_TIP")" == "$(spl_tree "$PUBLIC_ROOT" "$PUBLIC_SRC")" ]]; then
        echo "  public '$BRANCH' already contains $PUBLIC_SRC with the same content — nothing to do."
    elif (cd "$PUBLIC_ROOT" && git merge-base --is-ancestor "$PUBLIC_TIP" "$PUBLIC_SRC"); then
        echo "  fast-forwarding public '$BRANCH' $PUBLIC_TIP → $PUBLIC_SRC"
        move_public_branch "$PUBLIC_SRC"
    else
        if (cd "$PUBLIC_ROOT" && git merge-base --is-ancestor "$PUBLIC_SRC" "$PUBLIC_TIP"); then
            # Already in public main's history, but the content drifted after
            # it: restore the release's tree. A second parent would be redundant.
            KIND="commit"
            PARENTS=("$PUBLIC_TIP")
            MSG=$(printf '%s\n\nRelease: public %s restored to the released content\n(mirrored at %s).\n\nPrivate-SHA: %s\n' \
                "$SUBJECT" "$BRANCH" "${PUBLIC_SRC:0:12}" "$PRIVATE_TIP")
        else
            KIND="merge"
            PARENTS=("$PUBLIC_TIP" "$PUBLIC_SRC")
            MSG=$(printf '%s\n\nRelease merge: public %s now carries the full granular\nhistory of the released branch (mirrored at %s).\n\nPrivate-SHA: %s\n' \
                "$SUBJECT" "$BRANCH" "${PUBLIC_SRC:0:12}" "$PRIVATE_TIP")
        fi
        tripwire_or_exit "$MSG"
        if $DRY_RUN; then
            echo "  [dry-run] would create a $KIND on public '$BRANCH'"
            echo "            parents: ${PARENTS[*]}"
        else
            NEW=$(commit_on_public "$(spl_tree "$PUBLIC_ROOT" "$PUBLIC_SRC")" "$MSG" "${PARENTS[@]}")
            move_public_branch "$NEW"
            echo "  created $KIND $NEW on public '$BRANCH'"
        fi
    fi
    advance_state
    echo "Done."
    exit 0
fi

# ----------------------------------------------------------------------------
# No exact mirror: mirror private main directly onto public main.
# ----------------------------------------------------------------------------
if [[ -z "$PUBLIC_TIP" ]]; then
    echo "ERROR: public '$BRANCH' does not exist and no mirrored commit holds its content." >&2
    echo "Sync the released branch first (Sync to public, ref = develop), then re-run." >&2
    exit 1
fi

echo "  mirroring private $BRANCH directly (released branch has no exact public mirror)"

TMP=$(spl_worktree_open "$PUBLIC_TIP") || exit 1
spl_on_exit 'spl_worktree_close "$TMP"'
spl_extract "$PRIVATE_TIP" "$TMP/src"
spl_sync_and_stage "$TMP/src" "$PRIVATE_TIP" "$TMP/wt"
if ! spl_tripwire_staged "$TMP/wt" "private $BRANCH tip"; then
    echo "Aborting: add the file to .publicignore or remove the secret before retrying." >&2
    exit 2
fi
echo "  changes against public '$BRANCH':"
(cd "$TMP/wt" && git diff --cached --name-status "$PUBLIC_TIP") | sed -n '1,40p' | sed 's/^/      /'
TREE=$(cd "$TMP/wt" && git write-tree)

PARENTS=("$PUBLIC_TIP")
# Still join the released branch's granular history when its mirror is new.
if [[ -n "$ANCHOR_PUBLIC" ]] && \
    ! (cd "$PUBLIC_ROOT" && git merge-base --is-ancestor "$ANCHOR_PUBLIC" "$PUBLIC_TIP"); then
    PARENTS+=("$ANCHOR_PUBLIC")
fi
MSG=$(printf '%s\n\nRelease merge: public %s mirrored directly from private %s\n(the released branch has no exact public mirror).\n\nPrivate-SHA: %s\n' \
    "$SUBJECT" "$BRANCH" "$BRANCH" "$PRIVATE_TIP")
tripwire_or_exit "$MSG"

if $DRY_RUN; then
    echo "  [dry-run] would create a commit on public '$BRANCH' with parents: ${PARENTS[*]}"
    spl_success_exit
fi
NEW=$(commit_on_public "$TREE" "$MSG" "${PARENTS[@]}")
move_public_branch "$NEW"
advance_state
echo "  created commit $NEW on public '$BRANCH'"
echo "Done."
spl_success_exit
