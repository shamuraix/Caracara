#!/usr/bin/env python3
"""Sync a line's hardening_manifest.yaml from its Iron Bank upstream project.

Each of our manifests names the Iron Bank git repository it tracks:

    upstream:
      ironbank:
        repo: https://repo1.dso.mil/dsop/atlassian/bitbucket-data-center/bitbucket-lts.git
        ref: development
        manifest: hardening_manifest.yaml

`repo <target>` prints "<repo> <ref> <manifest>" for sync-ironbank.sh to
clone (IRONBANK_GIT_BASE rewrites the https://repo1.dso.mil/ prefix to a
mirror); `vcs-url <target>` prints the Artifactory VCS-remote REST URL that
serves the same branch (a single file with the downloadBranchFile API, or the
branch archive with downloadBranch) so nothing has to reach repo1.dso.mil
directly; `apply <target> <file>` reads the manifest from that checkout and
updates ours: args.VERSION and tags from the product version Iron Bank pins,
the PRODUCT resource's url and sha256 from the product-downloads.atlassian.com
tarball Iron Bank verifies, and any other resource whose filename Iron Bank
also pins (tini, git).  Exit 0 and print "changed"/"unchanged"; exit 2 on a
manifest we cannot interpret.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest  # noqa: E402

REPO1 = "https://repo1.dso.mil"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
GIT_URL = re.compile(r"^(https://|ssh://|git@)[^\s]+$")


class SyncError(RuntimeError):
    pass


def upstream(doc: dict) -> dict:
    up = dict(((doc.get("upstream") or {}).get("ironbank")) or {})
    if not up.get("repo") and up.get("project"):
        up["repo"] = f"{REPO1}/{str(up['project']).strip('/')}.git"
    if not up.get("repo"):
        raise SyncError("manifest has no upstream.ironbank.repo (git URL of the Iron Bank project)")
    if not GIT_URL.match(str(up["repo"])):
        raise SyncError(f"upstream.ironbank.repo is not a git URL: {up['repo']!r}")
    up.setdefault("ref", "development")
    up.setdefault("manifest", "hardening_manifest.yaml")
    return up


# Artifactory VCS remote (repo key IRONBANK_VCS_REPO) in front of repo1.dso.mil.
# Placeholders: {art} {vcsrepo} {org} {org_enc} {repo} {ref} {file}.  The
# default asks for just the manifest; a template without {file} must return a
# tar.gz branch archive (downloadBranch), which sync-ironbank.sh unpacks.
VCS_FILE_TEMPLATE = "https://{art}/artifactory/api/vcs/downloadBranchFile/{vcsrepo}/{org_enc}/{repo}/{ref}!{file}"
VCS_ARCHIVE_TEMPLATE = "https://{art}/artifactory/api/vcs/downloadBranch/{vcsrepo}/{org_enc}/{repo}/{ref}?ext=tar.gz"


def project_path(doc: dict) -> tuple[str, str]:
    """('dsop/atlassian/bitbucket-data-center', 'bitbucket-lts') from the repo URL."""
    repo = str(upstream(doc)["repo"])
    path = urlsplit(repo).path if "://" in repo else repo.split(":", 1)[-1]
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    org, _, name = path.rpartition("/")
    if not org or not name:
        raise SyncError(f"cannot split {repo!r} into group and project")
    return org, name


def vcs_url(doc: dict, art: str, vcsrepo: str, template: str | None = None) -> str:
    org, name = project_path(doc)
    up = upstream(doc)
    tpl = template or VCS_FILE_TEMPLATE
    return tpl.format(art=art, vcsrepo=vcsrepo, org=org, org_enc=org.replace("/", "%2F"),
                      repo=name, ref=up["ref"], file=up["manifest"])


def clone_url(doc: dict, base: str | None = None) -> str:
    """The repo URL, with https://repo1.dso.mil/ rewritten to `base` (a mirror) when given."""
    repo = str(upstream(doc)["repo"])
    if base and repo.startswith(REPO1 + "/"):
        return base.rstrip("/") + "/" + repo[len(REPO1) + 1:]
    return repo


def ib_product_resource(ib: dict) -> dict:
    for res in ib.get("resources") or []:
        url = str(res.get("url", ""))
        host = urlsplit(url).netloc
        if host.endswith("atlassian.com") and ".tar.gz" in url:
            return res
    raise SyncError("Iron Bank manifest has no product-downloads.atlassian.com tarball resource")


def ib_version(ib: dict, product_url: str) -> str:
    for tag in ib.get("tags") or []:
        if SEMVER.match(str(tag)):
            return str(tag)
    for key, value in (ib.get("args") or {}).items():
        if "VERSION" in str(key).upper() and SEMVER.match(str(value)):
            return str(value)
    m = re.search(r"-(\d+\.\d+\.\d+)\.tar\.gz", product_url)
    if m:
        return m.group(1)
    raise SyncError("cannot determine the product version from the Iron Bank manifest")


def ib_sha(res: dict) -> str:
    val = (res.get("validation") or {})
    if str(val.get("type", "sha256")).lower() != "sha256":
        raise SyncError(f"unsupported validation type {val.get('type')!r} for {res.get('filename')}")
    sha = str(val.get("value", "")).strip().lower()
    if not manifest.SHA256_RE.match(sha):
        raise SyncError(f"Iron Bank resource {res.get('filename')} has no sha256")
    return sha


def apply(ours: dict, ib: dict, line: str) -> list[str]:
    """Update `ours` in place from the Iron Bank manifest; return change notes."""
    changes: list[str] = []
    product = ib_product_resource(ib)
    version = ib_version(ib, str(product["url"]))
    if ours["args"].get("VERSION") != version:
        changes.append(f"VERSION {ours['args'].get('VERSION')} -> {version}")
        ours["args"]["VERSION"] = version
    tags = [version, line]
    if ours.get("tags") != tags:
        ours["tags"] = tags
    mine = manifest.find_resource(ours, "PRODUCT")
    new_url, new_sha = str(product["url"]), ib_sha(product)
    if mine.get("url") != new_url or manifest.sha256_of(mine) != new_sha:
        changes.append(f"PRODUCT {mine.get('url')} -> {new_url} sha256:{new_sha}")
        mine["url"] = new_url
        mine["filename"] = new_url.rsplit("/", 1)[-1]
        mine["validation"] = {"type": "sha256", "value": new_sha}
    # Any other resource Iron Bank pins under the same filename shape (tini-amd64, git-*.tar.xz, ...).
    by_name = {str(r.get("filename", "")): r for r in ib.get("resources") or []}
    for res in ours["resources"]:
        arg = manifest.resource_arg(res)
        if arg == "PRODUCT":
            continue
        ib_res = by_name.get(str(res.get("filename", "")))
        if ib_res is None:
            stem = re.sub(r"[\d.]+", "", str(res.get("filename", "")))
            cands = [r for n, r in by_name.items() if re.sub(r"[\d.]+", "", n) == stem and stem]
            ib_res = cands[0] if len(cands) == 1 else None
        if ib_res is None:
            continue
        try:
            sha = ib_sha(ib_res)
        except SyncError:
            continue
        url = str(ib_res.get("url", res.get("url")))
        if res.get("url") != url or manifest.sha256_of(res) != sha:
            changes.append(f"{arg} {res.get('url')} -> {url} sha256:{sha}")
            res["url"] = url
            res["filename"] = str(ib_res.get("filename", url.rsplit("/", 1)[-1]))
            res["validation"] = {"type": "sha256", "value": sha}
    ours.setdefault("upstream", {}).setdefault("ironbank", {})["synced_version"] = version
    return changes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("repo"); p.add_argument("target"); p.add_argument("--base", default=None)
    p = sub.add_parser("vcs-url"); p.add_argument("target"); p.add_argument("--art", required=True); p.add_argument("--vcs-repo", required=True); p.add_argument("--template", default=None); p.add_argument("--archive", action="store_true")
    p = sub.add_parser("apply"); p.add_argument("target"); p.add_argument("file")
    a = ap.parse_args(argv)

    path, ours = manifest.load(a.target)
    if a.cmd == "repo":
        up = upstream(ours)
        print(clone_url(ours, a.base), up["ref"], up["manifest"])
        return 0
    if a.cmd == "vcs-url":
        print(vcs_url(ours, a.art, a.vcs_repo, a.template or (VCS_ARCHIVE_TEMPLATE if a.archive else None)))
        return 0
    ib = yaml.safe_load(Path(a.file).read_text()) or {}
    line = Path(a.target).name if "/" in a.target.strip("/") else "lts"
    changes = apply(ours, ib, line)
    if changes:
        manifest.save(path, ours)
        print(f"changed {path}:")
        for c in changes:
            print(f"  - {c}")
    else:
        print(f"unchanged {path} (Iron Bank {upstream(ours)['repo']}@{upstream(ours)['ref']} pins {ours['args']['VERSION']})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SyncError, manifest.ManifestError) as exc:
        print(f"ironbank: {exc}", file=sys.stderr)
        sys.exit(2)
