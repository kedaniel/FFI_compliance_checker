"""The partition specification: what the memory layout is SUPPOSED to be.

The map file says where things ARE. The spec says where they SHOULD be: which linker
groups belong to which partition, which software modules may live there, what ASIL each
module has, and the rules to check. In a real project this information comes from the
safety concept and from the OS / MPU configuration (later we derive more of it from ARXML).
Today it is a JSON file, see examples/tc39x/partition_spec.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

ASIL_RANK = {"QM": 0, "A": 1, "B": 2, "C": 3, "D": 4}
PLATFORM_CLASSES = {"OS", "BSW"}  # not ASIL levels: "inherit the partition they are listed in"


class Partition(BaseModel):
    name: str
    core: int
    asil: str
    trusted: bool
    protection_set: str
    groups: list[str]
    modules: list[str]


class SharedGroup(BaseModel):
    group: str
    allowed_asil: list[str]
    writable_by: list[str] = Field(default_factory=list)
    note: str | None = None

    @property
    def is_wildcard(self) -> bool:
        return "wildcard" in self.group.lower()


class GuardPad(BaseModel):
    min_bytes: int
    between: list[str]  # two group name templates, {n} = core number
    group: str = "Mpu_ReservedCorePad_tc{n}"  # name of the pad group (convention in the map)


class Mpu(BaseModel):
    granularity_bytes: int = 8
    region_symbols: str = ""


class Spec(BaseModel):
    target: str = ""
    map_file: str = ""
    mpu: Mpu = Field(default_factory=Mpu)
    guard_pad: GuardPad
    module_asil: dict[str, str]
    partitions: list[Partition]
    shared_groups: list[SharedGroup] = Field(default_factory=list)
    rules: dict[str, str] = Field(default_factory=dict)  # rule id -> text, quoted in findings

    def partition_of_group(self, group: str) -> Partition | None:
        return next((p for p in self.partitions if group in p.groups), None)

    def shared_group(self, group: str) -> SharedGroup | None:
        return next((s for s in self.shared_groups if s.group == group), None)

    def cores(self) -> list[int]:
        return sorted({p.core for p in self.partitions})

    def partition_of_module(self, module: str) -> Partition | None:
        return next((p for p in self.partitions if module in p.modules), None)


def asil_rated(asil: str | None) -> bool:
    """True for A, B, C, D. QM, OS, BSW and unknown are not 'ASIL-rated'."""
    return asil in ASIL_RANK and asil != "QM"


def load_spec(path: str | Path) -> Spec:
    return Spec.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
