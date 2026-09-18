#!/usr/bin/env bash
# Local/CI lint: shell, YAML, Dockerfiles (when hadolint is present), the
# ignore file, support windows and the Python unit tests.
set -euo pipefail
cd "$(dirname "$0")/.."
rc=0

echo "== python dependencies"
if ! python3 -c "import yaml, jinja2" 2>/dev/null; then
  echo "missing PyYAML and/or Jinja2: python3 -m pip install -r requirements-dev.txt (or: make deps)" >&2
  exit 1
fi

if command -v shellcheck >/dev/null 2>&1; then
  echo "== shellcheck"
  shellcheck -x scripts/*.sh shared/*.sh shared/support/*.sh || rc=1
else
  echo "== shellcheck: not installed, skipped (pip install shellcheck-py)"; [ "${CI:-}" = "true" ] && rc=1
fi

if command -v yamllint >/dev/null 2>&1; then
  echo "== yamllint"
  yamllint -c .yamllint.yaml . || rc=1
else
  echo "== yamllint: not installed, skipped (pip install yamllint)"; [ "${CI:-}" = "true" ] && rc=1
fi

if command -v hadolint >/dev/null 2>&1; then
  echo "== hadolint"
  hadolint --config .hadolint.yaml jira/Dockerfile confluence/Dockerfile bitbucket/Dockerfile ci-tools/Dockerfile || rc=1
else
  echo "== hadolint: not installed, skipped"
fi

echo "== .trivyignore.yaml"
python3 scripts/check_trivyignore.py .trivyignore.yaml || rc=1

echo "== support windows"
python3 scripts/eol_check.py support-windows.yaml || rc=1

echo "== python unit tests"
python3 -m unittest discover -s tests -t . || rc=1

exit "${rc}"
