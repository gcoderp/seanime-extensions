#!/usr/bin/env bash
# Commits the given paths and pushes, surviving a concurrent writer.
#
# Why this exists: every workflow that produces artifacts pushes to main. When two of them
# overlap -- a heal run and convert's publish job, for example -- the second push is rejected
# with "Updates were rejected because the remote contains work that you do not have locally",
# and the whole job fails *after* doing all its work. The commit is then discarded and the
# artifacts are lost.
#
# So: commit, then push; on rejection, rebase onto the remote and try again, a few times.
#
# Usage:
#   bash scripts/commit-and-push.sh "commit message" [path ...]
#
# Environment:
#   GITHUB_REF_NAME   branch to push to (default: main)
#   PUSH_RETRIES      attempts before giving up (default: 5)

set -euo pipefail

MESSAGE="${1:-}"
if [ -z "$MESSAGE" ]; then
    echo "usage: commit-and-push.sh \"commit message\" [path ...]" >&2
    exit 2
fi
shift

BRANCH="${GITHUB_REF_NAME:-main}"
RETRIES="${PUSH_RETRIES:-5}"

git config user.name "${GIT_AUTHOR_NAME:-seanime-bot[bot]}"
git config user.email "${GIT_AUTHOR_EMAIL:-seanime-bot@users.noreply.github.com}"

if [ "$#" -gt 0 ]; then
    # `git add` fails if any pathspec does not exist, and generated paths come and go
    # (config/license-cache.json, manifest-urls.txt), so keep only the ones present.
    existing=()
    for path in "$@"; do
        [ -e "$path" ] && existing+=("$path")
    done
    if [ "${#existing[@]}" -gt 0 ]; then
        git add -A "${existing[@]}"
    else
        git add -A
    fi
else
    git add -A
fi

if git diff --cached --quiet; then
    echo "Nothing to commit: the working tree already matches the repository."
    exit 0
fi

git commit -m "$MESSAGE"

for attempt in $(seq 1 "$RETRIES"); do
    if git push origin "HEAD:${BRANCH}"; then
        echo "Pushed to ${BRANCH}."
        exit 0
    fi

    echo "Push rejected (attempt ${attempt}/${RETRIES}) -- another writer got there first."
    echo "Rebasing onto origin/${BRANCH} and retrying."

    if ! git pull --rebase --autostash origin "$BRANCH"; then
        echo "" >&2
        echo "Rebase failed: the remote changed files this job also rewrote, and git could" >&2
        echo "not reconcile them automatically. Nothing was pushed." >&2
        echo "Resolve locally with 'git pull --rebase origin ${BRANCH}', or re-run the" >&2
        echo "workflow once the other run has finished." >&2
        exit 1
    fi

    sleep $(( attempt * 3 ))
done

echo "Could not push after ${RETRIES} attempts." >&2
exit 1
