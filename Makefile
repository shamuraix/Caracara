# Developer convenience wrappers around scripts/.  CI does not use this file.
# Point BUILDKIT_HOST at a local rootless buildkitd for local builds, e.g.
#   export BUILDKIT_HOST=tcp://127.0.0.1:1234 BUILDKIT_CERTS=/nonexistent
SHELL := /usr/bin/env bash
PRODUCT ?= jira
LINE ?= lts
TARGET := $(PRODUCT)/$(LINE)
PRODUCTS := jira confluence bitbucket
LINES := lts

.PHONY: help lint test build gate patch sign sync pin pin-resources manifest-check pin-base certs eol

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

lint: ## shellcheck, yamllint, hadolint (if present), ignore-file and EOL checks, unit tests
	scripts/lint.sh

test: ## python unit tests only
	python3 -m unittest discover -s tests -t . -v

build: ## build+push one product's LTS line (PRODUCT=jira|confluence|bitbucket)
	scripts/build.sh $(TARGET)

gate: ## run the Trivy gate on the image from build.env
	set -a && source build.env && set +a && scripts/gate.sh "$$TAG"

sign: ## sign + attest the image from build.env and move the version tag
	set -a && source build.env && set +a && scripts/sign.sh "$${TAG%%:*}@$$DIGEST" "$$VERSION"

patch: ## copa-patch a live line, e.g. make patch PRODUCT=jira LINE=lts
	scripts/patch.sh $(TARGET)

sync: ## pull versions + checksums from Iron Bank development for every line (or TARGET)
	scripts/sync-ironbank.sh --all

pin: ## manual override: pin a line's version + tarball sha256 from Atlassian's .sha256, e.g. make pin PRODUCT=jira LINE=lts VERSION=11.3.11
	scripts/pin-version.sh $(TARGET) $(VERSION)

pin-resources: ## (re)pin every resource sha256 in $(TARGET)/hardening_manifest.yaml (tini, git, copa, crane)
	scripts/pin-resource.sh $(TARGET) --all

manifest-check: ## list unpinned resources for every image line
	@for p in $(PRODUCTS); do for l in $(LINES); do python3 scripts/manifest.py check $$p/$$l || true; done; done; python3 scripts/manifest.py check ci-tools || true

pin-base: ## resolve and pin the base image digest for PRODUCT
	scripts/pin-base.sh $(PRODUCT)

certs: ## generate bootstrap mTLS certs + Secret manifests for buildkitd
	scripts/gen-buildkit-certs.sh ./certs buildkitd.buildkit.svc gitlab-runner jenkins

eol: ## print days to base-OS and product support end
	python3 scripts/eol_check.py support-windows.yaml
