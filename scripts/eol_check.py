#!/usr/bin/env python3
"""Report days until the base OS and each Atlassian product line leave support.

Reads support-windows.yaml.  Exit 1 when anything is already out of support or
closer than --fail-within days (default 30); warn when closer than --warn-within
(default 90).  Used as a pipeline step so the "EOL clock" is visible on every
build, not only when Trivy finally flags the OS.

Usage: eol_check.py [support-windows.yaml] [--today YYYY-MM-DD] [--json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import yaml


def parse_date(value) -> dt.date | None:
    if value in (None, "", "unknown"):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


def evaluate(doc: dict, today: dt.date, warn_within: int, fail_within: int) -> list[dict]:
    rows: list[dict] = []

    def add(name: str, phase: str, ends, note: str = ""):
        end = parse_date(ends)
        if end is None:
            rows.append({"name": name, "phase": phase, "ends": None, "days": None, "status": "unknown", "note": note})
            return
        days = (end - today).days
        if days < 0:
            status = "expired"
        elif days <= fail_within:
            status = "fail"
        elif days <= warn_within:
            status = "warn"
        else:
            status = "ok"
        rows.append({"name": name, "phase": phase, "ends": end.isoformat(), "days": days, "status": status, "note": note})

    base = doc.get("base_os") or {}
    if base:
        add(base.get("name", "base OS"), "full support", base.get("full_support_ends"))
        add(base.get("name", "base OS"), "maintenance", base.get("maintenance_ends"))
    for product, info in (doc.get("products") or {}).items():
        line = info.get("line", "?")
        add(f"{product} {line}", "LTS" if info.get("lts") else "feature release", info.get("support_ends"), info.get("note", ""))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default="support-windows.yaml")
    ap.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument("--warn-within", type=int, default=90)
    ap.add_argument("--fail-within", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    doc = yaml.safe_load(Path(args.path).read_text()) or {}
    rows = evaluate(doc, args.today, args.warn_within, args.fail_within)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            days = "n/a" if r["days"] is None else f"{r['days']:>5}d"
            print(f"{r['status']:>8}  {days}  {r['name']} ({r['phase']}) ends {r['ends'] or 'unknown'} {r['note']}".rstrip())
    bad = [r for r in rows if r["status"] in ("expired", "fail")]
    unknown = [r for r in rows if r["status"] == "unknown"]
    if unknown:
        print(f"warning: {len(unknown)} support window(s) unknown; fill them in support-windows.yaml", file=sys.stderr)
    if bad:
        print(f"error: {len(bad)} support window(s) expired or within {args.fail_within} days", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
