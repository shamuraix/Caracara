#!/usr/bin/env bash
# Pin (or re-pin) resources in <dir>/hardening_manifest.yaml: downloads each
# named resource through the Artifactory generic remote (DOWNLOAD_DIRECT=true
# to go upstream), computes its sha256 and writes it back.  When the upstream
# publishes a checksum file next to the artefact (<file>.sha256, .sha256sum,
# or kernel.org's sha256sums.asc) it is fetched too and must agree.
#
# Usage: scripts/pin-resource.sh <product>/<line>|ci-tools <ARG> [<ARG> ...]
#        scripts/pin-resource.sh <dir> --all
#        scripts/pin-resource.sh <dir> <ARG> --url <new-url>   (bump and pin)
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
need curl sha256sum python3

dir="${1:?dir}"; shift
[ -f "${dir}/hardening_manifest.yaml" ] || die "${dir}/hardening_manifest.yaml not found"
direct=()
[ "${DOWNLOAD_DIRECT:-false}" = "true" ] && direct=(--direct)

new_url=""
args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --url) new_url="$2"; shift 2 ;;
    --all) mapfile -t args < <(python3 - "${dir}" <<'PY'
import sys, yaml
sys.path.insert(0, "scripts")
import manifest
_, doc = manifest.load(sys.argv[1])
print("\n".join(manifest.resource_arg(r) for r in doc["resources"]))
PY
); shift ;;
    *) args+=("$1"); shift ;;
  esac
done
[ "${#args[@]}" -gt 0 ] || die "name at least one resource ARG (or --all)"
[ -z "${new_url}" ] || [ "${#args[@]}" -eq 1 ] || die "--url applies to exactly one resource"

tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"' EXIT

published_sha() {
  # Try the common sidecar checksum conventions; print the sha or nothing.
  local url="$1" name="$2" out
  for cand in "${url}.sha256" "${url}.sha256sum" "${url}.sha256.txt"; do
    if out="$(curl -fsSL --max-time 30 "${cand}" 2>/dev/null)"; then
      awk -v n="${name}" '$1 ~ /^[0-9a-f]{64}$/ && (NF==1 || index($0, n)) {print $1; exit}' <<<"${out}"; return
    fi
  done
  if [[ "${url}" == */pub/software/scm/git/* ]]; then
    if out="$(curl -fsSL --max-time 30 "${url%/*}/sha256sums.asc" 2>/dev/null)"; then
      awk -v n="${name}" '$2 == n {print $1; exit}' <<<"${out}"; return
    fi
  fi
}

for arg in "${args[@]}"; do
  if [ -n "${new_url}" ]; then
    python3 scripts/manifest.py set-resource "${dir}" "${arg}" --url "${new_url}" --sha256 "" >/dev/null
  fi
  url="$(python3 scripts/manifest.py url "${dir}" "${arg}" --art "${ART}" "${direct[@]}")"
  name="${url##*/}"
  log "fetching ${url}"
  curl -fsSL --retry 3 -o "${tmp}/${name}" "${url}"
  sha="$(sha256sum "${tmp}/${name}" | awk '{print $1}')"
  pub="$(published_sha "${url}" "${name}" || true)"
  if [ -n "${pub}" ] && [ "${pub}" != "${sha}" ]; then
    die "${arg}: downloaded sha256 ${sha} != published ${pub}"
  fi
  [ -n "${pub}" ] && log "${arg}: matches the published checksum"
  python3 scripts/manifest.py set-resource "${dir}" "${arg}" --sha256 "${sha}"
  rm -f "${tmp:?}/${name}"
done
