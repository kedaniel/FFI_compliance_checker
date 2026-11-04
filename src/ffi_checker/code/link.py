"""Connect the code facts (C + map) to the ECU facts (ARXML).

The bridge is the runnable's SYMBOL: ARXML says "runnable Hmi_Run20ms is implemented by
the C function Hmi_Run20ms", so a C function with that name belongs to that runnable and
therefore to that SW component.

Variable ownership: the SW component whose runnables are implemented in the same .c file
as the variable's definition. A file with no runnables (e.g. shared RTE buffers) has no
owner. A file whose runnables belong to several SW components also gets no owner, with a
warning, because guessing there would hide real findings.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..model import EcuModel
from .model import CodeModel


class CodeLinks(BaseModel):
    owners: dict[str, str] = Field(default_factory=dict)  # variable path -> SwComponent path
    # (runnable path, variable path, "read" | "write" | "address-of")
    accesses: list[tuple[str, str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def link_code(ecu: EcuModel, code: CodeModel) -> CodeLinks:
    links = CodeLinks()
    runnable_by_symbol = {r.symbol: r for r in ecu.runnables.values() if r.symbol}

    swcs_in_file: dict[str, set[str]] = {}
    for func in code.functions.values():
        runnable = runnable_by_symbol.get(func.name)
        if runnable is None:
            continue  # helper function or BSW code, not a runnable
        swcs_in_file.setdefault(func.file, set()).add(runnable.swc)
        seen = set()
        for a in func.accesses:
            if (a.variable, a.kind) not in seen:
                seen.add((a.variable, a.kind))
                links.accesses.append((runnable.path, a.variable, a.kind))

    for var in code.variables.values():
        owners = swcs_in_file.get(var.file, set())
        if len(owners) == 1:
            links.owners[var.path] = next(iter(owners))
        elif len(owners) > 1:
            links.warnings.append(f"{var.path}: file implements runnables of several SWCs, no owner")
    return links
