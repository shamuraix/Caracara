#!/usr/bin/env bash
# Pull each line's version and checksums from its Iron Bank upstream project
# (the `development` branch of Iron Bank Containers / Atlassian / <Product>
# Data Center / <product>-lts, or the non-LTS project for `latest`), as named
# under `upstream.ironbank` in <product>/<line>/hardening_manifest.yaml.
#
# Usage: scripts/sync-ironbank.sh <product>/<line> [...] | --all  [--open-mr]
#   --open-mr  when anything changed, commit on a sync/ironbank-<date> branch,
#              push with GITLAB_SYNC_TOKEN (api + write_repository) and open
#              or update a merge request so git catches up with what the
#              rebuild just built.
# Exit 0 (changed or not); 3 when --check is given and something changed.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
need curl python3

direct=()
[ "${DOWNLOAD_DIRECT:-false}" = "true" ] && direct=(--direct)
open_mr=false; check=false; targets=()
while [ $# -gt 0 ]; do
  case "$1" in
    --all) for p in ${PRODUCTS}; do for l in ${LINES}; do [ -f "${p}/${l}/hardening_manifest.yaml" ] && targets+=("${p}/${l}"); done; done; shift ;;
    --open-mr) open_mr=true; shift ;;
    --check) check=true; shift ;;
    *) targets+=("$1"); shift ;;
  esac
done
[ "${#targets[@]}" -gt 0 ] || die "name at least one <product>/<line> (or --all)"

tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"' EXIT
changed=()
for target in "${targets[@]}"; do
  product_dir "${target}" >/dev/null
  url="$(python3 scripts/ironbank.py url "${target}" --art "${ART}" "${direct[@]}")"
  log "${target}: fetching ${url}"
  curl -fsSL --retry 3 -o "${tmp}/ib.yaml" "${url}" || die "${target}: cannot fetch the Iron Bank manifest (project/ref right? registry1 token on generic-repo1-remote?)"
  out="$(python3 scripts/ironbank.py apply "${target}" "${tmp}/ib.yaml")"
  echo "${out}" >&2
  [[ "${out}" == changed* ]] && changed+=("${target}")
done

if [ "${#changed[@]}" -eq 0 ]; then
  log "all lines already match their Iron Bank development branch"
  exit 0
fi
log "synced from Iron Bank: ${changed[*]}"
[ "${check}" = true ] && exit 3

if [ "${open_mr}" = true ]; then
  scripts/open-gitlab-mr.sh "sync/ironbank-$(date -u +%Y%m%d)" \
    "chore: sync ${changed[*]} from Iron Bank development" \
    "Versions and checksums pulled from each line's Iron Bank upstream project (\`upstream.ironbank\` in the manifests) by the scheduled rebuild. Changed: ${changed[*]}" \
    -- "${changed[@]/%//hardening_manifest.yaml}"
fi
