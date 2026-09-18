# Everything through Artifactory

Runners and `buildkitd` never reach the internet directly. Set up these
repositories once and point every `FROM`, `ADD` and tool download at them
(the Dockerfiles take the hostname as `ARG ART`; `buildkitd.toml` mirrors the
upstream registries into the remotes so even `# syntax=` frontend images come
through; `scripts/manifest.py` rewrites the upstream URLs in each
`hardening_manifest.yaml` to the generic remotes below, override the map with
`RESOURCE_MIRRORS="host=https://art/artifactory/repo,..."`).

| Artifactory repo | Type | Proxies / holds | Used by |
|---|---|---|---|
| `docker-redhat-remote` | Docker remote | `registry.access.redhat.com` (UBI 9) | `FROM` in every Dockerfile |
| `docker-registry1-remote` | Docker remote | `registry1.dso.mil` (Iron Bank, needs your registry1 token) | `FROM` when using hardened bases |
| `docker-hub-remote`, `docker-ghcr-remote` | Docker remote | `moby/buildkit`, `aquasec/trivy`, `renovate/renovate`, `tonistiigi/binfmt`, `ghcr.io/sigstore/cosign/cosign`, Trivy DBs (`ghcr.io/aquasecurity/trivy-db`, `trivy-java-db`) | ci-tools image, buildkitd, `TRIVY_DB_REPOSITORY` |
| `generic-atlassian-remote` | Generic remote | `https://product-downloads.atlassian.com` | `ADD --checksum` of the product tarball, `scripts/pin-version.sh` |
| `generic-github-remote` | Generic remote | `https://github.com` (release assets) | `tini` binaries in every product image; `copa` and `crane` tarballs in ci-tools (`hardening_manifest.yaml` resources) |
| `generic-kernel-remote` | Generic remote | `https://mirrors.edge.kernel.org` | git source tarball for Bitbucket (`hardening_manifest.yaml` resource) |
| `pypi-remote` | PyPI remote | `https://pypi.org` | `yamllint`, `shellcheck-py` in ci-tools (lint stage) |
| `docker-atlassian-local` | Docker local | Your built, patched, signed images, the ci-tools image and the BuildKit registry cache (`cache/<product>`) | `--output`, `copa --push`, deploys |
| `docker` | Docker virtual | All of the above | Single pull endpoint for clusters |

## Iron Bank source repositories: the VCS remote

`scripts/sync-ironbank.sh` reads each product's Iron Bank repository
(`https://repo1.dso.mil/dsop/atlassian/<product>-data-center/<product>-lts.git`,
branch `development`) through an Artifactory **VCS remote** so no runner
needs egress to repo1.dso.mil:

| Setting | Value |
|---|---|
| Repository key | `vcs-ironbank-remote` (CI variable `IRONBANK_VCS_REPO`) |
| Package type | VCS |
| Git provider | Custom (Iron Bank's GitLab; nested groups) |
| URL | `https://repo1.dso.mil` |
| Download URL template (Custom provider) | `{0}/{1}/-/archive/{2}/{1}-{2}.tar.gz` (GitLab branch archive; `{0}` group path, `{1}` project, `{2}` ref) |
| Credentials | a repo1 token if the `dsop/atlassian` group is not readable anonymously |

The sync then calls Artifactory's VCS REST API:

- `GET /api/vcs/downloadBranchFile/vcs-ironbank-remote/<group>/<project>/development!hardening_manifest.yaml`
  (default: one file), with `<group>` URL-encoded (`dsop%2Fatlassian%2F<product>-data-center`);
- or, with `IRONBANK_VCS_ARCHIVE=true`, `GET /api/vcs/downloadBranch/.../development?ext=tar.gz`
  and unpacks `hardening_manifest.yaml` from the archive.

If your Artifactory version resolves the nested group path differently, set
`IRONBANK_VCS_TEMPLATE` to the exact URL shape it accepts, using the
placeholders `{art} {vcsrepo} {org} {org_enc} {repo} {ref} {file}` (a template
without `{file}` is treated as an archive). The request authenticates with the
same Artifactory identity the runner already has (`~/.docker/config.json`
from `ART_DOCKER_CONFIG`, or `ARTIFACTORY_TOKEN` as a bearer token), so the
VCS remote's read permission goes to that CI identity.

`IRONBANK_FETCH=git` bypasses Artifactory and shallow-clones the repository
directly (local use, or runners with egress); `IRONBANK_GIT_BASE` and
`IRONBANK_GIT_TOKEN` point that mode at a mirror or a private group.

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
