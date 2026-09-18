# Building the images with BuildKit

The Dockerfiles start from the Iron Bank Jira Dockerfile shape, keep the
Atlassian entrypoint pattern (Python + Jinja2 templates), and add three
BuildKit features: a digest-pinned `FROM`, a checksum-verified `ADD`, and
SBOM/provenance attestations at build time.

## The hardening manifest: resources pinned by URL and sha256

Each product is built on its Long Term Support line only, from
`<product>/lts/hardening_manifest.yaml` (Iron Bank's format); the Dockerfile
lives in the product directory. A manifest's `resources:` section is the
single source of truth for everything that enters the image from outside the
UBI repos:

| Image | Resources | How it is used |
|---|---|---|
| `<product>/lts` | `PRODUCT` (Atlassian tarball), `TINI_AMD64`, `TINI_ARM64` (upstream release binaries) | tarball extracted to the install dir; tini installed as `/usr/bin/tini` |
| `bitbucket/lts` | `GIT` (kernel.org source tarball) | compiled in the `git-builder` stage and copied to `/opt/git`, as Iron Bank does, so the git version Bitbucket hosts with is chosen here and not by the UBI repo |
| ci-tools | `COPA_*`, `CRANE_*` (GitHub release tarballs per arch) | extracted in per-arch fetch stages |

```yaml
resources:
  - arg: TINI_AMD64
    filename: tini-amd64
    url: https://github.com/krallin/tini/releases/download/v0.19.0/tini-amd64
    validation: { type: sha256, value: 93dcc18adc78c65a028a84799ecf8ad40c936fdfc5f2a57b1acda5a8117fa82c }
```

`scripts/build.sh <product>/lts` turns `args:` and every resource into build args
(`<ARG>_URL`, `<ARG>_SHA256`), rewriting upstream hosts to the Artifactory
generic remotes (`scripts/manifest.py`, `RESOURCE_MIRRORS` to override the
map). The Dockerfiles declare those args **without defaults** and fetch each
resource with `ADD --checksum=sha256:${X_SHA256} ${X_URL}`, so a wrong or
missing checksum fails the build inside BuildKit; the Dockerfile itself never
carries a URL or hash. Per-architecture binaries use one `FROM scratch` stage
per arch and `FROM tini-${TARGETARCH}` to select.

Pinning:

- **Iron Bank first.** Each manifest's `upstream.ironbank` names the Iron Bank
  git repository the line tracks, as a clone URL
  (`https://repo1.dso.mil/dsop/atlassian/<product>-data-center/<product>-lts.git`)
  plus `ref: development` and the manifest path.
  `scripts/sync-ironbank.sh <product>/lts | --all` reads that branch through
  the Artifactory VCS remote (`IRONBANK_FETCH=vcs`, the default; `git`
  shallow-clones the repository directly) and `scripts/ironbank.py apply`
  rewrites ours: `args.VERSION`, `tags`, the
  `PRODUCT` url and sha256 (the one Iron Bank's pipeline verified), and any
  resource Iron Bank pins under the same filename shape (tini, git). Nothing
  else is touched, and the result is idempotent. `--open-mr` commits the
  change on a `sync/ironbank-<date>` branch and opens a merge request.
- `scripts/pin-version.sh <product>/lts <version>` is the manual override:
  it sets `args.VERSION` and `tags` (`[version, line]`), points `PRODUCT` at
  the new tarball and stores the sha256 from Atlassian's published `.sha256`
  file (no tarball download). Use it for an emergency advisory before Iron
  Bank's development branch has moved; the next sync will overwrite it once
  Iron Bank catches up.
  `args` (`JAVA_PACKAGE`, `ARTEFACT`) are per manifest; every current LTS line
  runs Java 21.
- `scripts/pin-resource.sh <dir> <ARG>... | --all` downloads each resource
  through Artifactory, computes its sha256, cross-checks it against the
  upstream's sidecar checksum (`.sha256`, `.sha256sum`, kernel.org's
  `sha256sums.asc`) when one exists, and writes it back. `--url <new>` bumps
  and pins in one step.
- `scripts/manifest.py check <dir>` lists unpinned resources; the build refuses
  to start while any exist. Run `make manifest-check` after cloning.
- Renovate bumps the version inside each annotated resource URL
  (`# renovate: datasource=... depName=...`) and runs `pin-resource.sh --all`
  in the same merge request, so a tini or git release arrives as one reviewed
  change with its new checksum. Renovate never bumps `args.VERSION`: product
  versions are Iron Bank's call.

Anything installed this way (tini, git, copa, crane) is not an RPM: Trivy
does not see it and Copa cannot patch it. Bumping the manifest entry is the
fix path for those, tracked in [what-copa-cant-fix.md](what-copa-cant-fix.md).

## The pattern (`jira/Dockerfile`)

- `ARG ART` + `FROM ${ART}/docker-redhat-remote/ubi9/ubi-minimal:9.7` (Renovate
  appends the digest).
- `ARG VERSION`, `ARG ARTEFACT`, `ARG JAVA_PACKAGE` mirror `args:` in the
  manifest; `ARG PRODUCT_URL` / `ARG PRODUCT_SHA256` come from the `PRODUCT`
  resource. `ARTEFACT` is `atlassian-jira-software` or `atlassian-servicedesk`
  for Jira Service Management, built from the same Dockerfile.
- `JAVA_PACKAGE`: the JDK is an RPM (`java-21-openjdk-headless`), so Copa
  can patch it. Set it per the product's supported-platforms page.
- `COPY --from=tini /tini /usr/bin/tini`: PID 1 from the pinned release binary.
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
| Confluence | same, plus `procps-ng` | 8090, 8091 | `/var/atlassian/application-data/confluence`, `/opt/atlassian/confluence` | 21 (10.x) |
| Bitbucket | `git` built from the manifest's kernel.org tarball (`git-builder` stage, `/opt/git`, `NO_PERL NO_TCLTK NO_GETTEXT NO_PYTHON USE_LIBPCRE2`) plus its runtime libs `expat`, `pcre2`; `openssh-clients`; the bundled OpenSearch needs `vm.max_map_count` on the host (`k8s/policy/sysctl-max-map-count.yaml`) | 7990, 7999 | `/var/atlassian/application-data/bitbucket`, `/opt/atlassian/bitbucket` | 21 (10.x) |

Bitbucket ships its own embedded SSH server, so `openssh-server` is not
installed; `openssh-clients` covers git+ssh mirrors and hooks. To take git
from the UBI repo instead of building it, drop the `git-builder` stage and
the `GIT` resource and add `git` to the `microdnf install` line; you lose the
pinned version but gain Copa coverage for git CVEs.

## Things that quietly break Copa or Trivy later

All seen in the Iron Bank Dockerfile history:

- `rpm -e --nodeps` leaves the rpm DB inconsistent.
- `microdnf remove` of `tar`/`gzip` is fine, but removing `rpm` or `microdnf`
  is not (Copa needs the package manager).
- Squashing layers (`--squash`, `docker export`) strips Red Hat's per-layer
  content manifests, which Trivy uses to map packages to CPEs, causing false
  positives.

## Invocation

`scripts/build.sh <product>/lts` runs, against the shared daemon:

```sh
buildctl --tlscacert /certs/ca.pem --tlscert /certs/cert.pem --tlskey /certs/key.pem \
  build --frontend dockerfile.v0 \
  --local context=. --local dockerfile=jira \
  --opt build-arg:ART=$ART $(scripts/manifest.py build-args jira/lts --art $ART) \
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
make build PRODUCT=jira LINE=lts
```
