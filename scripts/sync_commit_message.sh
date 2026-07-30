#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

#
# sync_commit_message.sh — commit-message synthesis helpers for
# sync_commit_mirror.sh. This file is SOURCED, never executed.
#
# Why this exists
# ---------------
# The private repo lands PRs as MERGE COMMITS, and sync_commit_mirror.sh walks
# --first-parent. An entire PR therefore collapses into ONE public commit whose
# message is the content-free
#
#     Merge pull request #1050 from Mixar-AI/task/1040-implement-adding-rules
#
# and whose author is whoever clicked the Merge button. The public mirror's
# history said nothing about the work and credited none of the people who did
# it — everything looked authored by the merger.
#
# For a "Merge pull request #N" commit we rebuild the message from the PR's own
# commits (the merge's second-parent range) and re-attribute the public commit
# to whoever wrote most of them. The merger is preserved as the committer, so
# no information is lost — it is just recorded in the right field.
#
# Result, for the example above:
#
#     Rules: project + global rules for the agent (#1050)
#
#     * Rules: extract rules_api — shared mutation surface (Chirag Singh)
#     * Rules: global scope — rules for every .mixar file (Chirag Singh)
#     * Rules composer: mouse drag selection (Chirag Singh)
#
#     Private-SHA: adb20072...
#
# Deliberately NOT synthesized:
#   - back-merges ("Merge branch 'develop' into feature/x") — their
#     second-parent range is all of develop, which would produce a bogus
#     hundred-line bullet list.
#   - merges whose second-parent range is empty after --no-merges.
# Both keep their original message.

# Max bullets listed before the tail is summarised. A PR with more commits
# than this is rare; the cap keeps the public log readable either way.
SM_MAX_BULLETS="${SM_MAX_BULLETS:-60}"

# Memo of PR number → title, so a re-run over many commits makes at most one
# API call per PR. Newline separated "<pr><TAB><title>".
_SM_PR_TITLES=""

# ---------------------------------------------------------------------------
# sm_pr_number <private_root> <sha>
#   Echoes the PR number if <sha> is a "Merge pull request #N" commit.
#   Returns 1 otherwise.
# ---------------------------------------------------------------------------
sm_pr_number() {
    local subj
    subj=$(cd "$1" && git log -1 --format='%s' "$2")
    if [[ "$subj" =~ ^Merge\ pull\ request\ \#([0-9]+)( |$) ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi
    return 1
}

# ---------------------------------------------------------------------------
# sm_source_branch <private_root> <sha>
#   "Merge pull request #1050 from Mixar-AI/task/1040-add-rules"
#     → "Mixar-AI/task/1040-add-rules"
# ---------------------------------------------------------------------------
sm_source_branch() {
    local subj
    subj=$(cd "$1" && git log -1 --format='%s' "$2")
    case "$subj" in
        *" from "*) echo "${subj##* from }" ;;
        *)          echo "" ;;
    esac
}

# ---------------------------------------------------------------------------
# sm_humanize_branch <branch>
#   Fallback subject when the PR title can't be fetched.
#   "Mixar-AI/task/1040-implement-adding-rules-for-users"
#     → "Implement adding rules for users"
# ---------------------------------------------------------------------------
sm_humanize_branch() {
    local b="$1" head
    # Drop the owner prefix ("Mixar-AI/") when the name is owner-qualified.
    case "$b" in Mixar-AI/*) b="${b#*/}" ;; esac
    # Drop a leading branch-type segment (task/, feature/, bugfix/, ...) but
    # only when something survives it — "develop" must stay "develop".
    head="${b%%/*}"
    case "$head" in
        task|feature|bugfix|fix|chore|hotfix|release|refactor|docs)
            [[ "$b" == */* ]] && b="${b#*/}"
            ;;
    esac
    # Drop a leading issue number ("1040-").
    b="${b#[0-9]*-}"
    # Separators → spaces, then sentence-case.
    b=$(echo "$b" | tr '_-' '  ' | tr -s ' ')
    b="$(echo "${b:0:1}" | tr '[:lower:]' '[:upper:]')${b:1}"
    echo "$b"
}

# ---------------------------------------------------------------------------
# sm_pr_title <pr_number>
#   Fetches the PR title from the GitHub API. Needs GITHUB_REPOSITORY plus a
#   token in SM_GH_TOKEN / GH_TOKEN / GITHUB_TOKEN with pull-requests:read.
#   Returns 1 (silently) when unavailable — callers fall back to the branch
#   name, so a missing token degrades the message, never the sync.
# ---------------------------------------------------------------------------
sm_pr_title() {
    local pr="$1" repo="${GITHUB_REPOSITORY:-}" token title cached
    token="${SM_GH_TOKEN:-${GH_TOKEN:-${GITHUB_TOKEN:-}}}"

    cached=$(printf '%s\n' "$_SM_PR_TITLES" | grep -m1 "^${pr}	" || true)
    if [[ -n "$cached" ]]; then
        title="${cached#*	}"
        [[ -n "$title" ]] || return 1
        echo "$title"
        return 0
    fi

    title=""
    if [[ -n "$repo" && -n "$token" ]]; then
        title=$(curl -sf --max-time 15 \
            -H "Authorization: Bearer ${token}" \
            -H "Accept: application/vnd.github+json" \
            "https://api.github.com/repos/${repo}/pulls/${pr}" 2>/dev/null \
            | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("title", "").strip())
except Exception:
    pass' 2>/dev/null) || title=""
    fi

    # Memoise both hits and misses — a miss must not be retried per commit.
    _SM_PR_TITLES="${_SM_PR_TITLES}
${pr}	${title}"

    [[ -n "$title" ]] || return 1
    echo "$title"
}

# ---------------------------------------------------------------------------
# sm_side_commits <private_root> <sha>
#   The PR's own commits: everything reachable from the merged branch but not
#   from the mainline. Back-merges of develop into the feature branch are
#   already excluded by the range, and --no-merges drops the back-merge
#   commits themselves.
# ---------------------------------------------------------------------------
sm_side_commits() {
    (cd "$1" && git log --no-merges --format='%s	%an' "${2}^1..${2}^2" 2>/dev/null)
}

# ---------------------------------------------------------------------------
# sm_majority_author <private_root> <sha>
#   "<name><TAB><email>" of whoever wrote the most commits in the PR.
#   Empty when the range is empty.
# ---------------------------------------------------------------------------
sm_majority_author() {
    (cd "$1" && git log --no-merges --format='%an	%ae' "${2}^1..${2}^2" 2>/dev/null) \
        | sort | uniq -c | sort -rn | head -1 | sed 's/^ *[0-9]*  *//'
}

# ---------------------------------------------------------------------------
# sm_build_message <private_root> <sha>
#   Prints the synthesized message (WITHOUT the Private-SHA trailer, which the
#   caller appends). Returns 1 when this commit should keep its original
#   message.
# ---------------------------------------------------------------------------
sm_build_message() {
    local root="$1" sha="$2" pr branch subject bullets count

    pr=$(sm_pr_number "$root" "$sha") || return 1

    bullets=$(sm_side_commits "$root" "$sha")
    [[ -n "$bullets" ]] || return 1
    count=$(printf '%s\n' "$bullets" | wc -l | tr -d ' ')

    branch=$(sm_source_branch "$root" "$sha")
    if ! subject=$(sm_pr_title "$pr"); then
        subject=$(sm_humanize_branch "$branch")
    fi
    [[ -n "$subject" ]] || subject="Merge pull request"

    printf '%s (#%s)\n\n' "$subject" "$pr"
    printf '%s\n' "$bullets" | head -n "$SM_MAX_BULLETS" \
        | sed 's/^\(.*\)	\(.*\)$/* \1 (\2)/'
    if [[ "$count" -gt "$SM_MAX_BULLETS" ]]; then
        printf '* ... and %s more commit(s)\n' "$((count - SM_MAX_BULLETS))"
    fi
    [[ -n "$branch" ]] && printf '\nSource-Branch: %s\n' "$branch"
    return 0
}
