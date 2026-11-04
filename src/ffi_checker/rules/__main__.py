"""Run the memory-FFI rules on a linker map and a partition spec.

    python -m ffi_checker.rules --map examples/tc39x/synthetic_tc39x.map --spec examples/tc39x/partition_spec.json
    ... --expected examples/tc39x/expected_findings.json     compare with a known answer
    ... --out report.json                                   write the evidence report

Exit code: 0 = ok, 1 = errors found (only with --strict), 2 = does not match --expected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from ..linkmap import parse_tasking_map
from ..spec import load_spec
from . import compare, run_rules
from .model import Finding


def sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tool_version() -> str:
    try:
        return metadata.version("ffi-checker")
    except metadata.PackageNotFoundError:
        return "unknown"


def build_report(findings: list[Finding], inputs: dict[str, str]) -> dict:
    """The audit record: what was checked, with which tool, and what was found and why."""
    return {
        "tool": {"name": "ffi-checker", "version": tool_version()},
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "llm_used": False,  # verdicts come from deterministic rules only
        "inputs": {name: {"path": p, "sha256": sha256(p)} for name, p in inputs.items()},
        "summary": {
            "errors": sum(f.severity == "error" for f in findings),
            "warnings": sum(f.severity == "warning" for f in findings),
        },
        "findings": [{"id": f.fingerprint, **f.model_dump(exclude_none=True)} for f in findings],
    }


def print_findings(findings: list[Finding]) -> None:
    for f in findings:
        print(f"\n[{f.severity.upper()}] {f.rule}  {f.fingerprint}")
        print(f"  {f.detail}")
        for e in f.evidence:
            print(f"    evidence: {e.source}  {e.text}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ffi_checker.rules", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--map", required=True, help="TASKING linker map")
    p.add_argument("--spec", required=True, help="partition specification (JSON)")
    p.add_argument("--expected", help="expected findings (JSON) to compare with")
    p.add_argument("--out", help="write the evidence report (JSON) here")
    p.add_argument("--strict", action="store_true", help="exit 1 if any error is found")
    args = p.parse_args(argv)

    m, spec = parse_tasking_map(args.map), load_spec(args.spec)
    findings = run_rules(m, spec)
    for w in m.warnings:
        print(f"map warning: {w}")

    print_findings(findings)
    errors = sum(f.severity == "error" for f in findings)
    print(f"\n{errors} error(s), {len(findings) - errors} warning(s) on {spec.target or 'target'}")

    if args.out:
        inputs = {"map": args.map, "spec": args.spec}
        Path(args.out).write_text(json.dumps(build_report(findings, inputs), indent=2), encoding="utf-8")
        print(f"Evidence report written to {args.out}")

    if args.expected:
        c = compare(findings, args.expected)
        print(f"\nComparison with {Path(args.expected).name}: matched {len(c.matched)}, "
              f"missing {len(c.missing)}, unexpected {len(c.unexpected)}, "
              f"severity mismatches {len(c.severity_mismatch)}")
        for label, items in (("missing", c.missing), ("unexpected", c.unexpected),
                             ("severity", c.severity_mismatch)):
            for item in items:
                print(f"  {label}: {item}")
        if not c.ok:
            return 2
    return 1 if args.strict and errors else 0


if __name__ == "__main__":
    sys.exit(main())
