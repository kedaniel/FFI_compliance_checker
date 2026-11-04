"""A finding is a claim with evidence. Evidence is what an assessor can check."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source: str  # "synthetic_tc39x.map:144" or "partition_spec.json: partitions[QM_Core0]"
    text: str


class Finding(BaseModel):
    rule: str  # e.g. "R1_placement"
    severity: Literal["error", "warning"]
    detail: str
    symbol: str | None = None
    module: str | None = None
    group: str | None = None
    address: str | None = None  # hex text, e.g. "0x6000556c"
    referenced_by: str | None = None
    rule_text: str = ""  # the rule as written in the spec
    evidence: list[Evidence] = Field(default_factory=list)

    @property
    def key(self) -> tuple:
        """Identity used to compare findings with expected ones.

        R3 is about a group, R4 about a symbol and who references it, all others about a symbol.
        """
        if self.rule.startswith("R3"):
            return (self.rule, self.group)
        if self.rule.startswith("R4"):
            return (self.rule, self.symbol, self.referenced_by)
        return (self.rule, self.symbol)

    @property
    def fingerprint(self) -> str:
        return ":".join(str(k) for k in self.key if k)
