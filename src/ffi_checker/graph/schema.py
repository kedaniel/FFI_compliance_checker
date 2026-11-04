"""Turn an EcuModel into a property graph: nodes + relationships.

What is a property graph?
    - A NODE is a thing, with a LABEL saying what kind of thing it is
      (Core, OsApplication, Task, Runnable, SwComponent) and PROPERTIES
      (name, path, asil, trusted, ...).
    - A RELATIONSHIP is a directed, named link between two nodes, e.g.
      (OsApplication)-[:RUNS_ON]->(Core).

Why a graph for FFI?
    FFI questions are "can X reach / interfere with Y?" questions. In a graph
    those are path queries, which are short to write and fast to run, even when
    an ECU has thousands of runnables. Later milestones add Variables, MemMap
    sections and MPU regions as more nodes, and the same style of query keeps working.

Our schema:

  milestone 2 (from ARXML)
    (SwComponent)-[:HAS_RUNNABLE]->(Runnable)-[:MAPPED_TO]->(Task)
    (OsApplication)-[:OWNS_TASK]->(Task)
    (OsApplication)-[:RUNS_ON]->(Core)

  milestone 3 (from generated C code + linker map, optional)
    (SwComponent)-[:OWNS_VARIABLE]->(Variable)
    (Runnable)-[:READS]->(Variable)
    (Runnable)-[:WRITES {kind}]->(Variable)       kind = "write" or "address-of"
    (Variable)-[:IN_SECTION]->(MemorySection)-[:PLACED_IN]->(MemoryRegion)

This module has no database code, so it is easy to test. `loader.py` writes the
result into Neo4j.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..code.link import link_code
from ..code.model import CodeModel
from ..model import EcuModel

# Every node label we use, and the relationship types with their (from, to) labels.
NODE_LABELS = [
    "Core", "OsApplication", "Task", "Runnable", "SwComponent",
    "Variable", "MemorySection", "MemoryRegion",
]
REL_TYPES = {
    "HAS_RUNNABLE": ("SwComponent", "Runnable"),
    "MAPPED_TO": ("Runnable", "Task"),
    "OWNS_TASK": ("OsApplication", "Task"),
    "RUNS_ON": ("OsApplication", "Core"),
    "OWNS_VARIABLE": ("SwComponent", "Variable"),
    "READS": ("Runnable", "Variable"),
    "WRITES": ("Runnable", "Variable"),
    "IN_SECTION": ("Variable", "MemorySection"),
    "PLACED_IN": ("MemorySection", "MemoryRegion"),
}


class Node(BaseModel):
    label: str
    path: str  # unique key, the AUTOSAR path
    props: dict[str, Any]


class Rel(BaseModel):
    type: str
    src: str  # path of the start node
    dst: str  # path of the end node
    props: dict[str, Any] = {}  # optional properties on the relationship


class Graph(BaseModel):
    nodes: list[Node]
    rels: list[Rel]

    def nodes_with_label(self, label: str) -> list[Node]:
        return [n for n in self.nodes if n.label == label]

    def rels_of_type(self, rel_type: str) -> list[Rel]:
        return [r for r in self.rels if r.type == rel_type]


def to_graph(model: EcuModel, code: CodeModel | None = None) -> Graph:
    """Build the graph from the ECU model and, optionally, the code model."""
    nodes: list[Node] = []
    rels: list[Rel] = []

    for c in model.cores.values():
        nodes.append(Node(label="Core", path=c.path, props={"name": c.name, "core_id": c.core_id}))

    for a in model.os_applications.values():
        nodes.append(
            Node(label="OsApplication", path=a.path, props={"name": a.name, "trusted": a.trusted})
        )
        if a.core:
            rels.append(Rel(type="RUNS_ON", src=a.path, dst=a.core))
        for t in a.tasks:
            if t in model.tasks:
                rels.append(Rel(type="OWNS_TASK", src=a.path, dst=t))

    for t in model.tasks.values():
        nodes.append(Node(label="Task", path=t.path, props={"name": t.name}))

    for s in model.swcs.values():
        props: dict[str, Any] = {"name": s.name}
        if s.asil is not None:
            # Store both: the text for humans, the rank (QM=0..D=4) for comparisons in queries.
            props["asil"] = s.asil.value
            props["asil_rank"] = s.asil.rank
        nodes.append(Node(label="SwComponent", path=s.path, props=props))

    for r in model.runnables.values():
        nodes.append(Node(label="Runnable", path=r.path, props={"name": r.name}))
        if r.swc:
            rels.append(Rel(type="HAS_RUNNABLE", src=r.swc, dst=r.path))
        if r.task:
            rels.append(Rel(type="MAPPED_TO", src=r.path, dst=r.task))

    if code is not None:
        _add_code(model, code, nodes, rels)

    return Graph(nodes=nodes, rels=rels)


def _add_code(model: EcuModel, code: CodeModel, nodes: list[Node], rels: list[Rel]) -> None:
    links = link_code(model, code)

    for r in code.regions.values():
        nodes.append(Node(label="MemoryRegion", path=f"region:{r.name}",
                          props={"name": r.name, "origin": r.origin, "length": r.length}))
    for ls in code.link_sections.values():
        nodes.append(Node(label="MemorySection", path=f"section:{ls.name}",
                          props={"name": ls.name, "address": ls.address, "size": ls.size}))
        if ls.region:
            rels.append(Rel(type="PLACED_IN", src=f"section:{ls.name}", dst=f"region:{ls.region}"))

    for v in code.variables.values():
        props = {"name": v.name, "file": v.file, "type": v.type}
        if v.section:
            props["memmap_section"] = v.section
        nodes.append(Node(label="Variable", path=v.path, props=props))
        placed = code.link_section_of(v)
        if placed:
            rels.append(Rel(type="IN_SECTION", src=v.path, dst=f"section:{placed.name}"))
        if v.path in links.owners:
            rels.append(Rel(type="OWNS_VARIABLE", src=links.owners[v.path], dst=v.path))

    by_pair: dict[tuple[str, str], set[str]] = {}
    for runnable, variable, kind in links.accesses:
        by_pair.setdefault((runnable, variable), set()).add(kind)
    for (runnable, variable), kinds in by_pair.items():
        if "read" in kinds:
            rels.append(Rel(type="READS", src=runnable, dst=variable))
        if "write" in kinds or "address-of" in kinds:
            kind = "write" if "write" in kinds else "address-of"
            rels.append(Rel(type="WRITES", src=runnable, dst=variable, props={"kind": kind}))
