"""Read the linker map: memory regions and where each section was placed.

The demo uses a SIMPLIFIED text format (see examples/demo_ecu/DemoEcu.map):

    MEMORY  <region>  origin=0x70000000 length=0x4000
    SECTION <name>    address=0x70000000 size=0x1 [region=<region>]

The real TASKING map file looks different. Keeping this behind one function
(`parse_map`) means that adding a real TASKING parser later changes only this file.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import CodeModel, LinkSection, MemoryRegion


def _kv(parts: list[str]) -> dict[str, str]:
    return dict(p.split("=", 1) for p in parts if "=" in p)


def parse_map(path: str | Path, model: CodeModel | None = None) -> CodeModel:
    """Add regions and linker sections from `path` to `model` (a new one if None)."""
    model = model or CodeModel()
    for n, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        try:
            if parts[0] == "MEMORY":
                kv = _kv(parts[2:])
                model.regions[parts[1]] = MemoryRegion(
                    name=parts[1], origin=int(kv["origin"], 16), length=int(kv["length"], 16)
                )
            elif parts[0] == "SECTION":
                kv = _kv(parts[2:])
                model.link_sections[parts[1]] = LinkSection(
                    name=parts[1], address=int(kv["address"], 16), size=int(kv["size"], 16),
                    region=kv.get("region"),
                )
            else:
                model.warnings.append(f"{Path(path).name}:{n}: unknown line '{line}'")
        except (KeyError, ValueError, IndexError) as e:
            model.warnings.append(f"{Path(path).name}:{n}: cannot read '{line}' ({e!r})")

    # A section without an explicit region gets the region that contains its address.
    for ls in model.link_sections.values():
        if ls.region is None:
            ls.region = next((r.name for r in model.regions.values() if r.contains(ls.address)), None)
    return model
