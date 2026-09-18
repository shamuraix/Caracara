# What Copa can't fix

Roughly a third of what Trivy reports on an Atlassian image is in the Java
layer, and only an Atlassian version bump fixes it. The pipeline forces those
bumps by policy; this section is how to keep them from blocking every build.

| Finding type | Where Trivy sees it | Fix path | SLA suggestion |
|---|---|---|---|
| OS RPM, fix available | `ubi9-minimal` layer | Copa (daily) or rebuild (weekly) | 7 days HIGH/CRITICAL |
| OS RPM, `will_not_fix` / `fix_deferred` | same | Nothing to do; excluded by `--ignore-unfixed`, tracked in `unfixed.json`, not a gate | Review monthly |
| Bundled jar (Tomcat, Jackson, Log4j, Spring) | `/opt/atlassian/*/WEB-INF/lib` | Upgrade `VERSION` to the release Atlassian's advisory names; check Atlassian's security bug-fix policy | 30 days, or VEX if Atlassian states not exploitable |
| JDK CVE | `java-*-openjdk-headless` RPM | Copa, because the JDK is an RPM here (not so on Atlassian's Temurin-based Ubuntu image) | 7 days |
| Python entrypoint deps (`python3-jinja2`) | RPM | Copa | 7 days |
| Atlassian product CVE (e.g. auth bypass) | Not in Trivy at all; only in Atlassian's advisory | Version bump, often emergency | 72 hours |
| Manifest resources that are not RPMs (`tini`, git built from source, `copa`/`crane` in ci-tools) | Not in Trivy (no package DB entry) | Bump the resource in `hardening_manifest.yaml` (Renovate MR + `pin-resource.sh`), rebuild | 30 days; 7 days for git on Bitbucket |

## Watch three feeds, not one

Trivy's DB covers the first five rows. The last row, Atlassian's own product
vulnerabilities, is published on
[Atlassian's security advisories](https://www.atlassian.com/trust/security/advisories)
and the [Data Center bug-fix policy](https://confluence.atlassian.com/support/atlassian-data-center-bug-fix-policy-1218548716.html).
Subscribe to the advisory feed and to the
[Red Hat product life cycle page](https://access.redhat.com/product-life-cycles)
for base-OS EOL; wire both into the same Renovate or ticket flow that bumps
`VERSION`. Renovate's `custom.atlassian` datasource (Marketplace versions API)
opens the MR for every new patch release on the pinned line; the emergency
path is `scripts/pin-version.sh <product> <version>` in a hand-made MR.

## Version support windows are the real EOL clock

Atlassian only ships security fixes for the current feature release and the
latest Long Term Support (LTS) line. Running an image on a Jira line that has
left support is the same failure as running on UBI 8: no fix will ever arrive,
however often you rebuild. `support-windows.yaml` tracks each product's LTS
end date next to the base-OS date, and `scripts/eol_check.py` fails the lint
stage 30 days before any of them (warns at 90). Update the file, and the
`allowedVersions` rule in `renovate.json`, when moving to a new line.

## Iron Bank as a second opinion

Iron Bank rebuilds its Atlassian images through its own Anchore/Trivy/OpenSCAP
pipeline and publishes approved findings and justifications with each image.
If you can use `registry1.dso.mil`, pulling
`ironbank/atlassian/jira-data-center/jira-node:11.3.11` gives you a
STIG-hardened image with a maintained `.trivyignore`-equivalent already
reviewed; if you cannot, its justifications are still a good source for your
own VEX statements.
