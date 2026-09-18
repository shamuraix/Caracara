# Patching with Copacetic

Copa adds one layer with updated RPMs on top of the existing image, driven by
the Trivy JSON report, in about a minute and without touching the Atlassian
layer. Use it between scheduled rebuilds so a Red Hat errata published on
Tuesday is in production on Tuesday, not next Sunday. It is not a replacement
for the rebuild: the rebuild is what advances the base digest and picks up new
Atlassian releases.

```sh
# Copa talks to the same rootless buildkitd the build job uses; no Docker needed.
# Flags per Copa's "custom BuildKit addresses" page.
BK="--addr tcp://buildkitd.buildkit.svc:1234 --cacert /certs/ca.pem --cert /certs/cert.pem --key /certs/key.pem"
REPO=artifactory.example.com/docker-atlassian-local
IMAGE=$REPO/jira:11.3.11

# Targeted: only packages named in the report (preferred for a Java app).
# With a remote daemon there is no local image store, so always --push.
copa patch $BK -i $IMAGE -r report.json -t 11.3.11-patched --push

# Comprehensive: every outdated RPM, no report needed (use on the base image only)
copa patch $BK -i $IMAGE -t 11.3.11-patched --push

# Multi-arch manifest lists are patched per platform and re-assembled
copa patch $BK -i $IMAGE -r report.json --platform linux/amd64,linux/arm64 --push
```

`scripts/patch.sh <name:tag>` is the daily job: scan the live tag (never a
cached report, so a CVE published overnight is caught), patch if anything is
fixable, re-run the full gate on the `-patched` tag, then `crane tag` the
version tag to the patched digest and sign it. Deployments with
`imagePullPolicy: Always` or Argo CD Image Updater pick the new digest up
without a manifest change; the Kyverno freshness rule refuses the old one
after 7 days.

`PLATFORMS` drives `--platform`. With a manifest list and a single Trivy
report, Copa patches the platform the report describes and carries the others
through per its multi-platform docs; if you need targeted patching of every
architecture, scan each platform (`trivy image --platform`) into its own report
and follow Copa's per-platform report layout. Comprehensive mode (no `-r`)
patches every platform identically and is the simpler choice for arm64 fleets.

## Failure modes

| Symptom | Cause | Action |
|---|---|---|
| `copa: package version lower than required` | The report asks for a version the enabled repos don't carry yet (mirror lag, or a minor-version trap: errata only ship for the latest RHEL 9 minor) | Wait for the mirror; bump the base minor tag; triage same day |
| Copa refuses the report | Java findings in the report | Always scan with `--pkg-types os` for the Copa report |
| Re-gate still fails after patching | Findings are in the Java layer or `will_not_fix` reclassified | See [what-copa-cant-fix.md](what-copa-cant-fix.md) |
| `rpm` DB errors during patch | A Dockerfile removed `rpm`/`microdnf` or used `rpm -e --nodeps` | Fix the Dockerfile; rebuild |

Copa docs: [README](https://github.com/project-copacetic/copacetic),
[Quick Start](https://project-copacetic.github.io/copacetic/website/quick-start),
[Troubleshooting](https://project-copacetic.github.io/copacetic/website/troubleshooting),
[Multi-platform patching](https://project-copacetic.github.io/copacetic/website/multiplatform-patching).
