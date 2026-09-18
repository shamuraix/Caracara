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
#   IRONBANK_FETCH        vcs (default in CI): read the branch through an
#                         Artifactory VCS remote that fronts repo1.dso.mil;
#                         git: shallow-clone the repository directly.
#   IRONBANK_VCS_REPO     Artifactory VCS remote repo key (default vcs-ironbank-remote).
#   IRONBANK_VCS_TEMPLATE override the REST URL template (see ironbank.py);
#                         a template without {file} must return a tar.gz
#                         branch archive (downloadBranch), which is unpacked.
#   IRONBANK_VCS_ARCHIVE  true: use the archive API instead of downloadBranchFile.
#   Artifactory credentials for vcs mode come from ~/.docker/config.json
#   (the ART_DOCKER_CONFIG the runner already has) or ARTIFACTORY_TOKEN.
#   IRONBANK_GIT_BASE     git mode: rewrite https://repo1.dso.mil/ to a mirror base.
#   IRONBANK_GIT_TOKEN    git mode: repo1 (or mirror) token for private groups.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
need python3 curl tar

: "${IRONBANK_FETCH:=vcs}"
: "${IRONBANK_VCS_REPO:=vcs-ironbank-remote}"
base_args=()
[ -n "${IRONBANK_GIT_BASE:-}" ] && base_args=(--base "${IRONBANK_GIT_BASE}")
vcs_args=(--art "${ART}" --vcs-repo "${IRONBANK_VCS_REPO}")
[ -n "${IRONBANK_VCS_TEMPLATE:-}" ] && vcs_args+=(--template "${IRONBANK_VCS_TEMPLATE}")
[ "${IRONBANK_VCS_ARCHIVE:-false}" = "true" ] && vcs_args+=(--archive)

# curl auth for Artifactory: the docker config the runner already holds, or a bearer token.
art_curl_auth() {
  local cfg="${DOCKER_CONFIG:-${HOME}/.docker}/config.json" auth
  if [ -n "${ARTIFACTORY_TOKEN:-}" ]; then
    printf -- '-H\nAuthorization: Bearer %s\n' "${ARTIFACTORY_TOKEN}"
  elif [ -f "${cfg}" ] && auth="$(jq -r --arg h "${ART}" '.auths[$h].auth // .auths["https://\($h)"].auth // empty' "${cfg}" 2>/dev/null)" && [ -n "${auth}" ]; then
    printf -- '-u\n%s\n' "$(printf '%s' "${auth}" | base64 -d)"
  fi
}

# Fetch the upstream manifest for a target into $2 (a file path).
fetch_manifest() {
  local target="$1" dest="$2" repo ref file url
  read -r repo ref file < <(python3 scripts/ironbank.py repo "${target}" "${base_args[@]}")
  case "${IRONBANK_FETCH}" in
    vcs)
      need jq
      url="$(python3 scripts/ironbank.py vcs-url "${target}" "${vcs_args[@]}")"
      mapfile -t auth < <(art_curl_auth)
      log "${target}: ${repo}@${ref} via Artifactory VCS remote ${IRONBANK_VCS_REPO}"
      if [[ "${url}" == *"!"* ]] || [[ "${IRONBANK_VCS_TEMPLATE:-}" == *"{file}"* ]]; then
        curl -fsSL --retry 3 "${auth[@]}" -o "${dest}" "${url}" \
          || die "${target}: cannot fetch ${url} (VCS remote key, provider download URL, or Artifactory credentials?)"
      else
        curl -fsSL --retry 3 "${auth[@]}" -o "${dest}.tar.gz" "${url}" \
          || die "${target}: cannot fetch ${url} (VCS remote key, provider download URL, or Artifactory credentials?)"
        tar -xzf "${dest}.tar.gz" -O --wildcards "*/${file}" > "${dest}" 2>/dev/null \
          || tar -xzf "${dest}.tar.gz" -O "${file}" > "${dest}" \
          || die "${target}: ${file} not found in the branch archive"
      fi
      ;;
    git)
      need git
      local git_auth=() clone="${dest}.clone"
      if [ -n "${IRONBANK_GIT_TOKEN:-}" ]; then
        git_auth=(-c "http.extraHeader=Authorization: Basic $(printf 'oauth2:%s' "${IRONBANK_GIT_TOKEN}" | base64 -w0)")
      fi
      log "${target}: cloning ${repo}@${ref}"
      GIT_TERMINAL_PROMPT=0 git "${git_auth[@]}" clone -q --depth 1 --branch "${ref}" --single-branch "${repo}" "${clone}" \
        || die "${target}: cannot clone ${repo} (branch ${ref}); check egress to repo1.dso.mil, IRONBANK_GIT_BASE or IRONBANK_GIT_TOKEN"
      [ -f "${clone}/${file}" ] || die "${target}: ${file} not found in ${repo}@${ref}"
      log "${target}: ${repo}@${ref} is at $(git -C "${clone}" rev-parse --short HEAD)"
      cp "${clone}/${file}" "${dest}"
      ;;
    *) die "IRONBANK_FETCH must be vcs or git, got ${IRONBANK_FETCH}" ;;
  esac
}
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
changed=()
for target in "${targets[@]}"; do
  product_dir "${target}" >/dev/null
  dest="${tmp}/${target//\//-}.yaml"
  fetch_manifest "${target}" "${dest}"
  out="$(python3 scripts/ironbank.py apply "${target}" "${dest}")"
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
