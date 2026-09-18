# Building the images with BuildKit

The Dockerfiles start from the Iron Bank Jira Dockerfile shape, keep the
Atlassian entrypoint pattern (Python + Jinja2 templates), and add three
BuildKit features: a digest-pinned `FROM`, a checksum-verified `ADD`, and
SBOM/provenance attestations at build time.

## The pattern (`jira/Dockerfile`)

- `ARG ART` + `FROM ${ART}/docker-redhat-remote/ubi9/ubi-minimal:9.7` (Renovate
  appends the digest).
- `ARG VERSION` / `ARG SHA256`: the product version and tarball checksum.
  `scripts/pin-version.sh` writes `VERSION`, `SHA256` and the Dockerfile
  default from Atlassian's published `.sha256` file. `ADD --checksum` fails the
  build on mismatch or when the checksum is empty.
- `ARG ARTEFACT`: `atlassian-jira-software` (default) or `atlassian-servicedesk`
  for Jira Service Management, built from the same Dockerfile.
- `ARG JAVA_PACKAGE`: the JDK is an RPM (`java-21-openjdk-headless`), so
  Copa can patch it. Set it per the product's supported-platforms page.
- One `RUN` layer: `microdnf upgrade` (this is where the weekly rebuild removes
  CVEs), runtime packages, user, extract, `setenv.sh` edits so `JVM_*`
  variables override the defaults, `microdnf clean all`.
- `/var/lib/rpm` is kept: Copa and Trivy need it to know what is installed.

The build context is the **repository root** so `shared/` is available;
`--local dockerfile=<product>` selects the Dockerfile.

## Per-product differences

| Product | Package differences | Ports | Home / install dir | Java |
|---|---|---|---|---|
| Jira Software / JSM | as above; JSM adds the `.obr` copied into `plugins/installed-plugins` (see Iron Bank) | 8080, 40001 | `/var/atlassian/application-data/jira`, `/opt/atlassian/jira` | 21 |
| Confluence | same, plus `procps-ng`; Java 17 or 21 per version matrix | 8090, 8091 | `/var/atlassian/application-data/confluence`, `/opt/atlassian/confluence` | 17 (9.x) |
| Bitbucket | add `git` (>= 2.31) and `openssh-clients`; the bundled OpenSearch needs `vm.max_map_count` on the host (`k8s/policy/sysctl-max-map-count.yaml`) | 7990, 7999 | `/var/atlassian/application-data/bitbucket`, `/opt/atlassian/bitbucket` | 17 or 21 |

Bitbucket ships its own embedded SSH server, so `openssh-server` is not
installed; `openssh-clients` covers git+ssh mirrors and hooks.

## Things that quietly break Copa or Trivy later

All seen in the Iron Bank Dockerfile history:

- `rpm -e --nodeps` leaves the rpm DB inconsistent.
- `microdnf remove` of `tar`/`gzip` is fine, but removing `rpm` or `microdnf`
  is not (Copa needs the package manager).
- Squashing layers (`--squash`, `docker export`) strips Red Hat's per-layer
  content manifests, which Trivy uses to map packages to CPEs, causing false
  positives.

## Invocation

`scripts/build.sh <product>` runs, against the shared daemon:

```sh
buildctl --tlscacert /certs/ca.pem --tlscert /certs/cert.pem --tlskey /certs/key.pem \
  build --frontend dockerfile.v0 \
  --local context=. --local dockerfile=jira \
  --opt build-arg:ART=$ART --opt build-arg:VERSION=11.3.11 --opt build-arg:SHA256=$SHA \
  --opt platform=linux/amd64,linux/arm64 \
  --opt attest:sbom= --opt attest:provenance=mode=max \
  --import-cache type=registry,ref=$REPO/cache/jira \
  --export-cache type=registry,ref=$REPO/cache/jira,mode=max \
  --output type=image,\"name=$REPO/jira:11.3.11-<pipeline>\",push=true,oci-mediatypes=true \
  --metadata-file meta.json          # contains containerimage.digest for signing
```

Registry credentials come from the client's `~/.docker/config.json`; `buildctl`
forwards them over the build session, so `buildkitd` holds no secrets.
Attestations are requested with `--opt attest:*` and land in the image index
next to the manifest, so Trivy can scan the SBOM later without re-pulling.

## Multi-platform

Multi-platform on a single `buildkitd` needs either the `tonistiigi/binfmt`
DaemonSet on its node (`k8s/binfmt/`, QEMU; note Atlassian's own `bsdtar`
workaround for QEMU + GNU tar in `Dockerfile.ubi`) or a second `buildkitd` on
an arm64 node pool added as a worker. If you only deploy amd64, set
`PLATFORMS=linux/amd64` and skip the problem.

## Local builds

Point `BUILDKIT_HOST` at a local rootless daemon and unset the cert path:

```sh
export BUILDKIT_HOST=tcp://127.0.0.1:1234 BUILDKIT_CERTS=/nonexistent ART=artifactory.example.com
make build PRODUCT=jira
```
