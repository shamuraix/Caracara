#!/usr/bin/env bash
# Commit the given files on a branch, push it and open (or update) a GitLab
# merge request.  No-op with a warning when GITLAB_SYNC_TOKEN is missing, so
# the calling job still succeeds with the in-workspace change.
#
# Usage: scripts/open-gitlab-mr.sh <branch> <title> <description> -- <file>...
# Env:   GITLAB_SYNC_TOKEN (project token: api, write_repository),
#        CI_API_V4_URL, CI_PROJECT_ID, CI_SERVER_HOST, CI_PROJECT_PATH,
#        CI_DEFAULT_BRANCH (all set by GitLab CI; set by hand on Jenkins).
set -euo pipefail
branch="${1:?branch}"; title="${2:?title}"; description="${3:-}"; shift 3
[ "${1:-}" = "--" ] && shift
files=("$@")
[ "${#files[@]}" -gt 0 ] || { echo "open-gitlab-mr: no files" >&2; exit 1; }

for v in GITLAB_SYNC_TOKEN CI_API_V4_URL CI_PROJECT_ID CI_SERVER_HOST CI_PROJECT_PATH; do
  if [ -z "${!v:-}" ]; then
    echo "open-gitlab-mr: ${v} not set; changes stay in this workspace only (would open: ${title})" >&2
    exit 0
  fi
done
target="${CI_DEFAULT_BRANCH:-main}"
remote="https://oauth2:${GITLAB_SYNC_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git"

git config user.name "${GIT_AUTHOR_NAME:-image-pipeline}"
git config user.email "${GIT_AUTHOR_EMAIL:-image-pipeline@example.com}"
git checkout -B "${branch}"
git add -- "${files[@]}"
if git diff --cached --quiet; then
  echo "open-gitlab-mr: nothing to commit" >&2
  exit 0
fi
git commit -q -m "${title}"
git push -f -o merge_request.create -o "merge_request.target=${target}" -o "merge_request.title=${title}" \
  -o "merge_request.description=${description}" -o merge_request.remove_source_branch \
  "${remote}" "HEAD:refs/heads/${branch}" 2>&1 | sed 's/oauth2:[^@]*@/oauth2:***@/'

# Push options create the MR when absent; make sure one exists and is labelled.
api="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/merge_requests"
hdr=(-H "PRIVATE-TOKEN: ${GITLAB_SYNC_TOKEN}")
iid="$(curl -fsS "${hdr[@]}" --get "${api}" --data-urlencode "source_branch=${branch}" --data-urlencode "state=opened" | jq -r '.[0].iid // empty')"
if [ -z "${iid}" ]; then
  iid="$(curl -fsS "${hdr[@]}" -X POST "${api}" --data-urlencode "source_branch=${branch}" --data-urlencode "target_branch=${target}" \
    --data-urlencode "title=${title}" --data-urlencode "description=${description}" --data-urlencode "remove_source_branch=true" | jq -r '.iid')"
fi
curl -fsS "${hdr[@]}" -X PUT "${api}/${iid}" --data-urlencode "labels=ironbank-sync,image-hygiene" >/dev/null
echo "open-gitlab-mr: !${iid} ${title}" >&2
