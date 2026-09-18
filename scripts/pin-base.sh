#!/usr/bin/env bash
# Pin (or re-pin) the base image digest in a Dockerfile's first FROM line.
# Renovate does this continuously; this script is the manual/bootstrap path.
#
# Usage: scripts/pin-base.sh <product|ci-tools> [image:tag]
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
need crane

dir="${1:?product dir}"
dockerfile="${dir}/Dockerfile"
[ -f "${dockerfile}" ] || die "${dockerfile} not found"

line="$(grep -En '^FROM \$\{ART\}/docker-redhat-remote/' "${dockerfile}" | head -n1)"
[ -n "${line}" ] || die "no UBI FROM line found in ${dockerfile}"
lineno="${line%%:*}"
current="$(echo "${line#*:}" | awk '{print $2}')"
image_tag="${2:-${current%%@*}}"
resolved="${image_tag/\$\{ART\}/${ART}}"

digest="$(crane digest "${resolved}")"
[[ "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || die "could not resolve ${resolved}"

new="FROM ${image_tag%%@*}@${digest}"
rest="$(echo "${line#*:}" | cut -d' ' -f3-)"
sed -i "${lineno}s|.*|${new} ${rest}|" "${dockerfile}"
log "pinned ${dockerfile}: ${new} ${rest}"
