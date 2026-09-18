#!/usr/bin/env bash
# Open (or comment on) a GitLab issue from CI.  No-op with a warning when the
# token is not configured, so the calling job's exit code is still the gate's.
#
# Usage: scripts/open-gitlab-issue.sh <title> <description>
# Env:   GITLAB_ISSUE_TOKEN (project access token with `api` scope),
#        CI_API_V4_URL, CI_PROJECT_ID (set by GitLab CI; set them by hand on Jenkins).
set -euo pipefail
title="${1:?title}"
description="${2:-}"

if [ -z "${GITLAB_ISSUE_TOKEN:-}" ] || [ -z "${CI_API_V4_URL:-}" ] || [ -z "${CI_PROJECT_ID:-}" ]; then
  echo "open-gitlab-issue: GITLAB_ISSUE_TOKEN/CI_API_V4_URL/CI_PROJECT_ID not set; would have opened: ${title}" >&2
  exit 0
fi

api="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/issues"
hdr=(-H "PRIVATE-TOKEN: ${GITLAB_ISSUE_TOKEN}")
label="${GITLAB_ISSUE_LABEL:-image-hygiene}"

# Reuse an open issue with the same title to avoid a ticket per scheduled run.
existing="$(curl -fsS "${hdr[@]}" --get "${api}" --data-urlencode "search=${title}" --data-urlencode "state=opened" --data-urlencode "in=title" | jq -r '.[0].iid // empty')"
if [ -n "${existing}" ]; then
  curl -fsS "${hdr[@]}" -X POST "${api}/${existing}/notes" --data-urlencode "body=Still failing on $(date -u +%F): ${CI_JOB_URL:-${BUILD_URL:-no job url}}" >/dev/null
  echo "open-gitlab-issue: commented on existing issue #${existing}" >&2
  exit 0
fi

curl -fsS "${hdr[@]}" -X POST "${api}" \
  --data-urlencode "title=${title}" \
  --data-urlencode "description=${description}

Job: ${CI_JOB_URL:-${BUILD_URL:-n/a}}" \
  --data-urlencode "labels=${label}" | jq -r '"open-gitlab-issue: created #\(.iid) \(.web_url)"' >&2
