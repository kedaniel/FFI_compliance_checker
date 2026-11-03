"""Milestone 2 tests.

Unit tests (always run): check the graph we build, and that the loader sends
the expected Cypher, using a fake session instead of a real database.

Integration tests (marked `neo4j`): run against a real Neo4j. They are skipped
unless NEO4J_URI is set, e.g.:

    docker compose up -d
    NEO4J_URI=bolt://localhost:7687 pytest -m neo4j
"""

import os
from pathlib import Path

import pytest

from ffi_checker import parse_arxml
from ffi_checker.graph import QUERIES, run_query, to_graph
from ffi_checker.graph.loader import load_graph

DEMO = Path(__file__).parent.parent / "examples" / "demo_ecu" / "DemoEcu.arxml"


@pytest.fixture
def graph():
    return to_graph(parse_arxml([DEMO]))


# ----------------------------------------------------------------- unit tests


def test_node_counts(graph):
    counts = {label: len(graph.nodes_with_label(label)) for label in
              ["Core", "OsApplication", "Task", "Runnable", "SwComponent"]}
    assert counts == {"Core": 2, "OsApplication": 3, "Task": 3, "Runnable": 4, "SwComponent": 4}


def test_relationship_counts(graph):
    assert len(graph.rels_of_type("HAS_RUNNABLE")) == 4
    assert len(graph.rels_of_type("MAPPED_TO")) == 4
    assert len(graph.rels_of_type("OWNS_TASK")) == 3
    assert len(graph.rels_of_type("RUNS_ON")) == 3


def test_every_relationship_points_to_existing_nodes(graph):
    paths = {n.path for n in graph.nodes}
    for r in graph.rels:
        assert r.src in paths and r.dst in paths, r


def test_asil_rank_stored_for_comparisons(graph):
    swc = {n.props["name"]: n.props for n in graph.nodes_with_label("SwComponent")}
    assert swc["BrakeCtrl"]["asil"] == "C" and swc["BrakeCtrl"]["asil_rank"] == 3
    assert swc["HmiGateway"]["asil_rank"] == 0


class FakeSession:
    """Records queries instead of sending them to Neo4j."""

    def __init__(self):
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))


def test_loader_uses_merge_and_batches(graph):
    s = FakeSession()
    load_graph(s, graph, reset=True)
    queries = [q for q, _ in s.calls]
    assert queries[0] == "MATCH (n) DETACH DELETE n"
    assert sum("CREATE CONSTRAINT" in q for q in queries) == 5
    node_loads = [(q, p) for q, p in s.calls if "MERGE (n:" in q]
    assert len(node_loads) == 5  # one batched query per label, not one per node
    assert all("UNWIND $rows" in q for q, _ in node_loads)
    rel_loads = [q for q in queries if "MERGE (a)-[:" in q]
    assert len(rel_loads) == 4


def test_every_query_has_description_and_cypher():
    for name, q in QUERIES.items():
        assert q["description"] and "RETURN" in q["cypher"], name


# ----------------------------------------------------------- integration tests

needs_neo4j = pytest.mark.skipif(not os.environ.get("NEO4J_URI"), reason="NEO4J_URI not set")


@pytest.fixture
def neo4j_session(graph):
    from ffi_checker.graph.loader import connect

    driver = connect()
    with driver.session() as session:
        load_graph(session, graph, reset=True)  # NOTE: wipes the database
        yield session
    driver.close()


@pytest.mark.neo4j
@needs_neo4j
def test_neo4j_mapping(neo4j_session):
    assert len(run_query(neo4j_session, "mapping")) == 4


@pytest.mark.neo4j
@needs_neo4j
def test_neo4j_load_twice_creates_no_duplicates(neo4j_session, graph):
    load_graph(neo4j_session, graph)
    count = neo4j_session.run("MATCH (n) RETURN count(n) AS n").single()["n"]
    assert count == len(graph.nodes)


@pytest.mark.neo4j
@needs_neo4j
def test_neo4j_seeded_issue_found(neo4j_session):
    rows = run_query(neo4j_session, "lower_asil_in_partition")
    assert rows == [{"os_app": "OsApp_AsilC_Core1", "partition_asil": "C",
                     "runnable": "Hmi_Run20ms", "swc": "HmiGateway", "asil": "QM"}]
    mixed = run_query(neo4j_session, "mixed_asil_partitions")
    assert [r["os_app"] for r in mixed] == ["OsApp_AsilC_Core1"]
    assert sorted(mixed[0]["asils"]) == ["C", "QM"]


@pytest.mark.neo4j
@needs_neo4j
def test_neo4j_other_queries(neo4j_session):
    assert [r["core"] for r in run_query(neo4j_session, "mixed_criticality_cores")] == ["Core0"]
    assert [r["os_app"] for r in run_query(neo4j_session, "trusted_partitions")] == ["OsApp_AsilC_Core0"]
    assert run_query(neo4j_session, "unmapped_runnables") == []
