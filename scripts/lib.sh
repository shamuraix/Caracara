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

# A build target is "<product>/<line>" (jira/lts, confluence/latest, ...) or
# "ci-tools".  Each target directory holds a hardening_manifest.yaml; the
# product directory holds the Dockerfile shared by its lines.
: "${LINES:=lts latest}"

product_dir() {
  local target="$1"
  [ -f "${target}/hardening_manifest.yaml" ] || die "unknown build target ${target} (expected <product>/<lts|latest> or ci-tools)"
  echo "${target}"
}

target_product() { echo "${1%%/*}"; }
target_line()    { [[ "$1" == */* ]] && echo "${1#*/}" || echo "latest"; }
target_dockerfile_dir() { echo "${1%%/*}"; }

# Product version: args.VERSION in <target>/hardening_manifest.yaml.
product_version() {
  python3 "$(dirname "${BASH_SOURCE[0]}")/manifest.py" version "$(product_dir "$1")"
}

# Refuse to build with unpinned resources (empty sha256 in the manifest).
manifest_check() {
  python3 "$(dirname "${BASH_SOURCE[0]}")/manifest.py" check "$(product_dir "$1")" >&2 \
    || die "pin every resource in $1/hardening_manifest.yaml first"
}

# `--opt=build-arg:K=V` lines for buildctl, with upstream URLs rewritten to Artifactory.
manifest_build_args() {
  python3 "$(dirname "${BASH_SOURCE[0]}")/manifest.py" build-args "$(product_dir "$1")" --art "${ART}"
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
