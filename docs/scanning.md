# Scanning with Trivy

Run two scans per build: a JSON OS-only scan that feeds Copa, and a gating
scan that fails the job on any fixable HIGH/CRITICAL or an EOL OS. Trivy's
`--ignore-unfixed` is shorthand for
`--ignore-status affected,will_not_fix,fix_deferred,end_of_life`, so it is
exactly the "no fixed vulnerabilities" definition
([filtering docs](https://aquasecurity.github.io/trivy/latest/docs/configuration/filtering/)).

```sh
ART=artifactory.example.com
IMAGE=$ART/docker-atlassian-local/jira:11.3.11
# Vulnerability DBs through Artifactory instead of ghcr.io
export TRIVY_DB_REPOSITORY=$ART/docker-ghcr-remote/aquasecurity/trivy-db
export TRIVY_JAVA_DB_REPOSITORY=$ART/docker-ghcr-remote/aquasecurity/trivy-java-db

# 1. Report for Copa: OS packages only, fixable only            (scripts/patch.sh)
trivy image --pkg-types os --ignore-unfixed -f json -o report.json $IMAGE

# 2. Gate: fail on fixable HIGH/CRITICAL (OS + Java jars) or EOL OS   (scripts/gate.sh)
trivy image --ignore-unfixed --severity HIGH,CRITICAL \
  --exit-code 1 --exit-on-eol 2 \
  --ignorefile .trivyignore.yaml $IMAGE

# 3. Vulnerability record for cosign attest, plus a CycloneDX SBOM    (scripts/gate.sh)
trivy image --format cosign-vuln -o vuln.json $IMAGE
trivy image --format cyclonedx -o sbom.cdx.json $IMAGE
```

Trivy pulls the image from Artifactory with the same `~/.docker/config.json`
the runner uses for `buildctl`; no Docker socket is involved. Exit codes let
the pipeline distinguish "patch it" (1) from "the base OS itself is dead,
rebuild on a newer base" (2, which also opens a GitLab issue).

| Flag | Why it matters here |
|---|---|
| `--pkg-types os` | Copa only understands OS packages; passing Java findings makes it refuse the report |
| `--ignore-unfixed` | Defines the gate: Red Hat `will_not_fix` / `fix_deferred` states are excluded, not hidden (`gate.sh` writes them to `unfixed.json` for tracking) |
| `--exit-on-eol` | Trivy has EOL awareness for RHEL/UBI; a UBI 8 or 9 image past its date fails with this code |
| `--ignorefile .trivyignore.yaml` | Time-boxed exceptions with an `expired_at` date, reviewed in a merge request, never a global suppress |
| `--vex` | Attach Red Hat's CSAF VEX or your own `not_affected` statements so Trivy suppresses them with a reason (`--show-suppressed` to audit) |
| `TRIVY_DB_REPOSITORY` | Keeps DB downloads inside Artifactory; without it every job reaches ghcr.io |

## Red Hat fix versions differ from NVD

Trivy uses Red Hat's advisories, so a fix like `openssl 3.0.7-16.el9_2` (RHSA)
counts as fixed even though NVD lists 3.0.9. Other scanners matching on NVD
alone will show phantom CVEs on UBI. Standardize on Trivy or a Red Hat-aware
scanner for the gate
([Trivy RHEL page](https://aquasecurity.github.io/trivy/latest/docs/coverage/os/rhel/)).

## Java layer

Trivy also inspects `*.jar` inside `/opt/atlassian/*/atlassian-jira/WEB-INF/lib`
and reports CVEs in bundled libraries such as Tomcat, Log4j or Jackson. Those
are real findings, but only Atlassian can fix them; see
[what-copa-cant-fix.md](what-copa-cant-fix.md). Keep the gate scanning them so
upgrades are forced by policy, and use VEX or `.trivyignore.yaml` entries with
an expiry for the ones Atlassian has assessed as not affected.

## The ignore file

`.trivyignore.yaml` is validated by `scripts/check_trivyignore.py` in the lint
stage and before every gate:

- every entry needs `id`, `statement` and `expired_at`;
- `expired_at` may be at most 90 days out (`--max-days`);
- an entry past its expiry fails the pipeline until it is removed or renewed.

Scope entries with `paths:` wherever possible. Prefer a VEX document for
"not affected" findings that have a vendor assessment; use the ignore file for
time-boxed deferrals ("fix lands in 11.3.12, JIRA-1 tracks the bump").

## VEX

Red Hat publishes CSAF VEX for every RHSA; Iron Bank publishes justifications
with each approved image. Either can be turned into an OpenVEX document and
passed with `--vex`. Set `TRIVY_VEX=/path/to/vex.json` in CI and
`scripts/lib.sh` adds `--vex` (plus `--show-suppressed`, so every suppression
is visible in the job log) to the gate; the gate fails if the file is missing
rather than silently running without it.
