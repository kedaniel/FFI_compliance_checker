"""Parse the tables of a TASKING linker map (.map).

The map is plain text with boxed tables like

    +-----------------------------------+
    | Group     | Section      | Size   |     <- header row
    |===================================|     <- separator
    | QM_DATA   | .bss.X.Y (12)| 0x10   |     <- data rows
    +-----------------------------------+

We recognise a table by its header cells, so the order of the tables in the file and extra
tables we do not know are both harmless. Tables we use:

    Locate Result  (sections)  -> MapSection   which group each section is in, address, size
    Symbols                    -> MapSymbol    incl. _lc_gb_<group> / _lc_ge_<group> boundaries
    Cross References           -> CrossRef     which object files use which symbol
    Locate Rules               -> GroupRange   start / end / size of every group

Needs the map to be produced with `--map-file-format=+sections,+symbols,+crossref`.
This was written against a SYNTHETIC sample map. Real maps differ in details (for example
other columns or spaces), which the warnings list will show; adapt the header sets below.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import CrossRef, GroupRange, MapModel, MapSection, MapSymbol

HEADERS = {
    "sections": ("Chip", "Group", "Section", "Size (MAU)", "Space addr", "Chip addr", "Alignment"),
    "symbols": ("Name", "Space addr", "Size", "Section"),
    "xrefs": ("Symbol", "Defined in", "Definition section", "Referenced in"),
    "ranges": ("Group", "Properties", "Start", "End (excl.)", "Size"),
}
SECTION_ID = re.compile(r"^(.*?)\s*\((\d+)\)$")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _hex(text: str) -> int:
    return int(text, 16)


def parse_tasking_map(path: str | Path) -> MapModel:
    path = Path(path)
    model = MapModel(source=path.name)
    table: str | None = None

    for n, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = raw.strip()
        if not line.startswith("|"):
            table = None  # a border, heading or blank line ends the current table
            continue
        cells = _cells(line)
        if set(line) <= set("|= "):
            continue  # the |=====| separator under the header
        header = next((k for k, h in HEADERS.items() if tuple(cells) == h), None)
        if header:
            table = header
            continue
        if table is None:
            continue
        try:
            _add_row(model, table, cells, n)
        except (ValueError, IndexError) as e:
            model.warnings.append(f"{path.name}:{n}: cannot read {table} row ({e})")
    if not model.sections:
        model.warnings.append(f"{path.name}: no 'Locate Result' section table found")
    return model


def _add_row(model: MapModel, table: str, c: list[str], line: int) -> None:
    if table == "sections":
        m = SECTION_ID.match(c[2])
        name, sid = (m.group(1), int(m.group(2))) if m else (c[2], None)
        model.sections.append(MapSection(
            chip=c[0], group=c[1], name=name, section_id=sid,
            size=_hex(c[3]), address=_hex(c[4]), alignment=_hex(c[6]), line=line,
        ))
    elif table == "symbols":
        model.symbols[c[0]] = MapSymbol(
            name=c[0], address=_hex(c[1]), size=_hex(c[2]) if c[2] else None,
            section=c[3] or None, line=line,
        )
    elif table == "xrefs":
        model.xrefs.append(CrossRef(
            symbol=c[0], defined_in=c[1], section=c[2],
            referenced_in=[x.strip() for x in c[3].split(",") if x.strip()], line=line,
        ))
    elif table == "ranges":
        model.group_ranges[c[0]] = GroupRange(
            group=c[0], properties=c[1], start=_hex(c[2]), end=_hex(c[3]), size=_hex(c[4]), line=line,
        )
