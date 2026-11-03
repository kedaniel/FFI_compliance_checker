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

Our schema (milestone 2):

    (SwComponent)-[:HAS_RUNNABLE]->(Runnable)-[:MAPPED_TO]->(Task)
    (OsApplication)-[:OWNS_TASK]->(Task)
    (OsApplication)-[:RUNS_ON]->(Core)

This module has no database code, so it is easy to test. `loader.py` writes the
result into Neo4j.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..model import EcuModel

# Every node label we use, and the relationship types with their (from, to) labels.
NODE_LABELS = ["Core", "OsApplication", "Task", "Runnable", "SwComponent"]
REL_TYPES = {
    "HAS_RUNNABLE": ("SwComponent", "Runnable"),
    "MAPPED_TO": ("Runnable", "Task"),
    "OWNS_TASK": ("OsApplication", "Task"),
    "RUNS_ON": ("OsApplication", "Core"),
}


class Node(BaseModel):
    label: str
    path: str  # unique key, the AUTOSAR path
    props: dict[str, Any]


class Rel(BaseModel):
    type: str
    src: str  # path of the start node
    dst: str  # path of the end node


class Graph(BaseModel):
    nodes: list[Node]
    rels: list[Rel]

    def nodes_with_label(self, label: str) -> list[Node]:
        return [n for n in self.nodes if n.label == label]

    def rels_of_type(self, rel_type: str) -> list[Rel]:
        return [r for r in self.rels if r.type == rel_type]


def to_graph(model: EcuModel) -> Graph:
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

    return Graph(nodes=nodes, rels=rels)
