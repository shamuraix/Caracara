#!/usr/bin/env bash
# Sign an image digest, attach the vulnerability and SBOM attestations, and
# move the mutable tags to it (promotion): the version tag, plus every tag in
# EXTRA_TAGS (the line tag `lts`, space separated).
#
# Usage: scripts/sign.sh <repo/name@sha256:...> <version-tag> [vuln.json] [sbom.cdx.json]
# Keyless (GitLab OIDC, SIGSTORE_ID_TOKEN) when COSIGN_KEY is unset, key-based otherwise.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
need cosign crane

ref="${1:?image@digest}"
version="${2:?version tag}"
vuln="${3:-${OUT_DIR}/vuln.json}"
sbom="${4:-${OUT_DIR}/sbom.cdx.json}"
[[ "${ref}" == *@sha256:* ]] || die "sign by digest, not tag: ${ref}"

log "signing ${ref}"
cosign sign "${COSIGN_ARGS[@]}" "${ref}"
if [ -s "${vuln}" ]; then
  cosign attest "${COSIGN_ARGS[@]}" --type vuln --predicate "${vuln}" "${ref}"
fi
if [ -s "${sbom}" ]; then
  cosign attest "${COSIGN_ARGS[@]}" --type cyclonedx --predicate "${sbom}" "${ref}"
fi

name="${ref%%@*}"
for t in "${version}" ${EXTRA_TAGS:-}; do
  log "promoting: ${name}:${t} -> ${ref#*@}"
  crane tag "${ref}" "${t}"
done
