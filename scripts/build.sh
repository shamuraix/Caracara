#!/usr/bin/env bash
# Build one product image with buildctl against the shared buildkitd, push it
# to Artifactory with SBOM + provenance attestations, and write build.env
# (TAG, VERSION, DIGEST) for the following stages.
#
# Usage: scripts/build.sh <product|ci-tools> [tag-suffix]
#   tag-suffix defaults to $CI_PIPELINE_IID, $BUILD_NUMBER or a timestamp.
# Build args come from <product>/hardening_manifest.yaml (args + one
# <ARG>_URL/<ARG>_SHA256 pair per resource); the build refuses to start while
# any resource is unpinned.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
need buildctl jq

product="${1:?product}"
suffix="${2:-${CI_PIPELINE_IID:-${BUILD_NUMBER:-$(date -u +%Y%m%d%H%M%S)}}}"
manifest_check "${product}"
if [ "${product}" = "ci-tools" ]; then
  version="$(date -u +%Y%m%d)"
else
  version="$(product_version "${product}")"
fi
tag="${REPO}/${product}:${version}-${suffix}"
meta="${OUT_DIR}/meta-${product}.json"
mapfile -t build_args < <(manifest_build_args "${product}")

if ! grep -Eq '^FROM .*@sha256:[0-9a-f]{64}' "${product}/Dockerfile"; then
  log "WARNING: ${product}/Dockerfile FROM line is not digest-pinned yet (Renovate pins it on its first run)"
fi

log "building ${tag} (platforms: ${PLATFORMS})"
buildctl "${BKTLS[@]}" build --frontend dockerfile.v0 \
  --local context=. --local dockerfile="${product}" \
  --opt "build-arg:ART=${ART}" \
  "${build_args[@]}" \
  --opt "platform=${PLATFORMS}" \
  --opt attest:sbom= --opt attest:provenance=mode=max \
  --import-cache "type=registry,ref=${REPO}/cache/${product}" \
  --export-cache "type=registry,ref=${REPO}/cache/${product},mode=max" \
  --output "type=image,\"name=${tag}\",push=true,oci-mediatypes=true" \
  --metadata-file "${meta}"

digest="$(jq -r '."containerimage.digest"' "${meta}")"
[[ "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || die "no digest in ${meta}"

{
  echo "PRODUCT=${product}"
  echo "TAG=${tag}"
  echo "VERSION=${version}"
  echo "DIGEST=${digest}"
} > "${OUT_DIR}/build.env"
log "built ${tag} @ ${digest}"
