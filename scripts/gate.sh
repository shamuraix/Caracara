#!/usr/bin/env bash
# The policy gate.  Fails on any fixable HIGH/CRITICAL CVE (OS packages and
# Java jars) or an end-of-life base OS, and produces the artefacts the sign
# stage attests: vuln.json (cosign-vuln) and sbom.cdx.json (CycloneDX).
#
# Usage: scripts/gate.sh <image-ref>
# Exit: 0 clean, 1 fixable CVEs, 2 base OS EOL (also opens a GitLab issue when
# GITLAB_ISSUE_TOKEN is set).
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
need trivy

image="${1:?image}"

# Time-boxed exceptions only: refuse to run with an ignore file that has
# entries without expiry, or past it.
python3 scripts/check_trivyignore.py "${TRIVYIGNORE}"

log "gate: ${image} (severity ${SEVERITY}, fixable only, EOL check)"
set +e
trivy_gate "${image}"
rc=$?
set -e

case "${rc}" in
  0) log "gate passed: no fixable ${SEVERITY} CVEs, base OS supported" ;;
  "${EXIT_EOL}")
    log "gate FAILED: base OS is end-of-life; rebuild on a newer base"
    scripts/open-gitlab-issue.sh "Base OS EOL: ${image}" \
      "Trivy reported the base OS of \`${image}\` as end-of-life (exit ${EXIT_EOL}). Bump the base image in the Dockerfile FROM line; see docs/base-image-strategy.md." || true
    exit "${EXIT_EOL}" ;;
  "${EXIT_VULN}")
    log "gate FAILED: fixable ${SEVERITY} CVEs present (OS: run patch; Java: bump the Atlassian version)"
    exit "${EXIT_VULN}" ;;
  *) die "trivy exited ${rc}" ;;
esac

log "writing vulnerability record and SBOM"
trivy image --format cosign-vuln --ignorefile "${TRIVYIGNORE}" -o "${OUT_DIR}/vuln.json" "${image}"
trivy image --format cyclonedx -o "${OUT_DIR}/sbom.cdx.json" "${image}"
# Informational: what is still there but not fixable upstream (tracked, not gated).
trivy image --pkg-types os --severity "${SEVERITY}" --ignore-status fixed \
  --format json -o "${OUT_DIR}/unfixed.json" "${image}" || true
log "unfixed ${SEVERITY} OS findings (will_not_fix/fix_deferred/affected): $(jq '[.Results[]?.Vulnerabilities // [] | length] | add // 0' "${OUT_DIR}/unfixed.json")"
