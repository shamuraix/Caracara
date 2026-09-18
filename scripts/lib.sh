#!/usr/bin/env bash
# Shared settings for the pipeline scripts.  Source it; do not execute it.
# Every value can be overridden from the CI environment.

# shellcheck disable=SC2034  # variables are consumed by the sourcing scripts
: "${ART:=artifactory.example.com}"
: "${REPO:=${ART}/docker-atlassian-local}"
: "${BUILDKIT_HOST:=tcp://buildkitd.buildkit.svc:1234}"
: "${BUILDKIT_CERTS:=/certs}"
: "${PLATFORMS:=linux/amd64,linux/arm64}"
: "${SEVERITY:=HIGH,CRITICAL}"
: "${TRIVYIGNORE:=.trivyignore.yaml}"
: "${TRIVY_DB_REPOSITORY:=${ART}/docker-ghcr-remote/aquasecurity/trivy-db}"
: "${TRIVY_JAVA_DB_REPOSITORY:=${ART}/docker-ghcr-remote/aquasecurity/trivy-java-db}"
: "${PRODUCTS:=jira confluence bitbucket}"
: "${OUT_DIR:=.}"
export ART REPO BUILDKIT_HOST TRIVY_DB_REPOSITORY TRIVY_JAVA_DB_REPOSITORY

# Trivy exit codes used by gate.sh: 1 = fixable findings, 2 = base OS is end-of-life.
EXIT_VULN=1
EXIT_EOL=2

# mTLS flags for buildctl and copa (client certs mounted from buildkit-client-certs).
BKTLS=(--tlscacert "${BUILDKIT_CERTS}/ca.pem" --tlscert "${BUILDKIT_CERTS}/cert.pem" --tlskey "${BUILDKIT_CERTS}/key.pem")
COPA_BK=(--addr "${BUILDKIT_HOST}" --cacert "${BUILDKIT_CERTS}/ca.pem" --cert "${BUILDKIT_CERTS}/cert.pem" --key "${BUILDKIT_CERTS}/key.pem")
if [ ! -f "${BUILDKIT_CERTS}/ca.pem" ]; then
  # Plain TCP (only acceptable for a local buildkitd on a developer machine).
  BKTLS=()
  COPA_BK=(--addr "${BUILDKIT_HOST}")
fi

# Signing: keyless (SIGSTORE_ID_TOKEN from GitLab OIDC) or a key file (Jenkins).
COSIGN_ARGS=(--yes)
if [ -n "${COSIGN_KEY:-}" ]; then
  COSIGN_ARGS+=(--key "${COSIGN_KEY}")
fi

log()  { printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${0##*/}" "$*" >&2; }
die()  { log "ERROR: $*"; exit 1; }
need() { for t in "$@"; do command -v "$t" >/dev/null 2>&1 || die "missing tool: $t"; done; }

product_dir() {
  local product="$1"
  [ -d "${product}" ] || die "unknown product directory: ${product}"
  echo "${product}"
}

# Reads $product/VERSION (single line, semver-ish).
product_version() {
  local product="$1"
  tr -d '[:space:]' < "$(product_dir "${product}")/VERSION"
}

# Reads $product/SHA256; fails loudly when it is missing so builds stay pinned.
product_sha256() {
  local product="$1" f
  f="$(product_dir "${product}")/SHA256"
  [ -s "${f}" ] || die "${f} is missing: run scripts/pin-version.sh ${product} $(product_version "${product}")"
  local sha
  sha="$(tr -d '[:space:]' < "${f}")"
  [[ "${sha}" =~ ^[0-9a-f]{64}$ ]] || die "${f} does not contain a sha256 hex digest"
  echo "${sha}"
}

# Renders the trivy gate command; exit 1 on fixable HIGH/CRITICAL, 2 on EOL OS.
trivy_gate() {
  local image="$1"; shift
  local vex=()
  # Optional OpenVEX/CSAF statements (Red Hat CSAF VEX, Iron Bank justifications).
  if [ -n "${TRIVY_VEX:-}" ]; then
    [ -f "${TRIVY_VEX}" ] || die "TRIVY_VEX=${TRIVY_VEX} does not exist"
    vex=(--vex "${TRIVY_VEX}" --show-suppressed)
  fi
  trivy image --ignore-unfixed --severity "${SEVERITY}" \
    --exit-code "${EXIT_VULN}" --exit-on-eol "${EXIT_EOL}" \
    --ignorefile "${TRIVYIGNORE}" "${vex[@]}" "$@" "${image}"
}
