#!/usr/bin/env bash
# Pull each LTS line's version and checksums from its Iron Bank upstream git
# repository: a shallow clone of the `development` branch of
# https://repo1.dso.mil/dsop/atlassian/<product>-data-center/<product>-lts.git
# (Iron Bank Containers / Atlassian / <Product> Data Center / <product>-lts),
# as named under `upstream.ironbank` in <product>/lts/hardening_manifest.yaml.
#
# Usage: scripts/sync-ironbank.sh <product>/lts [...] | --all  [--open-mr] [--check]
#   --open-mr  when anything changed, commit on a sync/ironbank-<date> branch,
#              push with GITLAB_SYNC_TOKEN (api + write_repository) and open
#              or update a merge request so git catches up with what the
#              rebuild just built.
#   --check    exit 3 instead of 0 when something changed (drift report).
# Env:
#   IRONBANK_GIT_BASE   rewrite https://repo1.dso.mil/ to a mirror base, e.g.
#                       https://gitlab.example.com/mirrors/ (GitLab pull
#                       mirrors of the Iron Bank projects) when runners have
#                       no egress to repo1.dso.mil.
#   IRONBANK_GIT_TOKEN  repo1 (or mirror) token for private groups; sent as
#                       an oauth2 basic credential on the clone only.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
need git python3

base_args=()
[ -n "${IRONBANK_GIT_BASE:-}" ] && base_args=(--base "${IRONBANK_GIT_BASE}")
open_mr=false; check=false; targets=()
while [ $# -gt 0 ]; do
  case "$1" in
    --all) for p in ${PRODUCTS}; do for l in ${LINES}; do [ -f "${p}/${l}/hardening_manifest.yaml" ] && targets+=("${p}/${l}"); done; done; shift ;;
    --open-mr) open_mr=true; shift ;;
    --check) check=true; shift ;;
    *) targets+=("$1"); shift ;;
  esac
done
[ "${#targets[@]}" -gt 0 ] || die "name at least one <product>/lts (or --all)"

tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"' EXIT
git_auth=()
if [ -n "${IRONBANK_GIT_TOKEN:-}" ]; then
  git_auth=(-c "http.extraHeader=Authorization: Basic $(printf 'oauth2:%s' "${IRONBANK_GIT_TOKEN}" | base64 -w0)")
fi
changed=()
for target in "${targets[@]}"; do
  product_dir "${target}" >/dev/null
  read -r repo ref file < <(python3 scripts/ironbank.py repo "${target}" "${base_args[@]}")
  dest="${tmp}/${target//\//-}"
  log "${target}: cloning ${repo}@${ref}"
  GIT_TERMINAL_PROMPT=0 git "${git_auth[@]}" clone -q --depth 1 --branch "${ref}" --single-branch "${repo}" "${dest}" \
    || die "${target}: cannot clone ${repo} (branch ${ref}); check egress to repo1.dso.mil, IRONBANK_GIT_BASE or IRONBANK_GIT_TOKEN"
  [ -f "${dest}/${file}" ] || die "${target}: ${file} not found in ${repo}@${ref}"
  log "${target}: ${repo}@${ref} is at $(git -C "${dest}" rev-parse --short HEAD)"
  out="$(python3 scripts/ironbank.py apply "${target}" "${dest}/${file}")"
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
