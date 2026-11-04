"""What we read from a TASKING linker map: where every section and symbol ended up.

Every row remembers its `line` number in the map file. That is what makes a finding
traceable: "see synthetic_tc39x.map line 144" is evidence an assessor can check.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MapSection(BaseModel):
    """One output section placed by the locator (a row of the 'Locate Result' table)."""

    chip: str
    group: str  # linker group, e.g. "ASIL_D_DATA_tc0". Empty for code in flash.
    name: str  # without the "(104)" id, e.g. ".bss.SafetyMon.SafetyMon_State"
    section_id: int | None
    size: int
    address: int
    alignment: int
    line: int

    def _parts(self) -> list[str]:
        parts = self.name.split(".")
        return parts if self.name.startswith(".") and len(parts) >= 4 else []

    @property
    def kind(self) -> str | None:
        """'bss', 'data' or 'text'. None for stacks, pads and other special sections."""
        p = self._parts()
        return p[1] if p else None

    @property
    def module(self) -> str | None:
        """Object file the section came from. Names look like .<kind>.<Module>.<Symbol>."""
        p = self._parts()
        return p[2] if p else None

    @property
    def symbol(self) -> str | None:
        p = self._parts()
        return ".".join(p[3:]) if p else None


class MapSymbol(BaseModel):
    name: str
    address: int
    size: int | None  # group boundary symbols (_lc_gb_/_lc_ge_) have no size
    section: str | None
    line: int


class CrossRef(BaseModel):
    symbol: str
    defined_in: str  # object file, e.g. "SafetyMon.o"
    section: str
    referenced_in: list[str]
    line: int

    @staticmethod
    def module_of(obj_file: str) -> str:
        return obj_file[:-2] if obj_file.endswith(".o") else obj_file


class GroupRange(BaseModel):
    """One row of 'Locate Rules': the address range the locator gave to a group."""

    group: str
    properties: str
    start: int
    end: int  # exclusive
    size: int
    line: int


class MapModel(BaseModel):
    source: str = ""  # file name, used in evidence
    sections: list[MapSection] = Field(default_factory=list)
    symbols: dict[str, MapSymbol] = Field(default_factory=dict)
    xrefs: list[CrossRef] = Field(default_factory=list)
    group_ranges: dict[str, GroupRange] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    def ref(self, line: int) -> str:
        """Evidence pointer such as 'synthetic_tc39x.map:144'."""
        return f"{self.source}:{line}"
