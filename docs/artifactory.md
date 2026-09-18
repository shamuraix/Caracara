# Everything through Artifactory

Runners and `buildkitd` never reach the internet directly. Set up these
repositories once and point every `FROM`, `ADD` and tool download at them
(the Dockerfiles take the hostname as `ARG ART`; `buildkitd.toml` mirrors the
upstream registries into the remotes so even `# syntax=` frontend images come
through).

| Artifactory repo | Type | Proxies / holds | Used by |
|---|---|---|---|
| `docker-redhat-remote` | Docker remote | `registry.access.redhat.com` (UBI 9) | `FROM` in every Dockerfile |
| `docker-registry1-remote` | Docker remote | `registry1.dso.mil` (Iron Bank, needs your registry1 token) | `FROM` when using hardened bases |
| `docker-hub-remote`, `docker-ghcr-remote` | Docker remote | `moby/buildkit`, `aquasec/trivy`, `renovate/renovate`, `tonistiigi/binfmt`, `ghcr.io/sigstore/cosign/cosign`, Trivy DBs (`ghcr.io/aquasecurity/trivy-db`, `trivy-java-db`) | ci-tools image, buildkitd, `TRIVY_DB_REPOSITORY` |
| `generic-atlassian-remote` | Generic remote | `https://product-downloads.atlassian.com` | `ADD --checksum` of the product tarball, `scripts/pin-version.sh` |
| `generic-github-remote` | Generic remote | `https://github.com` (release tarballs) | `copa` and `crane` binaries in ci-tools |
| `pypi-remote` | PyPI remote | `https://pypi.org` | `yamllint`, `shellcheck-py` in ci-tools (lint stage) |
| `docker-atlassian-local` | Docker local | Your built, patched, signed images, the ci-tools image and the BuildKit registry cache (`cache/<product>`) | `--output`, `copa --push`, deploys |
| `docker` | Docker virtual | All of the above | Single pull endpoint for clusters |

## Credentials

- **CI** gets one scoped token: push on `docker-atlassian-local`, read on the
  remotes. GitLab: masked variable `ART_DOCKER_CONFIG` holding a docker
  `config.json`; Jenkins: `artifactory-docker` username/password credential
  (`crane auth login`). `buildctl` forwards the client's `~/.docker/config.json`
  to the daemon over the build session, so `buildkitd` itself holds no secrets.
- **Renovate** needs a `hostRules` entry with an Artifactory token for the
  remotes (`k8s/renovate/configmap.yaml`).
- **Trivy** needs `TRIVY_DB_REPOSITORY` / `TRIVY_JAVA_DB_REPOSITORY` pointed
  at `docker-ghcr-remote` so DB updates also come through the proxy
  (`scripts/lib.sh` sets both). For air-gapped clusters, Trivy's self-hosting
  page covers mirroring the DB as an OCI artifact into a local repo instead.

## Xray

Artifactory Xray can scan the same repos as a second opinion, but keep Trivy
as the gate so Copa and the gate agree on what "fixable" means (Xray matches
on different data and will disagree on Red Hat backports).

## Retention

Keep the last 3 signed digests per version tag; clean unsigned `-patched`
tags after 24 hours and `cache/*` blobs older than 30 days (Artifactory
cleanup policies on `docker-atlassian-local`).
