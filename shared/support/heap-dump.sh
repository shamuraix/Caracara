#!/usr/bin/env bash
# Write a JVM heap dump for Atlassian support.
# Usage: heap-dump.sh [output-file]
# Requires jcmd (java-*-openjdk-devel).  Without it, set
# JVM_SUPPORT_RECOMMENDED_ARGS="-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=<home>" instead.
set -euo pipefail

out="${1:-${ATL_SUPPORT_DIR:-/tmp/atlassian-support}/heap-$(date +%Y%m%d-%H%M%S).hprof}"
mkdir -p "$(dirname "${out}")"

pid="$(pgrep -f 'org.apache.catalina.startup.Bootstrap|bitbucket' | head -n1 || true)"
if [ -z "${pid}" ]; then
  echo "no JVM process found" >&2
  exit 1
fi
if ! command -v jcmd >/dev/null 2>&1; then
  echo "jcmd not available in this image; install java-*-openjdk-devel or use -XX:+HeapDumpOnOutOfMemoryError" >&2
  exit 2
fi
jcmd "${pid}" GC.heap_dump "${out}"
echo "heap dump written to ${out}"
