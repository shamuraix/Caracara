#!/usr/bin/env python3
"""Validate .trivyignore.yaml: every entry needs a statement and an expiry, and
no entry may be past its expiry.  Trivy itself stops honouring expired entries,
but leaving them in place hides the fact that an exception lapsed; this makes
the pipeline fail until someone removes or renews it (in a merge request).

Usage: check_trivyignore.py [.trivyignore.yaml] [--max-days N] [--today YYYY-MM-DD]
Exit 0 when valid, 1 otherwise.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

SECTIONS = ("vulnerabilities", "misconfigurations", "secrets", "licenses")


def parse_date(value) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


def validate(doc: dict | None, today: dt.date, max_days: int) -> list[str]:
    problems: list[str] = []
    if doc is None:
        return problems
    if not isinstance(doc, dict):
        return ["top level must be a mapping with vulnerabilities:/misconfigurations:/secrets:/licenses:"]
    unknown = set(doc) - set(SECTIONS)
    if unknown:
        problems.append(f"unknown top-level keys: {', '.join(sorted(unknown))}")
    for section in SECTIONS:
        entries = doc.get(section) or []
        if not isinstance(entries, list):
            problems.append(f"{section}: must be a list")
            continue
        for i, entry in enumerate(entries):
            where = f"{section}[{i}]"
            if not isinstance(entry, dict) or "id" not in entry:
                problems.append(f"{where}: needs an id")
                continue
            where = f"{section}[{i}] {entry['id']}"
            if not str(entry.get("statement", "")).strip():
                problems.append(f"{where}: needs a statement (why it is not exploitable or who tracks it)")
            if "expired_at" not in entry:
                problems.append(f"{where}: needs expired_at (time-boxed exceptions only)")
                continue
            try:
                expiry = parse_date(entry["expired_at"])
            except (ValueError, TypeError):
                problems.append(f"{where}: expired_at is not a date: {entry['expired_at']!r}")
                continue
            if expiry <= today:
                problems.append(f"{where}: expired on {expiry.isoformat()}; remove or renew it")
            elif (expiry - today).days > max_days:
                problems.append(f"{where}: expires {expiry.isoformat()}, more than {max_days} days out")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default=".trivyignore.yaml")
    ap.add_argument("--max-days", type=int, default=90, help="longest allowed exception window (default 90)")
    ap.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f"{path}: not found (nothing to check)")
        return 0
    doc = yaml.safe_load(path.read_text())
    problems = validate(doc, args.today, args.max_days)
    if problems:
        print(f"{path}: {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
        return 1
    count = sum(len(doc.get(s) or []) for s in SECTIONS) if isinstance(doc, dict) else 0
    print(f"{path}: ok ({count} time-boxed exception(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
