import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ironbank  # noqa: E402
import manifest  # noqa: E402

SHA_A = "a" * 64
SHA_B = "b" * 64
IB_MANIFEST = {
    "apiVersion": "v1",
    "name": "atlassian/bitbucket-data-center/bitbucket-lts",
    "tags": ["10.2.9", "latest"],
    "args": {"BASE_IMAGE": "redhat/ubi/ubi9-minimal", "BASE_TAG": "9.7"},
    "resources": [
        {"url": "https://product-downloads.atlassian.com/software/stash/downloads/atlassian-bitbucket-10.2.9.tar.gz",
         "filename": "atlassian-bitbucket-10.2.9.tar.gz", "validation": {"type": "sha256", "value": SHA_A}},
        {"url": "https://github.com/krallin/tini/releases/download/v0.19.0/tini-amd64",
         "filename": "tini-amd64", "validation": {"type": "sha256", "value": SHA_B}},
    ],
}


class UrlTests(unittest.TestCase):
    def test_every_line_names_its_ironbank_project(self):
        for product, group in (("jira", "jira-data-center"), ("confluence", "confluence-data-center"), ("bitbucket", "bitbucket-data-center")):
            for line in ("lts", "latest"):
                _, doc = manifest.load(ROOT / product / line)
                up = ironbank.upstream(doc)
                self.assertTrue(up["project"].startswith(f"dsop/atlassian/{group}/{product}-"), f"{product}/{line}")
                self.assertEqual(up["ref"], "development", f"{product}/{line}")
                if line == "lts":
                    self.assertTrue(up["project"].endswith(f"{product}-lts"))
                url = ironbank.raw_url(doc, "art.local")
                self.assertEqual(url, f"https://art.local/artifactory/generic-repo1-remote/{up['project']}/-/raw/development/hardening_manifest.yaml")
                self.assertTrue(ironbank.raw_url(doc, direct=True).startswith("https://repo1.dso.mil/dsop/atlassian/"))


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "bitbucket" / "lts" / "hardening_manifest.yaml", self.tmp / "hardening_manifest.yaml")
        (self.tmp / "ib.yaml").write_text(yaml.safe_dump(IB_MANIFEST))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_apply(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = ironbank.main(["apply", str(self.tmp), str(self.tmp / "ib.yaml")])
        return rc, out.getvalue()

    def test_adopts_version_tarball_and_matching_resources(self):
        rc, out = self.run_apply()
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("changed"))
        _, doc = manifest.load(self.tmp)
        self.assertEqual(doc["args"]["VERSION"], "10.2.9")
        self.assertEqual(doc["tags"], ["10.2.9", self.tmp.name])
        product = manifest.find_resource(doc, "PRODUCT")
        self.assertEqual(product["url"], IB_MANIFEST["resources"][0]["url"])
        self.assertEqual(product["filename"], "atlassian-bitbucket-10.2.9.tar.gz")
        self.assertEqual(manifest.sha256_of(product), SHA_A)
        self.assertEqual(manifest.sha256_of(manifest.find_resource(doc, "TINI_AMD64")), SHA_B)
        # untouched: resources Iron Bank does not pin keep their values
        self.assertNotEqual(manifest.sha256_of(manifest.find_resource(doc, "TINI_ARM64")), SHA_B)
        self.assertEqual(manifest.find_resource(doc, "GIT")["url"].split("/")[-1], "git-2.47.1.tar.xz")
        self.assertEqual(doc["upstream"]["ironbank"]["synced_version"], "10.2.9")
        # ours must still pass the pin check for what Iron Bank supplied
        self.assertNotIn("PRODUCT", manifest.unpinned(doc))

    def test_idempotent(self):
        self.run_apply()
        rc, out = self.run_apply()
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("unchanged"), out)

    def test_git_matched_by_filename_shape(self):
        ib = dict(IB_MANIFEST)
        ib["resources"] = ib["resources"] + [{
            "url": "https://mirrors.edge.kernel.org/pub/software/scm/git/git-2.50.1.tar.xz",
            "filename": "git-2.50.1.tar.xz", "validation": {"type": "sha256", "value": "c" * 64}}]
        (self.tmp / "ib.yaml").write_text(yaml.safe_dump(ib))
        self.run_apply()
        _, doc = manifest.load(self.tmp)
        git = manifest.find_resource(doc, "GIT")
        self.assertEqual(git["filename"], "git-2.50.1.tar.xz")
        self.assertEqual(manifest.sha256_of(git), "c" * 64)

    def test_version_fallbacks(self):
        self.assertEqual(ironbank.ib_version({"tags": ["latest"], "args": {"CONFLUENCE_VERSION": "10.2.18"}}, ""), "10.2.18")
        self.assertEqual(ironbank.ib_version({}, "https://x/atlassian-jira-software-11.3.11.tar.gz"), "11.3.11")
        with self.assertRaises(ironbank.SyncError):
            ironbank.ib_version({}, "https://x/no-version.tar.gz")

    def test_rejects_manifest_without_tarball_or_sha(self):
        (self.tmp / "ib.yaml").write_text(yaml.safe_dump({"tags": ["1.2.3"], "resources": []}))
        with self.assertRaises(ironbank.SyncError):
            ironbank.main(["apply", str(self.tmp), str(self.tmp / "ib.yaml")])
        bad = dict(IB_MANIFEST); bad["resources"] = [dict(IB_MANIFEST["resources"][0], validation={"type": "sha256", "value": ""})]
        (self.tmp / "ib.yaml").write_text(yaml.safe_dump(bad))
        with self.assertRaises(ironbank.SyncError):
            ironbank.main(["apply", str(self.tmp), str(self.tmp / "ib.yaml")])
        # our manifest is left untouched on failure
        _, doc = manifest.load(self.tmp)
        self.assertEqual(doc["args"]["VERSION"], "10.2.7")


if __name__ == "__main__":
    unittest.main()
