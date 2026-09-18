# Policy gates and ops checklist

Enforce at three points: **PR** (Trivy on the built image), **registry** (only
signed digests get the version tag), and **cluster admission** (signature +
freshness). Freshness is the one most teams skip; without it a node can run a
90-day-old digest forever.

## Admission policy

`k8s/policy/kyverno-atlassian-images.yaml` (Kyverno `verifyImages`):

- images from `docker-atlassian-local` (or the `docker` virtual) only;
- signed by the GitLab sign job's keyless identity (`issuer` + `subject` are
  the project and ref that ran it) **or** the Jenkins cosign public key;
- a CycloneDX SBOM attestation must be attached;
- the `vuln/v1` attestation must say `scanner.result == pass` and
  `metadata.scanFinishedOn` must be less than 168 hours old.

If your Kyverno sits behind a private Sigstore (Rekor/Fulcio via Artifactory
or self-hosted), add `rekor.url` and `roots` under the keyless entry; the
GitLab OIDC subject format is documented in
[GitLab's Sigstore guide](https://docs.gitlab.com/ee/ci/yaml/signing_examples.html).
The vuln attestation comes from `trivy image --format cosign-vuln` piped to
`cosign attest --type vuln`; Trivy documents this under
[Cosign Vulnerability Scan Record](https://aquasecurity.github.io/trivy/latest/docs/supply-chain/attestation/vuln/).
Sigstore policy-controller is an equivalent alternative to Kyverno.

## Setup checklist

- [ ] Mirror the Iron Bank Dockerfiles for Jira, Confluence, Bitbucket into a GitLab project (this repo); switch `FROM` to an Artifactory-proxied digest (`scripts/pin-base.sh` or Renovate)
- [ ] Create the Artifactory repos in [artifactory.md](artifactory.md); give CI a scoped token with push on `docker-atlassian-local` and read on the remotes
- [ ] Deploy the rootless `buildkitd` StatefulSet with mTLS (`kubectl apply -k k8s/buildkit`); issue client certs to the runner namespace (GitLab) and the Jenkins agent namespace
- [ ] Build and pin a ci-tools image (`buildctl`, `trivy`, `copa`, `cosign`, `crane`, `jq`) in `docker-atlassian-local`; Renovate keeps it current
- [ ] GitLab Runner with the kubernetes executor (`k8s/gitlab-runner/values.yaml`) or Jenkins kubernetes plugin (`k8s/jenkins/pod-template.yaml`) mounting `buildkit-client-certs`; no privileged pods, no Docker socket
- [ ] Renovate as a Kubernetes CronJob (`k8s/renovate/`): `platform: gitlab`, docker manager for base digests, regex manager for `VERSION`, `hostRules` for Artifactory
- [ ] Create `generic-repo1-remote` (repo1.dso.mil) and confirm the `upstream.ironbank.project` paths in all six manifests (the `latest` ones point at the non-LTS Iron Bank projects; rename if the group calls them differently); `make sync` pulls every line's version and checksum from Iron Bank's `development` branch
- [ ] `make manifest-check`, then `scripts/pin-resource.sh <dir> --all` for whatever Iron Bank did not supply (git, copa, crane); the build refuses to run while a `hardening_manifest.yaml` resource has no sha256
- [ ] `GITLAB_SYNC_TOKEN` (api + write_repository) so the weekly rebuild's sync stage can open its merge request
- [ ] `.trivyignore.yaml` with mandatory `expired_at` on every entry; CI fails on entries past expiry (`scripts/check_trivyignore.py`)
- [ ] Signing: GitLab OIDC keyless, or a cosign key in Jenkins credentials / KMS; publish the verification policy consumers use (`k8s/policy/`)
- [ ] Artifactory retention: keep the last 3 signed digests per version tag, clean unsigned `-patched` tags after 24h
- [ ] Dashboard: image age, fixable CVE count (`unfixed.json`, `vuln.json` artefacts), days to base-OS EOL and Atlassian LTS end (`scripts/eol_check.py --json`), per running image

## Recurring

- **Daily**: patch job green; any Copa "version lower than required" error triaged same day
- **Weekly**: rebuild green for all products; review the `unfixed.json` (`will_not_fix`) list for anything Red Hat reclassified; merge Renovate MRs for manifest resources (git on Bitbucket first: it is not Copa-patchable)
- **Weekly, after the rebuild**: merge the `sync/ironbank-<date>` MR so git matches what was built; set `support_ends` in `support-windows.yaml` when a line moved
- **Monthly**: merge the Renovate MRs (base digests, tini/git/copa/crane); expire stale ignore entries; merge the UBI minor bump; re-check Trivy has vuln data for the base OS (relevant when moving to UBI 10)
- **Quarterly**: rehearse an emergency Atlassian advisory: from advisory to signed image in production in under 24h (`scripts/pin-version.sh`, MR, rebuild, `crane tag`)
- **Yearly, every May 31**: confirm base-OS phase (RHEL 9 full support ends 2027-05-31; maintenance 2032-05-31) and update `support-windows.yaml`
- **Yearly, when Atlassian announces a new LTS line** (Dec/Jan): watch for Iron Bank's `<product>-lts` project to move to it; the sync follows automatically, so the work is updating `support-windows.yaml` and re-validating the line while the old LTS still has runway

## Sources

- Copacetic: [README](https://github.com/project-copacetic/copacetic), [Quick Start](https://project-copacetic.github.io/copacetic/website/quick-start), [Troubleshooting](https://project-copacetic.github.io/copacetic/website/troubleshooting), [Multi-platform patching](https://project-copacetic.github.io/copacetic/website/multiplatform-patching)
- BuildKit: [buildctl reference](https://github.com/moby/buildkit#readme), [Kubernetes examples](https://github.com/moby/buildkit/tree/master/examples/kubernetes) (rootless StatefulSet, mTLS)
- Iron Bank: [Atlassian group](https://repo1.dso.mil/dsop/atlassian) and the Jira Data Center Dockerfile (development branch, Jira 11.3.11 on ubi9-minimal 9.7); [UBI 9.x group](https://repo1.dso.mil/dsop/redhat/ubi) (ubi9 Dockerfile, STIG remediation scripts)
- Atlassian: [docker-atlassian-jira `Dockerfile.ubi`](https://github.com/atlassian/docker-atlassian-jira) and [atlassian/jira-core on Docker Hub](https://hub.docker.com/r/atlassian/jira-core) (`-ubi9-jdk17` tags)
- Trivy: [User Guide](https://aquasecurity.github.io/trivy/), [OS coverage](https://aquasecurity.github.io/trivy/latest/docs/coverage/os/), [Red Hat](https://aquasecurity.github.io/trivy/latest/docs/coverage/os/rhel/), [Filtering](https://aquasecurity.github.io/trivy/latest/docs/configuration/filtering/), [Self-hosting the DB](https://aquasecurity.github.io/trivy/latest/docs/advanced/self-hosting/), [Vulnerability attestation](https://aquasecurity.github.io/trivy/latest/docs/supply-chain/attestation/vuln/)
- GitLab: [Kubernetes executor](https://docs.gitlab.com/runner/executors/kubernetes/), [Sigstore signing examples](https://docs.gitlab.com/ee/ci/yaml/signing_examples.html)
- Jenkins: [Kubernetes plugin](https://plugins.jenkins.io/kubernetes/)
- JFrog: [Docker registry in Artifactory](https://jfrog.com/help/r/jfrog-artifactory-documentation/docker-registry), [Remote repositories](https://jfrog.com/help/r/jfrog-artifactory-documentation/remote-repositories)
- [RHEL life cycle dates (endoflife.date)](https://endoflife.date/rhel)
- [Atlassian security advisories](https://www.atlassian.com/trust/security/advisories) and [security bug-fix policy](https://www.atlassian.com/trust/security/bug-fix-policy)
