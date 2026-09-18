#!/usr/bin/env bash
# Collect a series of JVM thread dumps for Atlassian support.
# Usage: thread-dumps.sh [count] [interval-seconds] [output-dir]
# Uses jcmd when the JDK is present, otherwise SIGQUIT (dump goes to the
# product's catalina.out / launcher log).
set -euo pipefail

count="${1:-10}"
interval="${2:-5}"
outdir="${3:-${ATL_SUPPORT_DIR:-/tmp/atlassian-support}}"
mkdir -p "${outdir}"

pid="$(pgrep -f 'org.apache.catalina.startup.Bootstrap|bitbucket' | head -n1 || true)"
if [ -z "${pid}" ]; then
  echo "no JVM process found" >&2
  exit 1
fi

for i in $(seq 1 "${count}"); do
  ts="$(date +%Y%m%d-%H%M%S)"
  if command -v jcmd >/dev/null 2>&1; then
    jcmd "${pid}" Thread.print > "${outdir}/thread-dump-${ts}-${i}.txt"
  else
    kill -3 "${pid}"
    echo "SIGQUIT sent to ${pid}; dump ${i}/${count} written to the JVM stdout log" > "${outdir}/thread-dump-${ts}-${i}.txt"
  fi
  if command -v top >/dev/null 2>&1; then
    top -b -n 1 -H -p "${pid}" > "${outdir}/top-${ts}-${i}.txt" || true
  fi
  [ "${i}" -lt "${count}" ] && sleep "${interval}"
done
echo "thread dumps written to ${outdir}"
