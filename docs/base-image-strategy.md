# Base image strategy

Use **UBI 9 minimal** (or the Iron Bank hardened `ubi9-minimal` if you need
STIG/FIPS). It is the only base that is simultaneously supported until 2032,
scannable by Trivy with fix-version data, patchable by Copa via `microdnf`,
and what both Atlassian and Iron Bank already build on.

| Base | Support ends | Trivy vuln scan | Copa patch | Verdict |
|---|---|---|---|---|
| `ubi9-minimal` | 2032-05-31 (maintenance) | Yes, Red Hat advisories with RHSA fix versions | Yes (microdnf) | **Recommended** |
| Iron Bank `ironbank/redhat/ubi/ubi9-minimal` | Same as UBI 9; rebuilt on every Red Hat release | Yes | Yes | Recommended for DoD / STIG / FIPS |
| `ubi10` | 2035-05-31 | SBOM only in Trivy today (no vuln matching) | Untested | Not yet: you cannot prove "zero fixed CVEs" |
| `ubi8` | Full support ended 2024-05-31 | Yes | Yes | Avoid for new builds |
| `eclipse-temurin:21-noble` (Atlassian's default Ubuntu base) | Ubuntu 24.04 until 2029-04 | Yes | Yes (apt) | Works, but Atlassian itself ships a `-ubi9` variant; pick one OS family and standardize |
| Alpine | ~2 years per release | Yes | Yes (apk) | Avoid: musl + JDK edge cases, short EOL windows |

Dates from [endoflife.date/rhel](https://endoflife.date/rhel); Trivy coverage
from the [Trivy OS coverage table](https://aquasecurity.github.io/trivy/latest/docs/coverage/os/).

**What the two upstreams actually use today.** Atlassian's own `Dockerfile.ubi`
starts from `registry.access.redhat.com/ubi9/openjdk-21` and publishes tags
like `atlassian/jira-software:10.x-ubi9-jdk17`. Iron Bank's Jira Dockerfile
starts from `registry1.dso.mil/ironbank/redhat/ubi/ubi9-minimal:9.7` and
installs `java-21-openjdk-headless` itself. Both run `microdnf upgrade` at
build time, which is why a scheduled rebuild alone removes most OS CVEs. This
repo follows the Iron Bank shape (minimal base, JDK from the RPM so Copa can
patch it).

## Pin by digest, bump by bot

`FROM ubi9-minimal:9.7` still drifts because Red Hat republishes that tag. The
Dockerfiles carry the tag; Renovate (`renovate.json`, `docker:pinDigests`)
appends `@sha256:...` on its first run and opens a merge request every time
the digest changes. That gives reproducible builds and a visible audit trail
of every base bump, which is exactly what Iron Bank's `hardening_manifest.yaml`
does with its `resources:` digests. `scripts/pin-base.sh <product>` does the
same by hand for bootstrap.

Digest bumps are auto-merged once the pipeline is green (build, gate, sign);
that merge is the "rebuild on any base-image release" trigger.

## Minor-version trap

Red Hat only ships errata for the latest RHEL 9 minor. Tracking
`ubi9-minimal:9.7` after 9.8 ships means no more patches for that tag. Either
track the major (`ubi9-minimal:latest` by digest) or bump the minor tag within
days of each release. Renovate opens the minor bump as a non-automerged MR
(`packageRules` in `renovate.json`); the monthly checklist item is to merge it.

## Switching to Iron Bank

Change the FROM line to
`${ART}/docker-registry1-remote/ironbank/redhat/ubi/ubi9-minimal:9.7` and add
the `docker-registry1-remote` repository (needs your registry1 token). The
rest of the Dockerfile is unchanged: Iron Bank's image is UBI 9 minimal with
STIG remediation scripts applied and a FIPS crypto policy, and it is rebuilt
daily.

## Moving to UBI 10

Not before Trivy publishes vulnerability data for RHEL 10 (check the OS
coverage table monthly). Until then a UBI 10 image cannot satisfy the "no
fixed vulnerabilities" test because nothing can prove it.
