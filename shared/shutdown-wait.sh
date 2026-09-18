#!/usr/bin/env bash
# Graceful shutdown helper, meant to be used as a Kubernetes preStop hook or
# with `docker exec <container> /shutdown-wait.sh`.  Runs the product's stop
# script and waits (up to ATL_SHUTDOWN_TIMEOUT seconds, default 120) for the
# JVM to exit so the pod is not SIGKILLed mid-flight.
set -euo pipefail

timeout="${ATL_SHUTDOWN_TIMEOUT:-120}"

if [ -n "${JIRA_INSTALL_DIR:-}" ]; then
  stop_script="${JIRA_INSTALL_DIR}/bin/stop-jira.sh"
  proc_match="${JIRA_INSTALL_DIR}"
elif [ -n "${CONFLUENCE_INSTALL_DIR:-}" ]; then
  stop_script="${CONFLUENCE_INSTALL_DIR}/bin/stop-confluence.sh"
  proc_match="${CONFLUENCE_INSTALL_DIR}"
elif [ -n "${BITBUCKET_INSTALL_DIR:-}" ]; then
  stop_script="${BITBUCKET_INSTALL_DIR}/bin/stop-bitbucket.sh"
  proc_match="${BITBUCKET_INSTALL_DIR}"
else
  echo "shutdown-wait: no *_INSTALL_DIR variable set; nothing to stop" >&2
  exit 1
fi

echo "shutdown-wait: running ${stop_script}"
"${stop_script}" || true

for _ in $(seq 1 "${timeout}"); do
  if ! pgrep -f "${proc_match}" >/dev/null 2>&1; then
    echo "shutdown-wait: product stopped"
    exit 0
  fi
  sleep 1
done

echo "shutdown-wait: product still running after ${timeout}s" >&2
exit 1
