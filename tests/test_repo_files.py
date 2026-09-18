"""Structural checks on the pipeline definitions, manifests and Dockerfiles."""

import json
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = ("jira", "confluence", "bitbucket")


class GitLabCITests(unittest.TestCase):
    def setUp(self):
        self.ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text())

    def test_stages_and_jobs(self):
        self.assertEqual(self.ci["stages"], ["lint", "build", "gate", "sign", "patch"])
        for job in ("lint", "build", "gate", "sign", "patch"):
            self.assertIn(job, self.ci)
            self.assertEqual(self.ci[job]["stage"], job)

    def test_matrix_covers_all_products_and_lines(self):
        matrix = self.ci[".product-matrix"]["parallel"]["matrix"][0]
        self.assertEqual(tuple(matrix["PRODUCT"]), PRODUCTS)
        self.assertEqual(matrix["LINE"], ["lts", "latest"])
        self.assertEqual(self.ci[".product-matrix"]["variables"]["TARGET"], "$PRODUCT/$LINE")
        self.assertEqual(self.ci[".product-matrix"]["variables"]["OUT_DIR"], "out/$PRODUCT-$LINE")
        self.assertIn('scripts/build.sh "$TARGET"', self.ci["build"]["script"][1])
        self.assertIn('scripts/patch.sh "$TARGET"', self.ci["patch"]["script"][1])
        self.assertTrue(self.ci["sign"]["script"][1].startswith('EXTRA_TAGS="$LINE" scripts/sign.sh'))

    def test_jenkins_matrix_has_line_axis(self):
        for f in ("Jenkinsfile", "Jenkinsfile.patch"):
            text = (ROOT / f).read_text()
            self.assertIn("axis { name 'LINE'; values 'lts', 'latest' }", text, f)
            self.assertIn('"${PRODUCT}/${LINE}"', text, f)
        for job in ("build", "gate", "sign", "patch"):
            self.assertIn(".product-matrix", self.ci[job]["extends"], job)

    def test_stage_ordering_via_needs(self):
        self.assertEqual(self.ci["gate"]["needs"], ["build"])
        self.assertEqual(self.ci["sign"]["needs"], ["build", "gate"])
        self.assertNotIn("reports", self.ci["build"]["artifacts"])

    def test_schedule_variables(self):
        text = (ROOT / ".gitlab-ci.yml").read_text()
        self.assertIn('$JOB == "rebuild"', text)
        self.assertIn('$JOB == "patch"', text)
        self.assertIn("SIGSTORE_ID_TOKEN", text)

    def test_no_docker_socket_or_privileged(self):
        text = (ROOT / ".gitlab-ci.yml").read_text() + (ROOT / "Jenkinsfile").read_text() + (ROOT / "Jenkinsfile.patch").read_text()
        self.assertNotIn("docker.sock", text)
        self.assertNotIn("privileged: true", text)
        self.assertNotIn("docker build", text)


class DockerfileTests(unittest.TestCase):
    def read(self, product):
        return (ROOT / product / "Dockerfile").read_text()

    def code(self, product):
        """Dockerfile without comment lines."""
        return "\n".join(l for l in self.read(product).splitlines() if not l.lstrip().startswith("#"))

    def test_ubi9_minimal_via_artifactory(self):
        for p in PRODUCTS:
            self.assertRegex(self.read(p), r"FROM \$\{ART\}/docker-redhat-remote/ubi9/ubi-minimal:9\.\d+")

    def test_checksum_verified_add(self):
        for p in PRODUCTS:
            self.assertIn("ADD --checksum=sha256:${PRODUCT_SHA256} ${PRODUCT_URL}", self.read(p))

    def test_no_unpinned_defaults_for_resources(self):
        # URLs and checksums come from the manifest; the Dockerfile must not carry its own copies.
        for p in PRODUCTS + ("ci-tools",):
            for line in self.code(p).splitlines():
                if line.startswith("ARG ") and ("_URL" in line or "_SHA256" in line):
                    self.assertNotIn("=", line, f"{p}: {line}")

    def test_tini_from_manifest_resource(self):
        for p in PRODUCTS:
            text = self.code(p)
            self.assertIn("FROM tini-${TARGETARCH} AS tini", text)
            self.assertIn("COPY --from=tini /tini /usr/bin/tini", text)
            self.assertNotRegex(text, r"microdnf -y install[^\n]*\btini\b", p)

    def test_bitbucket_builds_git_from_source(self):
        text = self.code("bitbucket")
        self.assertIn("AS git-builder", text)
        self.assertIn("ADD --checksum=sha256:${GIT_SHA256} ${GIT_URL}", text)
        self.assertIn("COPY --from=git-builder /opt/git /opt/git", text)
        self.assertNotRegex(text, r"microdnf -y install[^\n]*\bgit\b")

    def test_hygiene(self):
        for p in PRODUCTS + ("ci-tools",):
            text = self.code(p)
            self.assertNotIn("rpm -e", text, p)
            self.assertNotIn("--squash", text, p)
            self.assertNotIn("microdnf remove", text, p)
            self.assertIn("microdnf -y upgrade", text, p)
            self.assertIn("microdnf clean all", text, p)

    def test_runs_unprivileged_under_tini(self):
        for p in PRODUCTS:
            text = self.read(p)
            self.assertIn("USER ${RUN_USER}", text)
            self.assertIn('ENTRYPOINT ["/usr/bin/tini", "--"]', text)
            self.assertIn("VOLUME", text)

    def test_shared_files_copied(self):
        for p in PRODUCTS:
            self.assertIn(f"COPY shared/entrypoint_helpers.py shared/shutdown-wait.sh {p}/entrypoint.py /", self.read(p))


class RenovateTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "renovate.json").read_text())

    def test_pin_digests(self):
        self.assertTrue(self.cfg["dockerfile"]["pinDigests"])
        self.assertIn("docker:pinDigests", self.cfg["extends"])

    def test_version_managers_and_post_upgrade(self):
        managers = {m.get("depNameTemplate"): m for m in self.cfg["customManagers"] if "depNameTemplate" in m}
        self.assertEqual(set(managers), {"jira-software", "confluence", "bitbucket", "git/git"})
        for dep, product in (("jira-software", "jira"), ("confluence", "confluence"), ("bitbucket", "bitbucket")):
            self.assertEqual(managers[dep]["managerFilePatterns"], [f"/^{product}/(lts|latest)/hardening_manifest\\.yaml$/"])
        atl = [r for r in self.cfg["packageRules"] if r.get("matchDatasources") == ["custom.atlassian"]]
        pin = [r for r in atl if "postUpgradeTasks" in r][0]
        self.assertEqual(pin["postUpgradeTasks"]["commands"], ["scripts/pin-version.sh {{{packageFileDir}}} {{{newVersion}}}"])
        by_file = {r["matchFileNames"][0]: r for r in atl if "matchFileNames" in r}
        for product in PRODUCTS:
            for line in ("lts", "latest"):
                rule = by_file[f"{product}/{line}/**"]
                pattern = re.compile(rule["allowedVersions"].strip("/"))
                version = (ROOT / product / line / "hardening_manifest.yaml").read_text()
                import yaml as _y
                current = _y.safe_load(version)["args"]["VERSION"]
                self.assertRegex(current, pattern, f"{product}/{line}: pinned version must satisfy its own allowedVersions")
        resource_rule = [r for r in self.cfg["packageRules"] if "github-releases" in r.get("matchDatasources", [])][0]
        self.assertEqual(resource_rule["postUpgradeTasks"]["commands"], ["scripts/pin-resource.sh {{{packageFileDir}}} --all"])
        manifest_managers = [m for m in self.cfg["customManagers"] if "hardening_manifest" in m["managerFilePatterns"][0]]
        self.assertGreaterEqual(len(manifest_managers), 5)


class ManifestTests(unittest.TestCase):
    def docs(self, path):
        return [d for d in yaml.safe_load_all((ROOT / path).read_text()) if d]

    def test_all_manifests_parse_with_kind(self):
        for path in (ROOT / "k8s").rglob("*.yaml"):
            if path.name in ("kustomization.yaml", "values.yaml"):
                continue
            for doc in self.docs(path.relative_to(ROOT)):
                self.assertIn("kind", doc, path)
                self.assertIn("apiVersion", doc, path)

    def test_buildkitd_is_rootless_and_mtls(self):
        sts = self.docs("k8s/buildkit/statefulset.yaml")[0]
        c = sts["spec"]["template"]["spec"]["containers"][0]
        self.assertTrue(c["image"].endswith("-rootless"))
        self.assertEqual(c["securityContext"]["runAsUser"], 1000)
        self.assertEqual(c["securityContext"]["seccompProfile"]["type"], "Unconfined")
        self.assertNotIn("privileged", c["securityContext"])
        cm = self.docs("k8s/buildkit/configmap.yaml")[0]
        self.assertIn("[grpc.tls]", cm["data"]["buildkitd.toml"])
        self.assertIn('mirrors = ["artifactory.example.com/docker-redhat-remote"]', cm["data"]["buildkitd.toml"])

    def test_kyverno_policy_shape(self):
        pol = self.docs("k8s/policy/kyverno-atlassian-images.yaml")[0]
        self.assertEqual(pol["spec"]["validationFailureAction"], "Enforce")
        vi = pol["spec"]["rules"][0]["verifyImages"][0]
        types = [a["type"] for a in vi["attestations"]]
        self.assertEqual(types, ["https://cyclonedx.org/bom", "https://cosign.sigstore.dev/attestation/vuln/v1"])
        cond = vi["attestations"][1]["conditions"][0]["all"]
        self.assertEqual(cond[1]["value"], "168h")


class SupportFilesTests(unittest.TestCase):
    def test_support_windows_has_every_product(self):
        doc = yaml.safe_load((ROOT / "support-windows.yaml").read_text())
        self.assertEqual(set(doc["products"]), set(PRODUCTS))
        self.assertEqual(str(doc["base_os"]["maintenance_ends"]), "2032-05-31")

    def test_no_stray_version_or_sha_files(self):
        # <product>/<line>/hardening_manifest.yaml is the single source of truth.
        for p in PRODUCTS:
            self.assertFalse((ROOT / p / "VERSION").exists(), p)
            self.assertFalse((ROOT / p / "SHA256").exists(), p)
            for line in ("lts", "latest"):
                self.assertTrue((ROOT / p / line / "hardening_manifest.yaml").exists(), f"{p}/{line}")


if __name__ == "__main__":
    unittest.main()
