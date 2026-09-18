#!/usr/bin/env bash
# Pin an Atlassian product version: writes <product>/VERSION and <product>/SHA256
# from the vendor's published .sha256 file, fetched through the Artifactory
# generic remote (or directly from product-downloads.atlassian.com with
# DOWNLOAD_DIRECT=true).  Renovate runs this as a postUpgradeTask.
#
# Usage: scripts/pin-version.sh <jira|confluence|bitbucket> <version> [artefact]
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
need curl

product="${1:?product}"
version="${2:?version}"
case "${product}" in
  jira)       path="software/jira/downloads";       artefact="${3:-atlassian-jira-software}" ;;
  confluence) path="software/confluence/downloads"; artefact="${3:-atlassian-confluence}" ;;
  bitbucket)  path="software/stash/downloads";      artefact="${3:-atlassian-bitbucket}" ;;
  *) die "unknown product ${product}" ;;
esac
[[ "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must be X.Y.Z, got ${version}"

if [ "${DOWNLOAD_DIRECT:-false}" = "true" ]; then
  base="https://product-downloads.atlassian.com/${path}"
else
  base="https://${ART}/artifactory/generic-atlassian-remote/${path}"
fi
url="${base}/${artefact}-${version}.tar.gz.sha256"

log "fetching ${url}"
# The vendor file is "<sha256>  <filename>" (sha256sum format).
sha="$(curl -fsSL "${url}" | awk 'NR==1 {print $1}')"
[[ "${sha}" =~ ^[0-9a-f]{64}$ ]] || die "no sha256 found at ${url} (does ${artefact} ${version} exist?)"

echo "${version}" > "${product}/VERSION"
echo "${sha}" > "${product}/SHA256"
# Keep the Dockerfile default in sync so local builds without CI args work too.
sed -i -E "s/^ARG VERSION=.*/ARG VERSION=${version}/" "${product}/Dockerfile"
log "pinned ${product} ${version} sha256:${sha}"
