import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import manifest  # noqa: E402

PRODUCTS = ("jira", "confluence", "bitbucket")
LINES = ("lts", "latest")
TARGETS = tuple(f"{p}/{l}" for p in PRODUCTS for l in LINES)


class MirrorTests(unittest.TestCase):
    def test_known_hosts_rewritten(self):
        os.environ.pop("RESOURCE_MIRRORS", None)
        self.assertEqual(
            manifest.mirror_url("https://github.com/krallin/tini/releases/download/v0.19.0/tini-amd64", "art.local"),
            "https://art.local/artifactory/generic-github-remote/krallin/tini/releases/download/v0.19.0/tini-amd64",
        )
        self.assertEqual(
            manifest.mirror_url("https://mirrors.edge.kernel.org/pub/software/scm/git/git-2.47.1.tar.xz", "art.local"),
            "https://art.local/artifactory/generic-kernel-remote/pub/software/scm/git/git-2.47.1.tar.xz",
        )
        self.assertEqual(
            manifest.mirror_url("https://product-downloads.atlassian.com/software/jira/downloads/x.tar.gz", "art.local"),
            "https://art.local/artifactory/generic-atlassian-remote/software/jira/downloads/x.tar.gz",
        )

    def test_unknown_host_and_direct(self):
        self.assertEqual(manifest.mirror_url("https://example.org/a", "art.local"), "https://example.org/a")
        self.assertEqual(manifest.mirror_url("https://github.com/a", "art.local", direct=True), "https://github.com/a")

    def test_env_override(self):
        os.environ["RESOURCE_MIRRORS"] = "github.com=https://proxy/gh, kernel.org=https://proxy/k"
        try:
            self.assertEqual(manifest.mirror_url("https://github.com/a/b", "ignored"), "https://proxy/gh/a/b")
        finally:
            del os.environ["RESOURCE_MIRRORS"]


class ManifestFileTests(unittest.TestCase):
    def test_every_line_has_a_manifest_with_tini(self):
        for t in TARGETS:
            _, doc = manifest.load(ROOT / t)
            args = {manifest.resource_arg(r) for r in doc["resources"]}
            self.assertIn("PRODUCT", args, t)
            self.assertIn("TINI_AMD64", args, t)
            self.assertIn("TINI_ARM64", args, t)
            self.assertEqual(doc["tags"], [doc["args"]["VERSION"], t.split("/")[1]], t)
            product = manifest.find_resource(doc, "PRODUCT")
            self.assertIn(doc["args"]["VERSION"], product["url"], t)
            self.assertIn(doc["args"]["ARTEFACT"], product["url"], t)

    def test_lts_and_latest_are_distinct_lines(self):
        for p in PRODUCTS:
            _, lts = manifest.load(ROOT / p / "lts")
            _, latest = manifest.load(ROOT / p / "latest")
            self.assertNotEqual(lts["args"]["VERSION"], latest["args"]["VERSION"], p)
            self.assertEqual(lts["args"]["ARTEFACT"], latest["args"]["ARTEFACT"], p)
            self.assertFalse((ROOT / p / "hardening_manifest.yaml").exists(), f"{p}: manifest must live under lts/ or latest/")

    def test_bitbucket_pins_git_source_on_both_lines(self):
        for line in LINES:
            _, doc = manifest.load(ROOT / "bitbucket" / line)
            git = manifest.find_resource(doc, "GIT")
            self.assertTrue(git["url"].endswith(".tar.xz"), line)
            self.assertIn("kernel.org", git["url"], line)

    def test_ci_tools_resources(self):
        _, doc = manifest.load(ROOT / "ci-tools")
        args = {manifest.resource_arg(r) for r in doc["resources"]}
        self.assertEqual(args, {"COPA_AMD64", "COPA_ARM64", "CRANE_AMD64", "CRANE_ARM64"})

    def test_pinned_values_are_sha256(self):
        for d in TARGETS + ("ci-tools",):
            _, doc = manifest.load(ROOT / d)
            for r in doc["resources"]:
                val = manifest.sha256_of(r)
                self.assertTrue(val == "" or manifest.SHA256_RE.match(val), f"{d}/{manifest.resource_arg(r)}")

    def test_tini_pinned(self):
        for t in TARGETS:
            _, doc = manifest.load(ROOT / t)
            for arg in ("TINI_AMD64", "TINI_ARM64"):
                self.assertTrue(manifest.SHA256_RE.match(manifest.sha256_of(manifest.find_resource(doc, arg))), f"{t}/{arg}")


class BuildArgsTests(unittest.TestCase):
    def test_build_args_shape(self):
        _, doc = manifest.load(ROOT / "bitbucket" / "lts")
        args = manifest.build_args(doc, "art.local")
        self.assertEqual(args["VERSION"], doc["args"]["VERSION"])
        self.assertTrue(args["PRODUCT_URL"].startswith("https://art.local/artifactory/generic-atlassian-remote/"))
        self.assertTrue(args["GIT_URL"].startswith("https://art.local/artifactory/generic-kernel-remote/"))
        self.assertEqual(len(args["TINI_AMD64_SHA256"]), 64)
        self.assertIn("GIT_SHA256", args)

    def test_dockerfile_declares_every_resource_arg(self):
        # The product Dockerfile is shared by its lts/ and latest/ manifests.
        for d in TARGETS + ("ci-tools",):
            _, doc = manifest.load(ROOT / d)
            text = (ROOT / d.split("/")[0] / "Dockerfile").read_text()
            for r in doc["resources"]:
                stem = manifest.resource_arg(r)
                self.assertIn(f"ARG {stem}_URL\n", text, f"{d}: {stem}_URL")
                self.assertIn(f"ARG {stem}_SHA256\n", text, f"{d}: {stem}_SHA256")
                self.assertIn(f"ADD --checksum=sha256:${{{stem}_SHA256}}", text, f"{d}: {stem}")
            for name in doc["args"]:
                self.assertIn(f"ARG {name}", text, f"{d}: {name}")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copy(ROOT / "jira" / "lts" / "hardening_manifest.yaml", Path(self.tmp) / "hardening_manifest.yaml")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = manifest.main(list(argv))
        return rc, out.getvalue()

    def test_version_and_check(self):
        rc, out = self.run_cli("version", self.tmp)
        self.assertEqual((rc, out.strip()), (0, "11.3.11"))
        rc, out = self.run_cli("check", self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("PRODUCT", out)

    def test_set_resource_and_set_arg_roundtrip(self):
        sha = "a" * 64
        rc, _ = self.run_cli("set-resource", self.tmp, "PRODUCT", "--url", "https://product-downloads.atlassian.com/x/y-1.2.3.tar.gz", "--sha256", sha)
        self.assertEqual(rc, 0)
        rc, _ = self.run_cli("set-arg", self.tmp, "VERSION", "1.2.3")
        self.assertEqual(rc, 0)
        rc, out = self.run_cli("check", self.tmp)
        self.assertEqual(rc, 0)
        rc, out = self.run_cli("build-args", self.tmp, "--art", "art.local", "--shell")
        self.assertIn("VERSION=1.2.3\n", out)
        self.assertIn(f"PRODUCT_SHA256={sha}\n", out)
        self.assertIn("PRODUCT_URL=https://art.local/artifactory/generic-atlassian-remote/x/y-1.2.3.tar.gz\n", out)
        rc, out = self.run_cli("url", self.tmp, "TINI_AMD64", "--direct")
        self.assertTrue(out.startswith("https://github.com/krallin/tini/"))

    def test_bad_sha_rejected(self):
        with self.assertRaises(manifest.ManifestError):
            self.run_cli("set-resource", self.tmp, "PRODUCT", "--sha256", "nope")


if __name__ == "__main__":
    unittest.main()
