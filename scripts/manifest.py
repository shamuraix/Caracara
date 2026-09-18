#!/usr/bin/env python3
"""Read and update a product's hardening_manifest.yaml (Iron Bank format).

The manifest is the single source of truth for everything that enters an
image from outside the base OS repos: the product tarball, the tini binary,
git's source tarball for Bitbucket, and the copa/crane binaries for ci-tools.
Every resource carries an upstream URL and a sha256; the build passes both to
the Dockerfile, where `ADD --checksum` refuses anything that does not match.

Subcommands
  version    <dir>                          print args.VERSION
  arg        <dir> <NAME>                   print one build arg
  build-args <dir> [--art HOST] [--shell]   print `--opt build-arg:K=V` lines (or K=V with --shell)
  check      <dir>                          exit 1 and list resources without a sha256
  url        <dir> <ARG> [--art HOST]       print a resource's (mirrored) URL
  set-resource <dir> <ARG> [--url U] [--sha256 S]   update a resource in place
  set-arg    <dir> <NAME> <VALUE>           update args.NAME in place

Upstream hosts are rewritten to Artifactory generic remotes (RESOURCE_MIRRORS,
"host=https://art/artifactory/repo,..." or the built-in map) so neither the
runner nor buildkitd ever reaches the internet.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

try:
    import yaml
except ImportError:  # pragma: no cover - environment problem, not a code path
    sys.exit(
        "error: the PyYAML module is not installed.\n"
        "  workstation: python3 -m pip install -r requirements.txt   (or: make deps)\n"
        "  UBI/RHEL:    microdnf install python3-pyyaml\n"
        "  Debian:      apt install python3-yaml"
    )

MANIFEST = "hardening_manifest.yaml"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_MIRRORS = {
    "product-downloads.atlassian.com": "{art}/artifactory/generic-atlassian-remote",
    "github.com": "{art}/artifactory/generic-github-remote",
    "objects.githubusercontent.com": "{art}/artifactory/generic-github-remote",
    "mirrors.edge.kernel.org": "{art}/artifactory/generic-kernel-remote",
    "www.kernel.org": "{art}/artifactory/generic-kernel-remote",
    "cdn.kernel.org": "{art}/artifactory/generic-kernel-remote",
}


class ManifestError(RuntimeError):
    pass


def load(dir_: str | Path) -> tuple[Path, dict]:
    path = Path(dir_) / MANIFEST
    if not path.exists():
        raise ManifestError(f"{path} not found")
    doc = yaml.safe_load(path.read_text()) or {}
    doc.setdefault("args", {})
    doc.setdefault("resources", [])
    return path, doc


def save(path: Path, doc: dict) -> None:
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120))


def mirrors(art: str | None) -> dict[str, str]:
    """host -> base URL prefix, from RESOURCE_MIRRORS or the defaults."""
    art = art or os.environ.get("ART", "artifactory.example.com")
    env = os.environ.get("RESOURCE_MIRRORS", "").strip()
    if env:
        out = {}
        for pair in env.split(","):
            host, _, base = pair.partition("=")
            if host and base:
                out[host.strip()] = base.strip().rstrip("/")
        return out
    return {host: "https://" + tpl.format(art=art) for host, tpl in DEFAULT_MIRRORS.items()}


def mirror_url(url: str, art: str | None = None, direct: bool = False) -> str:
    if direct:
        return url
    parts = urlsplit(url)
    base = mirrors(art).get(parts.netloc)
    if not base:
        return url
    return f"{base}{parts.path}" + (f"?{parts.query}" if parts.query else "")


def resource_arg(res: dict) -> str:
    """Build-arg stem for a resource: explicit `arg:` or sanitized filename."""
    if res.get("arg"):
        return str(res["arg"])
    stem = re.sub(r"[^A-Za-z0-9]+", "_", str(res.get("filename", ""))).strip("_").upper()
    if not stem:
        raise ManifestError(f"resource without arg/filename: {res}")
    return stem


def find_resource(doc: dict, arg: str) -> dict:
    for res in doc["resources"]:
        if resource_arg(res) == arg:
            return res
    raise ManifestError(f"no resource with arg {arg}")


def sha256_of(res: dict) -> str:
    val = (res.get("validation") or {}).get("value") or ""
    return str(val).strip().lower()


def unpinned(doc: dict) -> list[str]:
    return [resource_arg(r) for r in doc["resources"] if not SHA256_RE.match(sha256_of(r))]


def build_args(doc: dict, art: str | None = None, direct: bool = False) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (doc.get("args") or {}).items():
        out[str(k)] = "" if v is None else str(v)
    for res in doc["resources"]:
        stem = resource_arg(res)
        out[f"{stem}_URL"] = mirror_url(str(res["url"]), art, direct)
        out[f"{stem}_SHA256"] = sha256_of(res)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("version"); p.add_argument("dir")
    p = sub.add_parser("arg"); p.add_argument("dir"); p.add_argument("name")
    p = sub.add_parser("build-args"); p.add_argument("dir"); p.add_argument("--art"); p.add_argument("--direct", action="store_true"); p.add_argument("--shell", action="store_true")
    p = sub.add_parser("check"); p.add_argument("dir")
    p = sub.add_parser("url"); p.add_argument("dir"); p.add_argument("arg"); p.add_argument("--art"); p.add_argument("--direct", action="store_true")
    p = sub.add_parser("set-resource"); p.add_argument("dir"); p.add_argument("arg"); p.add_argument("--url"); p.add_argument("--sha256")
    p = sub.add_parser("set-arg"); p.add_argument("dir"); p.add_argument("name"); p.add_argument("value")
    a = ap.parse_args(argv)

    path, doc = load(a.dir)
    if a.cmd == "version":
        v = doc["args"].get("VERSION")
        if not v:
            raise ManifestError(f"{path}: args.VERSION missing")
        print(v)
    elif a.cmd == "arg":
        if a.name not in doc["args"]:
            raise ManifestError(f"{path}: args.{a.name} missing")
        print(doc["args"][a.name])
    elif a.cmd == "build-args":
        for k, v in build_args(doc, a.art, a.direct).items():
            print(f"{k}={v}" if a.shell else f"--opt=build-arg:{k}={v}")
    elif a.cmd == "check":
        missing = unpinned(doc)
        if missing:
            print(f"{path}: unpinned resources (run scripts/pin-resource.sh {str(a.dir).rstrip('/')} {' '.join(missing)}):")
            for m in missing:
                print(f"  - {m}")
            return 1
        print(f"{path}: {len(doc['resources'])} resource(s) pinned")
    elif a.cmd == "url":
        print(mirror_url(str(find_resource(doc, a.arg)["url"]), a.art, a.direct))
    elif a.cmd == "set-resource":
        res = find_resource(doc, a.arg)
        if a.url:
            res["url"] = a.url
            res["filename"] = res.get("filename") or a.url.rsplit("/", 1)[-1]
        if a.sha256 is not None:
            if a.sha256 and not SHA256_RE.match(a.sha256):
                raise ManifestError(f"not a sha256: {a.sha256}")
            res["validation"] = {"type": "sha256", "value": a.sha256}
        save(path, doc)
        print(f"{path}: {a.arg} -> {res['url']} sha256:{sha256_of(res) or '<unpinned>'}")
    elif a.cmd == "set-arg":
        doc["args"][a.name] = a.value
        save(path, doc)
        print(f"{path}: args.{a.name} = {a.value}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ManifestError as exc:
        print(f"manifest: {exc}", file=sys.stderr)
        sys.exit(2)
