#!/usr/bin/env bash
# Pin an Atlassian product version in <product>/hardening_manifest.yaml:
# sets args.VERSION and tags[0], points the PRODUCT resource at the new
# tarball and stores its sha256 from the vendor's published .sha256 file
# (fetched through the Artifactory generic remote; DOWNLOAD_DIRECT=true to go
# to product-downloads.atlassian.com).  The tarball itself is not downloaded.
# Renovate runs this as a postUpgradeTask.
#
# Usage: scripts/pin-version.sh <jira|confluence|bitbucket> <version>
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
need curl python3

product="${1:?product}"
version="${2:?version}"
case "${product}" in
  jira)       path="software/jira/downloads" ;;
  confluence) path="software/confluence/downloads" ;;
  bitbucket)  path="software/stash/downloads" ;;
  *) die "unknown product ${product}" ;;
esac
[[ "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must be X.Y.Z, got ${version}"
artefact="$(python3 scripts/manifest.py arg "${product}" ARTEFACT)"

upstream="https://product-downloads.atlassian.com/${path}/${artefact}-${version}.tar.gz"
if [ "${DOWNLOAD_DIRECT:-false}" = "true" ]; then
  sha_url="${upstream}.sha256"
else
  sha_url="https://${ART}/artifactory/generic-atlassian-remote/${path}/${artefact}-${version}.tar.gz.sha256"
fi

log "fetching ${sha_url}"
# The vendor file is "<sha256>  <filename>" (sha256sum format).
sha="$(curl -fsSL "${sha_url}" | awk 'NR==1 {print $1}')"
[[ "${sha}" =~ ^[0-9a-f]{64}$ ]] || die "no sha256 found at ${sha_url} (does ${artefact} ${version} exist?)"

python3 scripts/manifest.py set-arg "${product}" VERSION "${version}"
python3 scripts/manifest.py set-resource "${product}" PRODUCT --url "${upstream}" --sha256 "${sha}"
python3 - "${product}" "${version}" <<'PY'
import sys
sys.path.insert(0, "scripts")
import manifest
path, doc = manifest.load(sys.argv[1])
tags = [t for t in doc.get("tags", []) if t != "latest"]
doc["tags"] = [sys.argv[2]] + [t for t in tags if t != sys.argv[2]][:2] + ["latest"]
manifest.save(path, doc)
PY
log "pinned ${product} ${version} sha256:${sha}"
