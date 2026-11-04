"""Compare found findings with an expected list (a test oracle).

Used to prove the rule engine works: the synthetic map was built with known problems and
known non-problems, and the result must match exactly. Extra findings are as bad as missing
ones: a checker that cries wolf is not trusted by safety engineers.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from .model import Finding


class Comparison(BaseModel):
    matched: list[str] = Field(default_factory=list)  # expected ids that were found
    missing: list[str] = Field(default_factory=list)  # expected, not found
    unexpected: list[str] = Field(default_factory=list)  # found, not expected
    severity_mismatch: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing or self.unexpected or self.severity_mismatch)


def _expected_key(e: dict) -> tuple:
    if e["rule"].startswith("R3"):
        return (e["rule"], e.get("group"))
    if e["rule"].startswith("R4"):
        return (e["rule"], e.get("symbol"), e.get("referenced_by"))
    return (e["rule"], e.get("symbol"))


def compare(findings: list[Finding], expected_path: str | Path) -> Comparison:
    expected = json.loads(Path(expected_path).read_text(encoding="utf-8"))["expected_findings"]
    by_key = {f.key: f for f in findings}
    result, seen = Comparison(), set()
    for e in expected:
        key = _expected_key(e)
        found = by_key.get(key)
        if found is None:
            result.missing.append(f"{e['id']} {e['rule']} {key[1:]}")
            continue
        seen.add(key)
        result.matched.append(e["id"])
        if found.severity != e["severity"]:
            result.severity_mismatch.append(f"{e['id']}: expected {e['severity']}, got {found.severity}")
    result.unexpected = [f.fingerprint for f in findings if f.key not in seen]
    return result
