# Developer convenience wrappers around scripts/.  CI does not use this file.
# Point BUILDKIT_HOST at a local rootless buildkitd for local builds, e.g.
#   export BUILDKIT_HOST=tcp://127.0.0.1:1234 BUILDKIT_CERTS=/nonexistent
SHELL := /usr/bin/env bash
PRODUCT ?= jira
PRODUCTS := jira confluence bitbucket

.PHONY: help lint test build gate patch sign pin pin-resources manifest-check pin-base certs eol

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

lint: ## shellcheck, yamllint, hadolint (if present), ignore-file and EOL checks, unit tests
	scripts/lint.sh

test: ## python unit tests only
	python3 -m unittest discover -s tests -t . -v

build: ## build+push one product (PRODUCT=jira|confluence|bitbucket)
	scripts/build.sh $(PRODUCT)

gate: ## run the Trivy gate on the image from build.env
	set -a && source build.env && set +a && scripts/gate.sh "$$TAG"

sign: ## sign + attest the image from build.env and move the version tag
	set -a && source build.env && set +a && scripts/sign.sh "$${TAG%%:*}@$$DIGEST" "$$VERSION"

patch: ## copa-patch a live tag, e.g. make patch IMAGE=jira:11.3.11
	scripts/patch.sh $(IMAGE)

pin: ## pin a product version + tarball sha256, e.g. make pin PRODUCT=jira VERSION=11.3.11
	scripts/pin-version.sh $(PRODUCT) $(VERSION)

pin-resources: ## (re)pin every resource sha256 in PRODUCT/hardening_manifest.yaml (tini, git, copa, crane)
	scripts/pin-resource.sh $(PRODUCT) --all

manifest-check: ## list unpinned resources for every image
	@for d in $(PRODUCTS) ci-tools; do python3 scripts/manifest.py check $$d || true; done

pin-base: ## resolve and pin the base image digest for PRODUCT
	scripts/pin-base.sh $(PRODUCT)

certs: ## generate bootstrap mTLS certs + Secret manifests for buildkitd
	scripts/gen-buildkit-certs.sh ./certs buildkitd.buildkit.svc gitlab-runner jenkins

eol: ## print days to base-OS and product support end
	python3 scripts/eol_check.py support-windows.yaml
