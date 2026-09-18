#!/usr/bin/env bash
# Daily fast path: scan a live tag, patch fixable OS CVEs with Copa on the
# shared buildkitd, re-gate, then move the tag and sign.  Exits 0 without
# doing anything when the image is already clean.
#
# Usage: scripts/patch.sh <name:tag>   e.g. jira:11.3.11
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
need trivy copa crane cosign jq

image="${1:?name:tag}"
name="${image%%:*}"
ver="${image#*:}"
ref="${REPO}/${image}"
patched_tag="${ver}-patched"
report="${OUT_DIR}/report-${name}.json"

log "scanning ${ref} for fixable OS package CVEs"
trivy image --pkg-types os --ignore-unfixed --ignorefile "${TRIVYIGNORE}" -f json -o "${report}" "${ref}"
count="$(jq '[.Results[]?.Vulnerabilities // [] | length] | add // 0' "${report}")"
if [ "${count}" = "0" ]; then
  log "${ref} is clean; nothing to patch"
  exit 0
fi
log "${count} fixable OS finding(s); patching with copa"

copa patch "${COPA_BK[@]}" -i "${ref}" -r "${report}" -t "${patched_tag}" \
  --platform "${PLATFORMS}" --push

log "re-gating ${REPO}/${name}:${patched_tag}"
scripts/gate.sh "${REPO}/${name}:${patched_tag}"

digest="$(crane digest "${REPO}/${name}:${patched_tag}")"
scripts/sign.sh "${REPO}/${name}@${digest}" "${ver}"
# Keep the immutable build tag history readable: <ver>-<pipeline>-patched-<date>.
crane tag "${REPO}/${name}@${digest}" "${ver}-patched-$(date -u +%Y%m%d)"
log "patched ${ref} -> ${digest}"
