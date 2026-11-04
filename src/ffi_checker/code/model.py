"""Facts extracted from generated C code and the linker map.

Two sources, two kinds of facts:

  C sources  ->  which VARIABLES exist, in which MemMap section they are declared,
                 and which FUNCTIONS read or write them.
  Map file   ->  where the linker actually PUT each section (address, memory region).

Put together:  function -> variable -> MemMap section -> linker section -> memory region.
That is the second half of the memory-FFI chain (the first half, SWC -> partition,
came from the ARXML in milestone 1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AccessKind = Literal["read", "write", "address-of"]


class Variable(BaseModel):
    name: str
    path: str  # "<file>::<name>", unique even if two files use the same static name
    file: str
    type: str
    # Section as the MemMap macros name it: "<PREFIX>_<SECTION>", e.g.
    # "BRAKECTRL_VAR_ZERO_INIT_8BIT". None = defined outside any MemMap section.
    section: str | None = None


class Access(BaseModel):
    variable: str  # Variable.path
    kind: AccessKind


class Function(BaseModel):
    name: str
    file: str
    accesses: list[Access] = Field(default_factory=list)


class MemoryRegion(BaseModel):
    name: str
    origin: int
    length: int

    def contains(self, address: int) -> bool:
        return self.origin <= address < self.origin + self.length


class LinkSection(BaseModel):
    name: str  # e.g. ".bss.BRAKECTRL_VAR_ZERO_INIT_8BIT"
    address: int
    size: int
    region: str | None = None  # MemoryRegion.name


class CodeModel(BaseModel):
    variables: dict[str, Variable] = Field(default_factory=dict)  # by path
    functions: dict[str, Function] = Field(default_factory=dict)  # by "<file>::<name>"
    regions: dict[str, MemoryRegion] = Field(default_factory=dict)
    link_sections: dict[str, LinkSection] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    def link_section_of(self, variable: Variable) -> LinkSection | None:
        """The linker section that holds this variable, or None if it cannot be found.

        Convention used here: the linker section name ends with the MemMap section
        name, e.g. ".bss.BRAKECTRL_VAR_ZERO_INIT_8BIT". In real MICROSAR projects the
        link is made by `#pragma section` lines in the *_MemMap.h files. Reading those
        is a later improvement.
        """
        if variable.section is None:
            return None
        key = variable.section.lower()
        for ls in self.link_sections.values():
            if ls.name.lower().endswith(key):
                return ls
        return None
